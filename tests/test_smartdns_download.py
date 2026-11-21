#!/usr/bin/env python3
"""Exercise canonical SmartDNS core and pinned WebUI source acquisition.

Offline checks expand both locked OpenWrt download frameworks with GNU make.
The Linux REQUIRE_SMARTDNS_DOWNLOAD gate performs real core/WebUI downloads,
checks all payload bytes against independently read Git trees/blobs, verifies
core extraction/patch paths and rejects wrong hashes in the real downloaders.
Only build variables, package compilation and the Rust include are shimmed.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/smartdns-download/3fd1e27a/download.mk'
SOURCE_URL = 'https://github.com/pymumu/smartdns-webui.git'
SOURCE_COMMIT = '3261c18b1b93d841e86d9e727557109ae71d71cd'
SOURCE_TREE = '190f76f34cfda865389b27e8f69887aa6a64edc3'
CORE_COMMIT = '136c0c2690138d6dedd8b520281aafe49112643f'
CORE_URL = 'https://www.github.com/pymumu/smartdns.git'
CORE_CODELOAD_URL = 'https://codeload.github.com/pymumu/smartdns/tar.gz'
CORE_PREFIX = 'smartdns-' + CORE_COMMIT
CORE_ARCHIVE_NAME = CORE_PREFIX + '.tar.gz'
CORE_ARCHIVE_SHA256 = 'fd7bfb126ba15764d89a3a57efbea67602105a7bf394f81b7b5dd81693ddc5cb'
CORE_TREE = '4f7381b2b6778f5f6b96d7e2dbdf7167753d2b52'
CORE_TIMESTAMP = 1769178721
MODERN_COMMIT = '000a4e74b17edfdc296f9eaa674344fc0adaaf95'
MODERN_URL = 'https://raw.githubusercontent.com/LiBwrt/openwrt-6.x/' + MODERN_COMMIT + '/'
MODERN_FILES = {
    'include/download.mk': 'd06a7ba7746d65121bd6d374dcad1e4fca359b675f23fe5b89522849fe99077f',
    'scripts/download.pl': 'd0c58207bca31c52f9a6fdf35dbd28ce67d069ba860255705b808bf24e05d663',
    'scripts/dl_github_archive.py': 'b1a5d9bb356c8931d26ff4c87786c4238559f3d92d1090199e21cd2b57ab5dad',
    'scripts/projectsmirrors.json': 'dbc6449558d25f51af0d746b4558d509feaffcdf2939671aaa505a21b8e780f2',
}
PREFIX = 'smartdns-webui'
ARCHIVE_NAME = 'smartdns-webui-1.0.0.tar.gz'
ARCHIVE_SHA256 = '4401734712dd034eb1088ce440d1bc64d053dfcd6f63f66c08cd48ab68593042'
TAR_SHA256 = 'a203faeeb55271853270e0e84907d29d4e32043cf1bc86f4e45a4e78ff92816f'
TIMESTAMP = 1766583635
REQUIRED = os.environ.get('REQUIRE_SMARTDNS_DOWNLOAD') == '1'
DOWNLOAD_TOOLS = ('bash', 'make', 'git', 'perl', 'curl', 'flock', 'tar', 'gzip', 'patch')
BASH = os.environ.get('BASH') or (
    'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash'))

if REQUIRED and sys.platform != 'linux':
    raise RuntimeError('The required SmartDNS download gate needs Linux tar/gzip and file modes')
if REQUIRED:
    missing = [name for name in DOWNLOAD_TOOLS if not shutil.which(name)]
    if missing:
        raise RuntimeError('Required SmartDNS download tools missing: ' + ', '.join(missing))


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


# Reuse authenticated framework acquisition and generic Git-object readers;
# none of the simple-obfs-specific expected payload or archive code is used.
framework = module('smartdns_download_framework', 'tests/test_simple_obfs_download.py')


def make_available():
    if not BASH or (not Path(BASH).is_file() and not shutil.which(BASH)):
        return False
    result = subprocess.run([BASH, '--noprofile', '--norc', '-c', 'command -v make'],
                            capture_output=True, text=True, timeout=15)
    return result.returncode == 0


def setup_recipe(build, network=False, core="legacy"):
    """Use real download rules, leaving compilation and Rust outside this test."""
    if network:
        framework.setup_framework(build)
        if core == "25.12":
            for relative, expected in MODERN_FILES.items():
                data = urllib.request.urlopen(MODERN_URL + relative, timeout=45).read()
                if hashlib.sha256(data).hexdigest() != expected:
                    raise AssertionError('Modern SmartDNS framework drift: ' + relative)
                (build / relative).write_bytes(data)
            mirrors = build / 'scripts/projectsmirrors.json'
            catalog = json.loads(mirrors.read_text())
            catalog['@IMMORTALWRT'] = catalog['@OPENWRT'] = []
            mirrors.write_text(json.dumps(catalog))
    else:
        fixture = FIXTURE if core == "legacy" else FIXTURE.parents[1] / '000a4e74/download.mk'
        data = fixture.read_bytes()
        expected = (framework.FRAMEWORK_FILES if core == "legacy" else MODERN_FILES)['include/download.mk']
        if hashlib.sha256(data).hexdigest() != expected:
            raise AssertionError('Offline download.mk fixture drift')
        (build / 'include').mkdir(parents=True)
        (build / 'include/download.mk').write_bytes(data)
        for name in ('dl', 'tmp', 'scripts'):
            (build / name).mkdir()
        (build / '.config').write_text('CONFIG_DOWNLOAD_CHECK_CERTIFICATE=y\n')
        (build / 'rules.mk').write_text(r'''INCLUDE_DIR:=$(TOPDIR)/include
DL_DIR:=$(TOPDIR)/dl
TMP_DIR:=$(TOPDIR)/tmp
SCRIPT_DIR:=$(TOPDIR)/scripts
TAR:=tar
MKHASH:=$(SCRIPT_DIR)/mkhash
CONFIG_DOWNLOAD_CHECK_CERTIFICATE:=y
CONFIG_DOWNLOAD_TOOL_CUSTOM:=
ext=$(word $(words $(subst ., ,$(1))),$(subst ., ,$(1)))
define locked
SHELL= flock $(TMP_DIR)/.$(if $(2),$(strip $(2)),global).flock -c '$(subst ','\'',$(1))'
endef
export TOPDIR TMP_DIR MKHASH
''')
        (build / 'include/package.mk').write_text(
            'include $(INCLUDE_DIR)/download.mk\n$(eval $(call Download,default))\n')
    with (build / 'rules.mk').open('a') as rules:
        rules.write('\nBUILD_DIR:=$(TOPDIR)/build_dir\n')
    package = build / 'package/network/smartdns'
    shutil.copytree(ROOT / 'maintenance/plugins/smartdns/package', package)
    rust = build / 'package/lang/rust/rust-package.mk'
    rust.parent.mkdir(parents=True)
    rust.write_text('# Compilation is outside this download-only fixture.\n')
    with (build / 'include/package.mk').open('a') as makefile:
        makefile.write('\n.PHONY: print-source-dir\nprint-source-dir:\n\t@printf "%s\\n" "$(PKG_BUILD_DIR)"\n')
    return package


def download_environment():
    environment = dict(os.environ, LC_ALL='C', GIT_CONFIG_COUNT='1',
                       GIT_CONFIG_KEY_0='core.autocrlf', GIT_CONFIG_VALUE_0='false')
    for name in ('DOWNLOAD_MIRROR', 'GZIP', 'TAR_OPTIONS', 'XZ_OPT', 'XZ_DEFAULTS'):
        environment.pop(name, None)
    return environment


def run_make(build, selection='', dry_run=True, target='download'):
    # Let MSYS normalize Windows drive paths before make parses target names.
    # No downloaded script is executed by the default offline dry runs.
    script = r'''set -euo pipefail
build=$1
selection=$2
target=$3
shift 3
if command -v cygpath >/dev/null 2>&1; then build=$(cygpath -u "$build"); fi
if [ "$target" = webui ]; then target="$build/dl/smartdns-webui-1.0.0.tar.gz"; fi
if [ "$target" = core ]; then target="$build/dl/smartdns-136c0c2690138d6dedd8b520281aafe49112643f.tar.gz"; fi
cd "$build/package/network/smartdns"
umask 022
make --no-print-directory -f Makefile "TOPDIR=$build" \
    "CONFIG_PACKAGE_smartdns-ui=$selection" "$target" -j1 V=s "$@"
'''
    command = [BASH, '--noprofile', '--norc', '-c', script, 'smartdns-download',
               str(build), selection, target]
    if dry_run:
        command.append('-n')
    return subprocess.run(command, cwd=build, env=download_environment(),
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=300)


def independent_payload(directory):
    """Read expected bytes from the pinned Git objects, not the downloader."""
    tree = framework.clone_tree(directory, SOURCE_URL, SOURCE_COMMIT)
    if framework.git(directory, 'rev-parse', SOURCE_COMMIT + '^{tree}').decode().strip() != SOURCE_TREE:
        raise AssertionError('Wrong WebUI source tree')
    if int(framework.git(directory, 'show', '-s', '--format=%ct', SOURCE_COMMIT)) != TIMESTAMP:
        raise AssertionError('Wrong WebUI source timestamp')
    if any(kind != 'blob' or mode != '100644' for mode, kind, _ in tree.values()):
        raise AssertionError('Unreviewed WebUI submodule, symlink or executable')
    files = framework.blobs(directory, tree)
    if '.gitmodules' in files or files.get('.gitattributes') != ('100644', b'* text=lf'):
        raise AssertionError('Unreviewed git archive export or submodule behavior')
    entries = {PREFIX: (tarfile.DIRTYPE, 0o755, b'')}
    for name, (_, data) in files.items():
        path = PREFIX + '/' + name
        entries[path] = (tarfile.REGTYPE, 0o644, data)
        for parent in PurePosixPath(path).parents:
            if str(parent) != '.':
                entries.setdefault(str(parent), (tarfile.DIRTYPE, 0o755, b''))
    if len(files) != 109 or len(entries) != 151:
        raise AssertionError('Unexpected WebUI source payload size')
    return entries


def rebuild_archive(entries):
    """Reconstruct the GNU tar/gzip archive independently of download.mk."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.GNU_FORMAT) as archive:
        for name in sorted(entries, key=lambda path: tuple(path.split('/'))):
            kind, mode, data = entries[name]
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.mtime = kind, mode, TIMESTAMP
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            if kind == tarfile.REGTYPE:
                info.size = len(data)
            archive.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    raw = buffer.getvalue()
    if hashlib.sha256(raw).hexdigest() != TAR_SHA256:
        raise AssertionError('Independently reconstructed WebUI tar differs')
    data = subprocess.check_output(['gzip', '-nc'], input=raw, env=download_environment())
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise AssertionError('Independently reconstructed WebUI gzip differs')
    return data


