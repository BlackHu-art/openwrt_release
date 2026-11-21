#!/usr/bin/env python3
"""Exercise source locking with real Git repositories and native feed inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'wrt_core/feeds_lock.py'
LOCK = ROOT / 'wrt_core/feeds.lock.json'


def git(directory, *arguments):
    return subprocess.check_output(['git', '-C', str(directory), *arguments], text=True, stderr=subprocess.PIPE).strip()


def commit(directory, text):
    (directory / 'revision').write_text(text)
    git(directory, 'add', '.')
    git(directory, '-c', 'user.name=Feed test', '-c', 'user.email=feed@example.invalid', 'commit', '-qm', text)
    return git(directory, 'rev-parse', 'HEAD')


class FeedLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='feed-lock-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / 'feed upstream'
        self.remote.mkdir()
        git(self.remote, 'init', '-q')
        self.pin = commit(self.remote, 'A')
        self.newer = commit(self.remote, 'B')
        self.feed_url = self.remote.as_uri()
        self.tree = self.root / 'build-tree'
        self.tree.mkdir()
        git(self.tree, 'init', '-q')
        self.core_url = (self.root / 'core upstream.git').as_uri()
        git(self.tree, 'remote', 'add', 'origin', self.core_url)
        self.conf = self.tree / 'feeds.conf.default'
        self.original = '# keep this comment\nsrc-git packages ' + self.feed_url + ';main\n'
        self.conf.write_text(self.original)
        self.core = commit(self.tree, 'core')
        self.lock = self.root / 'feeds.lock.json'
        self.data = {
            'schema': 1,
            'feed_sets': {'fixture': {'packages': {'url': self.feed_url, 'commit': self.pin}}},
            'cores': [{'url': self.core_url, 'commit': self.core, 'feed_set': 'fixture'}],
        }
        self.write_lock()

    def write_lock(self):
        self.lock.write_text(json.dumps(self.data, indent=2) + '\n')

    def call(self, action, *arguments):
        return subprocess.run([sys.executable, str(ADAPTER), '--lock', str(self.lock), action, *map(str, arguments)], text=True, capture_output=True)

    def expect_error(self, result, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Feed lock error:', result.stderr)
        self.assertIn(message, result.stderr)

    def checkout(self, revision):
        destination = self.tree / 'feeds/packages'
        destination.parent.mkdir(exist_ok=True)
        subprocess.run(['git', 'clone', '-q', self.feed_url, str(destination)], check=True)
        git(destination, 'checkout', '-q', '--detach', revision)
        return destination

    def test_prepare_writes_native_immutable_source_and_is_idempotent(self):
        result = self.call('prepare', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.conf.read_text(), '# keep this comment\nsrc-git packages ' + self.feed_url + '^' + self.pin + '\n')
        stamp = self.conf.stat().st_mtime_ns
        result = self.call('prepare', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.conf.stat().st_mtime_ns, stamp)

    def test_unknown_core_origin_and_head_leave_configuration_untouched(self):
        for drift in ('origin', 'head'):
            with self.subTest(drift=drift):
                if drift == 'origin':
                    git(self.tree, 'remote', 'set-url', 'origin', 'https://example.invalid/other.git')
                else:
                    git(self.tree, 'remote', 'set-url', 'origin', self.core_url)
                    commit(self.tree, 'unknown core')
                self.expect_error(self.call('prepare', self.tree), 'Unknown core')
                self.assertEqual(self.conf.read_text(), self.original)

    def test_all_feed_inputs_are_validated_before_any_write(self):
        invalid = {
            'origin': 'src-git packages https://example.invalid/other.git\n',
            'missing': '# no packages feed\n',
            'duplicate': self.original + self.original,
            'unknown': self.original + 'src-git unexpected https://example.invalid/new.git\n',
            'type': 'src-link packages /some/local/path\n',
        }
        for name, text in invalid.items():
            with self.subTest(name=name):
                self.conf.write_text(text)
                self.expect_error(self.call('prepare', self.tree), '')
                self.assertEqual(self.conf.read_text(), text)
                self.assertEqual(list(self.tree.glob('.feeds-lock-*')), [])

    def test_append_feed_is_locked_and_appended_exactly_once(self):
        self.data['feed_sets']['fixture']['addon'] = {
            'url': 'https://example.invalid/addon.git', 'commit': 'f' * 40, 'append': True,
        }
        self.write_lock()
        for _ in range(2):
            result = self.call('prepare', self.tree)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.conf.read_text().count('src-git addon https://example.invalid/addon.git^' + 'f' * 40), 1)

    def test_ignored_upstream_feeds_are_removed_only_after_validation(self):
        self.conf.write_text(self.original + 'src-git packages_ext https://example.invalid/extras.git\n')
        result = self.call('prepare', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('packages_ext', self.conf.read_text())

    def test_reused_stale_checkout_is_rejected_before_configuration_changes(self):
        self.checkout(self.newer)
        self.expect_error(self.call('prepare', self.tree), 'HEAD')
        self.assertEqual(self.conf.read_text(), self.original)

    def test_preflight_rejects_drift_without_erasing_reused_checkout(self):
        self.checkout(self.newer)
        before = self.conf.read_bytes()
        result = self.call('preflight', self.tree, '--repo-url', self.core_url, '--commit', self.core)
        self.expect_error(result, 'HEAD')
        self.assertEqual(self.conf.read_bytes(), before)
        self.assertEqual(git(self.tree / 'feeds/packages', 'rev-parse', 'HEAD'), self.newer)

    def test_atomic_fetch_never_publishes_default_head_and_can_retry(self):
        self.assertEqual(self.call('prepare', self.tree).returncode, 0)
        result = self.call('fetch', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.tree / 'feeds/packages', 'rev-parse', 'HEAD'), self.pin)
        self.assertEqual((self.tree / 'feeds/packages/revision').read_text(), 'A')
        self.assertEqual(self.call('fetch', self.tree).returncode, 0)

    def test_missing_pinned_commit_leaves_no_partial_checkout(self):
        self.data['feed_sets']['fixture']['packages']['commit'] = 'f' * 40
        self.write_lock()
        self.assertEqual(self.call('prepare', self.tree).returncode, 0)
        result = self.call('fetch', self.tree)
        self.expect_error(result, 'Git failed')
        self.assertFalse((self.tree / 'feeds/packages').exists())
        self.data['feed_sets']['fixture']['packages']['commit'] = self.pin
        self.write_lock()
        self.assertEqual(self.call('prepare', self.tree).returncode, 0)
        result = self.call('fetch', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_zero_exit_scan_errors_and_missing_indexes_are_rejected(self):
        self.assertEqual(self.call('prepare', self.tree).returncode, 0)
        self.checkout(self.pin)
        log = self.root / 'index.log'
        log.write_text('ERROR: please fix feeds/packages/broken/Makefile - see dump.txt\n')
        self.expect_error(self.call('check-index', self.tree, '--log', log), 'scan failed')
        log.write_text('Create index file packages.index\n')
        self.expect_error(self.call('check-index', self.tree, '--log', log), 'index')
        (self.tree / 'feeds/packages.index').write_text('')
        result = self.call('check-index', self.tree, '--log', log)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_install_requires_expected_local_registration_and_symlink(self):
        self.assertEqual(self.call('prepare', self.tree).returncode, 0)
        self.checkout(self.pin)
        self.expect_error(self.call('verify', self.tree, '--custom'), 'custom_feed')
        custom = self.tree / 'custom_feed'
        custom.mkdir()
        self.conf.write_text(self.conf.read_text() + 'src-link custom_feed ' + custom.as_posix() + '\n')
        (self.tree / 'feeds/custom_feed').symlink_to(custom, target_is_directory=True)
        result = self.call('verify', self.tree, '--custom')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.conf.write_text(self.conf.read_text().replace(custom.as_posix(), self.root.as_posix()))
        self.expect_error(self.call('verify', self.tree, '--custom'), 'custom_feed')

    def test_verify_checks_real_commit_and_remote_and_accepts_derived_changes(self):
        result = self.call('prepare', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = self.checkout(self.pin)
        (checkout / 'revision').write_text('local compatibility patch')
        result = self.call('verify', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        git(checkout, 'restore', 'revision')
        git(checkout, 'checkout', '-q', '--detach', self.newer)
        self.expect_error(self.call('verify', self.tree), 'HEAD')
        git(checkout, 'checkout', '-q', '--detach', self.pin)
        git(checkout, 'remote', 'set-url', 'origin', 'https://example.invalid/drift.git')
        self.expect_error(self.call('verify', self.tree), 'origin')

    def test_verify_requires_fetched_tree_and_locked_configuration(self):
        self.expect_error(self.call('verify', self.tree), 'locked')
        result = self.call('prepare', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.expect_error(self.call('verify', self.tree), 'Missing feed checkout')
        self.checkout(self.pin)
        self.conf.write_text(self.original)
        self.expect_error(self.call('verify', self.tree), 'locked')

    def test_duplicate_lock_entries_origins_or_malformed_sha_are_rejected(self):
        bad_documents = [
            '{"schema":1,"schema":1}',
            {**self.data, 'cores': self.data['cores'] * 2},
            {**self.data, 'feed_sets': {'fixture': {
                'packages': {'url': self.feed_url, 'commit': 'abcd'},
            }}},
            {**self.data, 'feed_sets': {'fixture': {
                'packages': {'url': self.feed_url, 'commit': self.pin},
                'duplicate-origin': {'url': self.feed_url, 'commit': self.pin},
            }}},
        ]
        for document in bad_documents:
            with self.subTest(document=document):
                self.lock.write_text(document if isinstance(document, str) else json.dumps(document))
                self.expect_error(self.call('prepare', self.tree), '')
                self.assertEqual(self.conf.read_text(), self.original)

    def test_identity_includes_feed_lock_and_refuses_unknown_core(self):
        arguments = ['--repo-url', self.core_url, '--commit', self.core]
        initial = self.call('identity', *arguments)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertEqual(initial.stdout.strip(), hashlib.sha256(self.lock.read_bytes()).hexdigest())
        self.data['review_note'] = 'another reviewed lock'
        self.write_lock()
        changed = self.call('identity', *arguments)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertNotEqual(initial.stdout, changed.stdout)
        self.expect_error(self.call('identity', '--repo-url', self.core_url, '--commit', '0' * 40), 'Unknown core')

    def test_feeds_conf_override_is_the_only_configuration_modified(self):
        override = self.tree / 'feeds.conf'
        override.write_text(self.original)
        result = self.call('prepare', self.tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('^' + self.pin, override.read_text())
        self.assertEqual(self.conf.read_text(), self.original)

    def test_nested_or_symlinked_tree_does_not_borrow_parent_repository(self):
        nested = self.tree / 'nested'
        nested.mkdir()
        (nested / 'feeds.conf.default').write_text(self.original)
        self.expect_error(self.call('prepare', nested), 'Git root')
        self.conf.unlink()
        outside = self.root / 'outside.conf'
        outside.write_text(self.original)
        self.conf.symlink_to(outside)
        self.expect_error(self.call('prepare', self.tree), 'symlink')
        self.assertEqual(outside.read_text(), self.original)

    def shell_fixture(self):
        base = self.root / 'wrt_core'
        base.mkdir()
        shutil.copy(ADAPTER, base / ADAPTER.name)
        shutil.copy(self.lock, base / LOCK.name)
        scripts = self.tree / 'scripts'
        scripts.mkdir()
        feeds = scripts / 'feeds'
        feeds.write_text('''#!/usr/bin/env python3
import os, pathlib, subprocess, sys
root = pathlib.Path(os.environ.get('TOPDIR', pathlib.Path.cwd()))
with (root / 'events').open('a') as output: output.write(' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['update', '-i']:
    for line in (root / 'feeds.conf.default').read_text().splitlines():
        if not line or line.startswith('#'): continue
        kind, name, source = line.split()
        target = root / 'feeds' / name
        if kind != 'src-link':
            url, sha = source.split('^')
            actual = subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
            assert actual == sha, 'unverified HEAD reached indexing'
            if os.environ.get('WRONG_HEAD'):
                subprocess.run(['git','-C',str(target),'fetch','-q','origin',os.environ['WRONG_HEAD']],check=True)
                subprocess.run(['git','-C',str(target),'checkout','-q','--detach',os.environ['WRONG_HEAD']],check=True)
        (root / 'feeds' / (name + '.index')).write_text('')
    # Match include/scan.mk: a noninteractive inherited setting can suppress
    # diagnostics even though a partial index is published with exit status 0.
    if os.environ.get('INDEX_ERROR') and os.environ.get('IS_TTY', os.environ.get('MAKE_TERMOUT', '1')) == '1':
        print('ERROR: please fix feeds/packages/broken/Makefile - see dump.txt')
''')
        feeds.chmod(0o755)
        # Production currently touches bpf.mk; a real core has include/.
        (self.tree / 'include').mkdir()
        return base

    def run_shell(self, wrong_head=None, index_error=False):
        base = self.shell_fixture()
        script = '''set -e
source "$MODULE"
BASE_PATH="$TEST_BASE"
BUILD_DIR="$TEST_TREE"
FEEDS_CONF=feeds.conf.default
network_retry() { "$@"; }
cd "$BUILD_DIR"
update_feeds
mkdir -p "$BUILD_DIR/custom_feed"
ln -s "$BUILD_DIR/custom_feed" "$BUILD_DIR/feeds/custom_feed"
printf 'src-link custom_feed %s\\n' "$BUILD_DIR/custom_feed" >> "$BUILD_DIR/feeds.conf.default"
run_feed_index custom custom_feed
install_feeds
'''
        environment = {**os.environ, 'MODULE': str(ROOT / 'wrt_core/modules/feeds.sh'),
                       'TEST_BASE': str(base), 'TEST_TREE': str(self.tree), 'TOPDIR': str(self.root / 'unrelated'),
                       'IS_TTY': '0', 'MAKE_TERMOUT': '/dev/pts/0'}
        if wrong_head:
            environment['WRONG_HEAD'] = wrong_head
        if index_error:
            environment['INDEX_ERROR'] = '1'
        return subprocess.run(['bash', '-c', script], text=True, capture_output=True, env=environment)

    def test_shell_uses_immutable_input_before_update_and_index(self):
        result = self.run_shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.tree / 'events').read_text().splitlines(), ['update -i', 'update -i custom_feed', 'update -i', 'install -a -f'])
        self.assertEqual(git(self.tree / 'feeds/packages', 'rev-parse', 'HEAD'), self.pin)

    def test_shell_refuses_wrong_fetched_head_before_install_index(self):
        result = self.run_shell(self.newer)
        self.expect_error(result, 'HEAD')
        self.assertEqual((self.tree / 'events').read_text().splitlines(), ['update -i'])

    def test_native_success_status_does_not_hide_scan_failure(self):
        result = self.run_shell(index_error=True)
        self.expect_error(result, 'scan failed')
        self.assertEqual((self.tree / 'events').read_text().splitlines(), ['update -i'])

    def test_reused_tree_stage_checks_drift_before_cleaning(self):
        self.checkout(self.newer)
        base = self.root / 'wrt_core'
        base.mkdir()
        shutil.copy(ADAPTER, base / ADAPTER.name)
        shutil.copy(self.lock, base / LOCK.name)
        script = '''source "$UPDATE_SCRIPT"
clone_repo() { touch "$BUILD_DIR/cloned"; }
clean_up() { touch "$BUILD_DIR/cleaned"; }
reset_feeds_conf() { :; }
stage_repo_checkout
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
            env={**os.environ, 'UPDATE_SCRIPT': str(ROOT / 'wrt_core/update.sh'),
                 'BASE_PATH': str(base), 'BUILD_DIR': str(self.tree), 'REPO_URL': self.core_url,
                 'COMMIT_HASH': self.core})
        self.expect_error(result, 'HEAD')
        self.assertFalse((self.tree / 'cleaned').exists())
        self.assertFalse((self.tree / 'cloned').exists())

    def test_reused_tree_switch_cleans_known_core_before_changing_tracked_files(self):
        scripts = self.tree / 'scripts'
        scripts.mkdir()
        feeds = scripts / 'feeds'
        feeds.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "$TOPDIR/../clean-events"\n')
        feeds.chmod(0o755)
        first = commit(self.tree, 'first reviewed core')
        second = commit(self.tree, 'second reviewed core')
        self.data['cores'] = [dict(url=self.core_url, commit=sha, feed_set='fixture') for sha in (first, second)]
        self.write_lock()
        git(self.tree, 'checkout', '-q', '--detach', first)
        (self.tree / 'revision').write_text('local LAN customization')
        (self.tree / 'feeds').mkdir()
        base = self.root / 'wrt_core'
        base.mkdir()
        shutil.copy(ADAPTER, base / ADAPTER.name)
        shutil.copy(self.lock, base / LOCK.name)
        result = subprocess.run(['bash', '-c', 'set -e; source "$UPDATE_SCRIPT"; stage_repo_checkout'],
            capture_output=True, text=True, env={**os.environ,
                'UPDATE_SCRIPT': str(ROOT / 'wrt_core/update.sh'), 'BASE_PATH': str(base),
                'BUILD_DIR': str(self.tree), 'REPO_URL': self.core_url, 'COMMIT_HASH': second,
                'FEEDS_CONF': 'feeds.conf.default', 'NETWORK_RETRY_MAX': '1'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.tree, 'rev-parse', 'HEAD'), second)
        self.assertEqual((self.tree / 'revision').read_text(), 'second reviewed core')
        self.assertEqual((self.root / 'clean-events').read_text().splitlines(), ['clean'])

    def test_reused_tree_failed_native_cleanup_aborts_before_reset(self):
        scripts = self.tree / 'scripts'
        scripts.mkdir()
        feeds = scripts / 'feeds'
        feeds.write_text('#!/usr/bin/env bash\necho "native clean failure" >&2\nexit 42\n')
        feeds.chmod(0o755)
        (self.tree / 'feeds').mkdir()
        (self.tree / 'revision').write_text('local customization before failed clean')
        base = self.root / 'wrt_core'
        base.mkdir()
        shutil.copy(ADAPTER, base / ADAPTER.name)
        shutil.copy(self.lock, base / LOCK.name)
        result = subprocess.run(['bash', '-c', 'set -e; source "$UPDATE_SCRIPT"; stage_repo_checkout'],
            capture_output=True, text=True, env={**os.environ,
                'UPDATE_SCRIPT': str(ROOT / 'wrt_core/update.sh'), 'BASE_PATH': str(base),
                'BUILD_DIR': str(self.tree), 'REPO_URL': self.core_url, 'COMMIT_HASH': self.core,
                'NETWORK_RETRY_MAX': '1'})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native clean failure', result.stderr)
        self.assertEqual((self.tree / 'revision').read_text(), 'local customization before failed clean')
        self.assertFalse((self.tree / 'tmp/.build').exists())

    def test_shell_unknown_source_does_not_mutate_configuration_or_run_feeds(self):
        self.conf.write_text('src-git packages https://example.invalid/drift.git\n')
        before = self.conf.read_bytes()
        result = self.run_shell()
        self.expect_error(result, 'origin')
        self.assertEqual(self.conf.read_bytes(), before)
        self.assertFalse((self.tree / 'events').exists())


class ProductionSourceLockTests(unittest.TestCase):
    def test_config_preview_exposes_lock_identity_for_all_profiles(self):
        bash = shutil.which('bash')
        version = subprocess.check_output([bash, '-c', 'echo ${BASH_VERSINFO[0]}'], text=True).strip()
        if int(version) < 4:
            self.skipTest('config_preview requires existing project Bash >=4.3')
        digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()
        for profile in sorted((ROOT / 'wrt_core/compilecfg').glob('*.ini')):
            with self.subTest(profile=profile.name):
                result = subprocess.run([bash, str(ROOT / 'build.sh'), profile.stem, 'config_preview'], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Feed lock SHA-256: ' + digest, result.stdout)
                self.assertIn('Feed packages:', result.stdout)

    def test_every_profile_has_reviewed_immutable_source_identity(self):
        profiles = sorted((ROOT / 'wrt_core/compilecfg').glob('*.ini'))
        self.assertEqual(len(profiles), 18)
        for profile in profiles:
            with self.subTest(profile=profile.name):
                fields = dict(line.split('=', 1) for line in profile.read_text().splitlines() if '=' in line)
                result = subprocess.run([sys.executable, str(ADAPTER), 'identity', '--repo-url', fields['REPO_URL'], '--commit', fields.get('COMMIT_HASH', 'none')], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout.strip(), r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
