#!/usr/bin/env python3
"""Lock native OpenWrt feed inputs to a reviewed core origin and commit.

Fetches are staged at exact commits before publication. OpenWrt's own
scripts/feeds then builds indexes from the verified local checkouts only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

DEFAULT_LOCK = Path(__file__).with_name('feeds.lock.json')
SHA = re.compile(r'^[0-9a-f]{40}$')
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')
REMOVED_FEEDS = {'packages_ext', 'small8', 'custom_feed'}


class LockError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LockError(f'Duplicate lock key: {key}')
        result[key] = value
    return result


def origin(url):
    if not isinstance(url, str) or not url or re.search(r'[\s;^\x00-\x1f]', url):
        raise LockError(f'Invalid Git origin: {url!r}')
    if not url.startswith(('https://', 'file:///')):
        raise LockError(f'Unsupported Git origin: {url!r}')
    return url.rstrip('/').removesuffix('.git')


def checked_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise LockError(f'Expected a full lowercase Git commit SHA: {value!r}')
    return value


def read_lock(path):
    raw = path.read_bytes()
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise LockError('Unsupported feed lock schema')
    sets = data.get('feed_sets')
    cores = data.get('cores')
    if not isinstance(sets, dict) or not sets or not isinstance(cores, list) or not cores:
        raise LockError('Feed lock requires nonempty feed_sets and cores')
    for set_name, feeds in sets.items():
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', set_name) or not isinstance(feeds, dict) or not feeds:
            raise LockError(f'Invalid feed set: {set_name}')
        seen_origins = set()
        for name, feed in feeds.items():
            if not NAME.fullmatch(name) or not isinstance(feed, dict):
                raise LockError(f'Invalid locked feed: {name}')
            url = origin(feed.get('url'))
            checked_sha(feed.get('commit'))
            if not isinstance(feed.get('append', False), bool):
                raise LockError(f'Invalid append flag for {name}')
            if url in seen_origins:
                raise LockError(f'Duplicate feed origin in {set_name}: {url}')
            seen_origins.add(url)
    identities = set()
    for core in cores:
        if not isinstance(core, dict):
            raise LockError('Invalid core entry')
        identity = (origin(core.get('url')), checked_sha(core.get('commit')))
        if identity in identities:
            raise LockError(f'Duplicate core identity: {identity}')
        identities.add(identity)
        if core.get('feed_set') not in sets:
            raise LockError(f'Unknown locked feed set: {core.get("feed_set")}')
    return data, hashlib.sha256(raw).hexdigest()


def git(tree, *arguments):
    result = subprocess.run(['git', '-C', str(tree), *arguments], text=True,
                            encoding='utf-8', errors='replace', capture_output=True)
    if result.returncode:
        raise LockError(f'Git failed in {tree}: {result.stderr.strip()}')
    return result.stdout.strip()


def repository_identity(tree):
    if tree.is_symlink():
        raise LockError(f'Repository may not be a symlink: {tree}')
    tree = tree.resolve(strict=True)
    root = Path(git(tree, 'rev-parse', '--show-toplevel')).resolve()
    if root != tree:
        raise LockError(f'Expected Git root {tree}, found {root}')
    urls = git(tree, 'config', '--get-all', 'remote.origin.url').splitlines()
    if len(urls) != 1:
        raise LockError(f'Expected one origin in {tree}')
    return origin(urls[0]), checked_sha(git(tree, 'rev-parse', 'HEAD'))


def select_core(data, url, commit):
    identity = (origin(url), checked_sha(commit))
    for core in data['cores']:
        if identity == (origin(core['url']), core['commit']):
            return core['feed_set'], data['feed_sets'][core['feed_set']]
    raise LockError(f'Unknown core origin/HEAD: {url}@{commit}; review and update the source lock')


def configuration_path(tree):
    override = tree / 'feeds.conf'
    path = override if override.exists() or override.is_symlink() else tree / 'feeds.conf.default'
    if path.is_symlink():
        raise LockError(f'Feed configuration may not be a symlink: {path}')
    if not path.is_file():
        raise LockError(f'Missing feed configuration: {path}')
    return path


def source_origin(source):
    parts = re.fullmatch(r'([^;^]+)(?:[;^]([^;^]+))?', source)
    if not parts:
        raise LockError(f'Invalid native feed source: {source}')
    return origin(parts[1])


def render_configuration(raw, feeds, *, require_locked=False):
    output = []
    seen = set()
    for line in raw.decode('utf-8').splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            output.append(line)
            continue
        fields = stripped.split()
        if len(fields) != 3:
            raise LockError(f'Invalid feed entry: {stripped}')
        kind, name, source = fields
        if name in seen:
            raise LockError(f'Duplicate feed entry: {name}')
        seen.add(name)
        if name in REMOVED_FEEDS:
            # custom_feed is generated locally only after the upstream update.
            if require_locked:
                if name != 'custom_feed' or kind != 'src-link':
                    raise LockError(f'Unexpected removed feed in locked configuration: {name}')
                output.append(line)
            continue
        if name not in feeds:
            raise LockError(f'Unknown feed: {name}')
        feed = feeds[name]
        if kind not in {'src-git', 'src-git-full'}:
            raise LockError(f'Expected remote Git feed {name}, found {kind}')
        if source_origin(source) != origin(feed['url']):
            raise LockError(f'Unexpected feed origin for {name}: {source}')
        locked = f'{feed["url"]}^{feed["commit"]}'
        if require_locked and source != locked:
            raise LockError(f'Feed {name} configuration is not locked to {locked}')
        output.append(f'{kind} {name} {locked}\n')
    missing = set(feeds) - seen
    required = sorted(name for name in missing if require_locked or not feeds[name].get('append', False))
    if required:
        raise LockError(f'Missing required feeds: {", ".join(required)}')
    for name in sorted(missing):
        feed = feeds[name]
        if output and not output[-1].endswith('\n'):
            output[-1] += '\n'
        output.append(f'src-git {name} {feed["url"]}^{feed["commit"]}\n')
    return ''.join(output).encode('utf-8')


def verify_checkouts(tree, feeds, *, allow_missing=False):
    directory = feed_directory(tree)
    for name, feed in feeds.items():
        path = directory / name
        if not path.exists() and not path.is_symlink():
            if allow_missing:
                continue
            raise LockError(f'Missing feed checkout: {name}')
        url, head = repository_identity(path)
        if url != origin(feed['url']):
            raise LockError(f'Unexpected feed origin for {name}: {url}')
        if head != feed['commit']:
            raise LockError(f'Unexpected feed HEAD for {name}: {head}, expected {feed["commit"]}; clean stale feeds before retrying')


def feed_directory(tree):
    directory = tree / 'feeds'
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise LockError(f'Invalid feed directory: {directory}')
    if directory.resolve().parent != tree.resolve():
        raise LockError(f'Feed directory escapes build tree: {directory}')
    return directory


def verify_custom_feed(tree):
    expected = tree.resolve() / 'custom_feed'
    if expected.is_symlink() or not expected.is_dir():
        raise LockError('Missing or unsafe local custom_feed source')
    entries = [line.split() for line in configuration_path(tree).read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    entries = [fields for fields in entries if len(fields) >= 2 and fields[1] == 'custom_feed']
    if (len(entries) != 1 or len(entries[0]) != 3 or entries[0][0] != 'src-link'
            or not Path(entries[0][2]).is_absolute()
            or Path(entries[0][2]).resolve() != expected):
        raise LockError('custom_feed registration must point to this build tree')
    link = feed_directory(tree) / 'custom_feed'
    if not link.is_symlink() or link.resolve() != expected:
        raise LockError('custom_feed worktree link must point to this build tree')


def fetch_locked(tree, data):
    # Never let a failed default-branch clone become an indexable checkout.
    # Only a fully fetched, detached and verified commit is published. A retry
    # reuses complete pinned feeds and starts failed temporary fetches afresh.
    url, head = repository_identity(tree)
    _, feeds = select_core(data, url, head)
    render_configuration(configuration_path(tree).read_bytes(), feeds, require_locked=True)
    verify_checkouts(tree, feeds, allow_missing=True)
    directory = feed_directory(tree)
    directory.mkdir(exist_ok=True)
    for name, feed in feeds.items():
        target = directory / name
        if target.exists():
            continue
        with tempfile.TemporaryDirectory(prefix='.locked-feed-', dir=directory) as temporary:
            checkout = Path(temporary) / name
            checkout.mkdir()
            git(checkout, 'init', '-q')
            git(checkout, 'remote', 'add', 'origin', feed['url'])
            git(checkout, 'fetch', '--depth', '1', '--no-tags', 'origin', feed['commit'])
            git(checkout, '-c', 'advice.detachedHead=false', 'checkout', '--detach', feed['commit'])
            git(checkout, 'submodule', 'update', '--init', '--recursive', '--depth', '1')
            if repository_identity(checkout) != (origin(feed['url']), feed['commit']):
                raise LockError(f'Fetched feed identity mismatch: {name}')
            os.replace(checkout, target)
    verify_checkouts(tree, feeds)


def check_index(tree, data, log, only=None, custom=False):
    # Native update_index() can return zero even when prepare-mk/scan failed.
    # This log is truncated for each invocation, so old dump errors do not count.
    output = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', log.read_text(errors='replace'))
    failures = [line for line in output.splitlines() if
                re.search(r'ERROR:\s*please fix\s|(?:g?make)(?:\[\d+\])?:\s*\*\*\*', line)]
    if failures:
        raise LockError('Feed scan failed: ' + '\n'.join(failures[:10]))
    if only == 'custom_feed':
        verify_custom_feed(tree)
        names = ['custom_feed']
    else:
        url, head = repository_identity(tree)
        _, feeds = select_core(data, url, head)
        names = list(feeds)
        if custom:
            verify_custom_feed(tree)
            names.append('custom_feed')
    directory = feed_directory(tree)
    for name in names:
        index = directory / (name + '.index')
        if not index.is_file() or not index.resolve().is_relative_to(directory.resolve()):
            raise LockError(f'Missing or unsafe feed package index: {name}')


def replace_atomically(path, contents):
    if path.read_bytes() == contents:
        return
    handle, temporary = tempfile.mkstemp(prefix='.feeds-lock-', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as target:
            target.write(contents)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def operate(tree, data, *, verify=False, dry_run=False, custom=False):
    url, head = repository_identity(tree)
    set_name, feeds = select_core(data, url, head)
    path = configuration_path(tree)
    contents = render_configuration(path.read_bytes(), feeds, require_locked=verify)
    verify_checkouts(tree, feeds, allow_missing=not verify)
    if custom:
        verify_custom_feed(tree)
    if not verify and not dry_run:
        replace_atomically(path, contents)
    return set_name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'verify', 'fetch', 'preflight', 'check-index'):
        command = commands.add_parser(name)
        command.add_argument('tree', type=Path)
        command.add_argument('--custom', action='store_true')
        if name == 'preflight':
            command.add_argument('--repo-url', required=True)
            command.add_argument('--commit', required=True)
        if name == 'check-index':
            command.add_argument('--log', type=Path, required=True)
            command.add_argument('--only', choices=['custom_feed'])
    for name in ('identity', 'describe'):
        command = commands.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument('--repo-url')
        source.add_argument('--tree', type=Path)
        command.add_argument('--commit')
    args = parser.parse_args(argv)
    try:
        data, digest = read_lock(args.lock)
        if args.command in {'identity', 'describe'}:
            if args.tree is not None:
                url, head = repository_identity(args.tree)
            else:
                url, head = args.repo_url, args.commit
            set_name, feeds = select_core(data, url, head)
            if args.command == 'identity':
                print(digest)
            else:
                print(f'  Feed set: {set_name}')
                print(f'  Feed lock SHA-256: {digest}')
                for name, feed in feeds.items():
                    print(f'  Feed {name}: {feed["commit"]}')
        elif args.command == 'fetch':
            fetch_locked(args.tree, data)
            print('Locked feeds fetched and verified before indexing')
        elif args.command == 'check-index':
            check_index(args.tree, data, args.log, args.only, args.custom)
            print('Feed package indexes verified')
        else:
            if args.command == 'preflight':
                select_core(data, args.repo_url, args.commit)
                actual_url, _ = repository_identity(args.tree)
                if actual_url != origin(args.repo_url):
                    raise LockError('Build checkout origin differs from requested core')
            set_name = operate(args.tree, data, verify=args.command == 'verify',
                               dry_run=args.command == 'preflight', custom=args.custom)
            print(f'Feed lock {args.command}: {set_name} ({digest})')
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(f'Feed lock error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