def verify_payload(path, expected):
    actual = {}
    with tarfile.open(path) as archive:
        for item in archive:
            if item.name in actual:
                raise AssertionError('Duplicate archive member: ' + item.name)
            if not (item.isdir() or item.isfile()):
                raise AssertionError('Unexpected archive member type: ' + item.name)
            data = archive.extractfile(item).read() if item.isfile() else b''
            actual[item.name] = (item.type, item.mode, data)
            if (item.uid, item.gid, item.mtime, item.uname, item.gname) != (0, 0, TIMESTAMP, '', ''):
                raise AssertionError('Unexpected archive metadata: ' + item.name)
    if actual != expected:
        raise AssertionError('Downloaded WebUI payload differs from pinned Git objects')


@unittest.skipUnless(make_available(), 'GNU make and Bash are needed for download recipe expansion')
class SmartDnsDownloadSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='smartdns-make-')
        self.addCleanup(self.temporary.cleanup)
        self.build = Path(self.temporary.name)
        self.package = setup_recipe(self.build)

    def test_original_recipe_drops_commit_and_downloads_unselected_webui(self):
        # Characterize the real failure: VERSION is ignored by this framework,
        # and unconditional registration makes even an unselected UI download.
        result = run_make(self.build)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(ARCHIVE_NAME, result.stdout)
        self.assertIn('--version=""', result.stdout)
        self.assertNotIn(SOURCE_COMMIT, result.stdout)
        self.assertIn(CORE_COMMIT, result.stdout)

    def test_prepared_recipe_registers_only_selected_ui_with_exact_commit(self):
        original = run_make(self.build)
        self.assertEqual(original.returncode, 0, original.stdout + original.stderr)
        core_command = [line for line in original.stdout.splitlines() if CORE_URL in line]
        self.assertEqual(len(core_command), 1)
        adapter = module('smartdns_make_adapter', 'wrt_core/smartdns_compat.py')
        adapter.prepare(self.package)
        for selection in ('', 'n', 'y', 'm'):
            with self.subTest(selection=selection or 'unset'):
                result = run_make(self.build, selection)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(CORE_COMMIT, result.stdout)
                canonical = [line for line in result.stdout.splitlines() if CORE_CODELOAD_URL in line]
                self.assertEqual(len(canonical), 1)
                self.assertIn(CORE_COMMIT, canonical[0])
                self.assertIn(CORE_ARCHIVE_SHA256, canonical[0])
                self.assertNotIn(CORE_URL, result.stdout)
                if selection in ('y', 'm'):
                    self.assertIn(ARCHIVE_NAME, result.stdout)
                    self.assertIn('--version="' + SOURCE_COMMIT + '"', result.stdout)
                    self.assertIn('git checkout ' + SOURCE_COMMIT, result.stdout)
                    self.assertIn(SOURCE_URL, result.stdout)
                    self.assertIn(ARCHIVE_SHA256, result.stdout)
                else:
                    self.assertNotIn(ARCHIVE_NAME, result.stdout)
                    self.assertNotIn(SOURCE_URL, result.stdout)
                    absent = run_make(self.build, selection, dry_run=False, target='webui')
                    self.assertNotEqual(absent.returncode, 0)
                    self.assertIn('No rule to make target', absent.stderr)
                    self.assertNotIn('download.pl', absent.stdout)
                self.assertFalse((self.build / 'dl' / ARCHIVE_NAME).exists())


    def test_both_locked_frameworks_use_canonical_http_core_archive_and_matching_build_directory(self):
        adapter = module('smartdns_core_make_adapter', 'wrt_core/smartdns_compat.py')
        for core in ('legacy', '25.12'):
            with self.subTest(core=core), tempfile.TemporaryDirectory(prefix='smartdns-core-rules-') as tmp:
                build = Path(tmp)
                package = setup_recipe(build, core=core)
                adapter.prepare(package)
                result = run_make(build, target='core')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(CORE_CODELOAD_URL, result.stdout)
                self.assertIn(CORE_ARCHIVE_SHA256, result.stdout)
                self.assertIn('"' + CORE_COMMIT + '"', result.stdout)
                self.assertNotIn('git clone', result.stdout)
                self.assertNotIn('zstd', result.stdout)
                result = run_make(build, dry_run=False, target='print-source-dir')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                source_path = result.stdout.strip()
                if os.name == 'nt' and len(source_path) > 3 and source_path[0] == '/' and source_path[2] == '/':
                    source_path = source_path[1].upper() + ':' + source_path[2:]
                self.assertEqual(Path(source_path), build / 'build_dir' / CORE_PREFIX)


def independent_core_payload(directory):
    tree = framework.clone_tree(directory, 'https://github.com/pymumu/smartdns.git', CORE_COMMIT)
    if framework.git(directory, 'rev-parse', CORE_COMMIT + '^{tree}').decode().strip() != CORE_TREE:
        raise AssertionError('Wrong SmartDNS core Git tree')
    if int(framework.git(directory, 'show', '-s', '--format=%ct', CORE_COMMIT)) != CORE_TIMESTAMP:
        raise AssertionError('Wrong SmartDNS core timestamp')
    if len(tree) != 445 or any(kind != 'blob' or mode not in ('100644', '100755')
                               for mode, kind, _ in tree.values()):
        raise AssertionError('Unreviewed SmartDNS core file modes/submodules')
    files = framework.blobs(directory, tree)
    if any(name.endswith(('.gitattributes', '.gitmodules')) for name in files):
        raise AssertionError('Unreviewed Git export rules/submodules')
    entries = {CORE_PREFIX: (tarfile.DIRTYPE, 0o775, b'')}
    for name, (mode, data) in files.items():
        path = CORE_PREFIX + '/' + name
        # Codeload preserves git archive's default tar.umask=0002 metadata.
        entries[path] = (tarfile.REGTYPE, (int(mode, 8) & 0o777) | 0o020, data)
        for parent in PurePosixPath(path).parents:
            if str(parent) != '.':
                entries.setdefault(str(parent), (tarfile.DIRTYPE, 0o775, b''))
    if len(entries) != 546:
        raise AssertionError('Unexpected SmartDNS core archive member count')
    return entries


def verify_core_payload(path, expected):
    actual = {}
    with tarfile.open(path) as archive:
        if archive.pax_headers != {'comment': CORE_COMMIT}:
            raise AssertionError('Canonical core archive does not identify the pinned Git commit')
        for item in archive:
            if item.name in actual or not (item.isdir() or item.isfile()):
                raise AssertionError('Unexpected/duplicate SmartDNS core archive member: ' + item.name)
            data = archive.extractfile(item).read() if item.isfile() else b''
            actual[item.name] = (item.type, item.mode, data)
            if (item.uid, item.gid, item.mtime, item.uname, item.gname) != (0, 0, CORE_TIMESTAMP, 'root', 'root'):
                raise AssertionError('Unexpected canonical SmartDNS core metadata: ' + item.name)
    if actual != expected:
        raise AssertionError('Canonical SmartDNS core archive differs from the pinned Git blobs')


@unittest.skipUnless(REQUIRED, 'actual SmartDNS core download is required by the Linux CI gate')
class SmartDnsCoreDownload(unittest.TestCase):
    def test_canonical_core_uses_real_downloaders_verified_git_payload_and_strict_hash(self):
        adapter = module('smartdns_core_real_adapter', 'wrt_core/smartdns_compat.py')
        with tempfile.TemporaryDirectory(prefix='smartdns-core-audit-') as independent:
            expected = independent_core_payload(Path(independent) / 'git')
            canonical = None
            for core in ('legacy', '25.12'):
                with self.subTest(core=core), tempfile.TemporaryDirectory(prefix='smartdns-core-download-') as temporary:
                    build = Path(temporary)
                    package = setup_recipe(build, network=True, core=core)
                    adapter.prepare(package)
                    result = run_make(build, dry_run=False, target='core')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    archive = build / 'dl' / CORE_ARCHIVE_NAME
                    data = archive.read_bytes()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), CORE_ARCHIVE_SHA256)
                    verify_core_payload(archive, expected)
                    if canonical is None:
                        canonical = data
                    self.assertEqual(data, canonical)
                    destination = run_make(build, dry_run=False, target='print-source-dir')
                    self.assertEqual(destination.returncode, 0, destination.stdout + destination.stderr)
                    source_dir = Path(destination.stdout.strip())
                    self.assertEqual(source_dir, build / 'build_dir' / CORE_PREFIX)
                    source_dir.parent.mkdir(parents=True)
                    subprocess.run(['tar', '-xzf', str(archive), '-C', str(source_dir.parent)], check=True)
                    for name in ('100-smartdns-optimize.patch',
                                 '101-smartdns-shutdown-order.patch',
                                 '102-smartdns-dhcp-option.patch',
                                 '103-smartdns-serve-expired-no.patch',
                                 '104-smartdns-expired-cache-config.patch'):
                        patch = subprocess.run(['patch', '-p1', '-F', '0', '-i',
                            str(ROOT / 'wrt_core/patches' / name)], cwd=source_dir,
                            capture_output=True, text=True, timeout=30)
                        self.assertEqual(patch.returncode, 0, patch.stdout + patch.stderr)
                    print('SmartDNS canonical core ' + core + ': 445 pinned Git blobs + build directory/patch paths PASS', flush=True)
                    recipe = package / 'Makefile'
                    recipe.write_bytes(recipe.read_bytes().replace(CORE_ARCHIVE_SHA256.encode(), b'0' * 64))
                    archive.unlink()
                    rejected = run_make(build, dry_run=False, target='core')
                    self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
                    self.assertIn('file: ' + CORE_ARCHIVE_SHA256 + ', requested: ' + '0' * 64,
                                  rejected.stdout + rejected.stderr)
                    self.assertFalse(archive.exists(), 'Incorrectly hashed download must not be published')
                    print('SmartDNS canonical core ' + core + ': real incorrect-hash download rejected', flush=True)


@unittest.skipUnless(REQUIRED, 'actual SmartDNS download is required by the Linux CI gate')
class SmartDnsDownload(unittest.TestCase):
    def test_real_pinned_download_independent_archive_and_hash_rejection(self):
        adapter = module('smartdns_download_adapter', 'wrt_core/smartdns_compat.py')
        with tempfile.TemporaryDirectory(prefix='smartdns-real-download-') as temporary:
            build = Path(temporary)
            package = setup_recipe(build, network=True)
            adapter.prepare(package)
            expected = independent_payload(build / 'independent')
            independently_built = rebuild_archive(expected)
            archive = build / 'dl' / ARCHIVE_NAME
            print('SmartDNS independent pinned Git tree + GNU tar/gzip: PASS (109 files)', flush=True)
            for selection in ('y', 'm'):
                with self.subTest(selection=selection):
                    archive.unlink(missing_ok=True)
                    result = run_make(build, selection, dry_run=False, target='webui')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('--version="' + SOURCE_COMMIT + '"', result.stdout)
                    self.assertTrue(archive.is_file(), result.stdout + result.stderr)
                    self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), ARCHIVE_SHA256)
                    self.assertEqual(archive.read_bytes(), independently_built)
                    verify_payload(archive, expected)
                    print('SmartDNS real fixed-commit download CONFIG_PACKAGE_smartdns-ui=' + selection + ': PASS', flush=True)

            # Fresh actual fetches must still reject the wrong integrity value.
            makefile = package / 'Makefile'
            data = makefile.read_bytes()
            self.assertEqual(data.count(ARCHIVE_SHA256.encode()), 1)
            makefile.write_bytes(data.replace(ARCHIVE_SHA256.encode(), b'0' * 64))
            archive.unlink(missing_ok=True)
            invalid = run_make(build, 'y', dry_run=False, target='webui')
            self.assertNotEqual(invalid.returncode, 0, invalid.stdout + invalid.stderr)
            self.assertIn('expected ' + '0' * 64 + ', got ' + ARCHIVE_SHA256,
                          invalid.stdout + invalid.stderr)
            self.assertTrue(archive.is_file(), invalid.stdout + invalid.stderr)
            verify_payload(archive, expected)
            print('SmartDNS wrong hash rejected by actual download.mk: PASS', flush=True)


if __name__ == '__main__':
    unittest.main()
