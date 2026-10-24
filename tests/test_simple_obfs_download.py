#!/usr/bin/env python3
"""Exercise the real pinned OpenWrt downloader and independently audit its archive.

The Linux CI gate enables this network integration test. Only rules.mk build
variables and the package compilation targets are shimmed; download.mk, both
download programs, the fw876 recipe, Git clones, tar, xz, and hashes are real.
"""
import hashlib
import importlib.util
import io
import json
import lzma
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
FRAMEWORK_COMMIT = '3fd1e27a511851b41cf082b067b60099e8e026c4'
FRAMEWORK_URL = 'https://raw.githubusercontent.com/VIKINGYFY/immortalwrt/' + FRAMEWORK_COMMIT + '/'
FRAMEWORK_FILES = {
    'include/download.mk': 'd3ab6d3764a1e521998418588cfc76e0108fc8064f11dcd18e1b080ca1191d57',
    'scripts/download.pl': 'd0c58207bca31c52f9a6fdf35dbd28ce67d069ba860255705b808bf24e05d663',
    'scripts/dl_github_archive.py': 'cc2f595483ac5fba569e255addd35026f6aa9e60b258494fc34ace3c9ea2e508',
    'scripts/projectsmirrors.json': '67ffb50ee96976fd70a99de3a6c553104b07444ffeeb858545c57d56d642aa53',
}
SOURCE_URL = 'https://github.com/shadowsocks/simple-obfs.git'
SOURCE_COMMIT = '486bebd9208539058e57e23a12f23103016e09b4'
SUBMODULE_URL = 'https://github.com/shadowsocks/libcork.git'
SUBMODULE_COMMIT = 'f02984545061c924808e4b9ea7cc6749a41f1979'
PREFIX = 'simple-obfs-0.0.5'
ARCHIVE_SHA256 = 'da5af052265fbfba7a11ee4195257f9bc13f44d054d8fdcbace0639360870035'
TAR_SHA256 = '369a65861e5046a1fc2be77f6426bd2ea262afabbcbbef679cf7898ce434248b'
OLD_SHA256 = '7a0154d2de18373e52783d1b64cf5204471049c2d2c64f0b3323d7f430aa4275'
TIMESTAMP = 1566028858
REQUIRED = os.environ.get('REQUIRE_SIMPLE_OBFS_DOWNLOAD') == '1'

if REQUIRED and sys.platform != 'linux':
    raise RuntimeError('The required simple-obfs download gate needs Linux tar/xz and file modes')
if REQUIRED:
    missing = [name for name in ('make', 'git', 'perl', 'curl', 'flock', 'tar', 'xz') if not shutil.which(name)]
    if missing:
        raise RuntimeError('Required simple-obfs download tools missing: ' + ', '.join(missing))


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def git(repository, *arguments):
    # Global Windows autocrlf settings must not change archive payload bytes.
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-C', str(repository), *arguments])


def clone_tree(destination, url, commit):
    # Fetch the pinned tree with its blobs in one transfer. Partial clones cause
    # cat-file --batch to fetch hundreds of individual blobs on this code path.
    destination.mkdir(parents=True)
    subprocess.run(['git', 'init', '--quiet', str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'remote', 'add', 'origin', url], check=True)
    subprocess.run(['git', '-C', str(destination), 'fetch', '--depth=1', 'origin', commit],
                   check=True, timeout=120, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if git(destination, 'rev-parse', commit + '^{commit}').decode().strip() != commit:
        raise AssertionError('Wrong source commit: ' + url)
    result = {}
    for record in git(destination, 'ls-tree', '-rz', commit).split(b'\0'):
        if record:
            metadata, name = record.split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            result[name.decode()] = (mode, kind, oid)
    return result


def blobs(repository, tree):
    records = [(path, mode, oid) for path, (mode, kind, oid) in tree.items() if kind == 'blob']
    raw = subprocess.check_output(['git', '-C', str(repository), 'cat-file', '--batch'],
                                  input=('\n'.join(oid for _, _, oid in records) + '\n').encode())
    offset, result = 0, {}
    for path, mode, oid in records:
        end = raw.index(b'\n', offset)
        actual, kind, size = raw[offset:end].decode().split()
        if (actual, kind) != (oid, 'blob'):
            raise AssertionError('Unexpected Git object')
        size = int(size)
        data = raw[end + 1:end + 1 + size]
        if hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + data).hexdigest() != oid:
            raise AssertionError('Git blob content mismatch: ' + path)
        result[path] = (mode, data)
        offset = end + size + 2
    return result


def independent_payload(directory):
    """Build expected payload from Git objects, without using the downloader."""
    directory.mkdir(parents=True, exist_ok=True)
    main = directory / 'main'
    sub = directory / 'libcork'
    main_tree = clone_tree(main, SOURCE_URL, SOURCE_COMMIT)
    sub_tree = clone_tree(sub, SUBMODULE_URL, SUBMODULE_COMMIT)
    if main_tree.get('libcork') != ('160000', 'commit', SUBMODULE_COMMIT):
        raise AssertionError('Wrong libcork gitlink')
    if any(kind == 'commit' for _, kind, _ in sub_tree.values()):
        raise AssertionError('Unreviewed nested submodule')
    if int(git(main, 'show', '-s', '--format=%ct', SOURCE_COMMIT)) != TIMESTAMP:
        raise AssertionError('Wrong source timestamp')
    files = blobs(main, main_tree)
    gitmodules = files.pop('.gitmodules')[1].decode()
    if 'path = libcork' not in gitmodules or 'url = ' + SUBMODULE_URL not in gitmodules:
        raise AssertionError('Wrong submodule source')
    files.update(('libcork/' + name, item) for name, item in blobs(sub, sub_tree).items())
    # The exact upstream rawgit implementation removes the root .git directory
    # and .gitmodules, but leaves this submodule administrative pointer file.
    files['libcork/.git'] = ('100644', b'gitdir: ../.git/modules/libcork\n')
    entries = {PREFIX: (tarfile.DIRTYPE, 0o755, b'')}
    for name, (mode, data) in files.items():
        path = PREFIX + '/' + name
        entries[path] = (tarfile.SYMTYPE if mode == '120000' else tarfile.REGTYPE,
                         int(mode, 8) & 0o777, data)
        for parent in PurePosixPath(path).parents:
            if str(parent) != '.':
                entries.setdefault(str(parent), (tarfile.DIRTYPE, 0o755, b''))
    if len(files) != 279 or len(entries) != 321:
        raise AssertionError('Unexpected source payload size')
    return entries


def rebuild_archive(entries, output, xz='xz'):
    """Reproduce GNU tar order/metadata from Git objects, then encode with xz."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.GNU_FORMAT) as archive:
        for name in sorted(entries, key=lambda path: tuple(path.split('/'))):
            kind, mode, data = entries[name]
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.mtime = kind, mode, TIMESTAMP
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            if kind == tarfile.SYMTYPE:
                info.linkname = data.decode()
            if kind == tarfile.REGTYPE:
                info.size = len(data)
            archive.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    raw = buffer.getvalue()
    if hashlib.sha256(raw).hexdigest() != TAR_SHA256:
        raise AssertionError('Independently reconstructed tar differs')
    # XZ >=5.6 uses the multithreaded container format by default, including
    # single-block inputs. Make that format explicit in this independent path.
    data = subprocess.check_output([str(xz), '-zc', '-7e', '-T0'], input=raw)
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise AssertionError('Independently reconstructed xz differs')
    output.write_bytes(data)


def verify_payload(path, expected):
    actual = {}
    with tarfile.open(path) as archive:
        for item in archive:
            if item.name in actual:
                raise AssertionError('Duplicate archive member: ' + item.name)
            data = archive.extractfile(item).read() if item.isfile() else item.linkname.encode()
            actual[item.name] = (item.type, item.mode, data)
            if (item.uid, item.gid, item.mtime) != (0, 0, TIMESTAMP):
                raise AssertionError('Unexpected archive metadata: ' + item.name)
    if actual != expected:
        raise AssertionError('Downloaded payload differs from the pinned Git objects')


def setup_framework(build):
    for relative, expected in FRAMEWORK_FILES.items():
        data = urllib.request.urlopen(FRAMEWORK_URL + relative, timeout=45).read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise AssertionError('Download framework drift: ' + relative)
        path = build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.suffix in ('.py', '.pl'):
            path.chmod(0o755)
    for name in ('dl', 'tmp'):
        (build / name).mkdir()
    # Keep the actual download.pl mirror/fallback machinery, but use an empty
    # mirror catalog in this disposable fixture. Public mirrors may later gain
    # the old archive; they must not make the mandatory rawgit path disappear.
    # Both actual source repository URLs and commits remain the fw876 recipe's.
    mirror_file = build / 'scripts/projectsmirrors.json'
    mirrors = json.loads(mirror_file.read_text())
    mirrors['@IMMORTALWRT'] = []
    mirrors['@OPENWRT'] = []
    mirror_file.write_text(json.dumps(mirrors))
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
    (build / 'include/package.mk').write_text('include $(INCLUDE_DIR)/download.mk\n$(eval $(call Download,default))\n')
    # mkhash is a host tool unrelated to source acquisition. Preserve its stdin
    # and filename interfaces while using Python's real SHA implementation.
    (build / 'scripts/mkhash').write_text('''#!/usr/bin/env python3
import hashlib, pathlib, sys
data = pathlib.Path(sys.argv[2]).read_bytes() if len(sys.argv) > 2 else sys.stdin.buffer.read()
print(hashlib.new(sys.argv[1], data).hexdigest())
''')
    (build / 'scripts/mkhash').chmod(0o755)


@unittest.skipUnless(REQUIRED, 'actual source download is required by the Linux CI gate')
class SimpleObfsDownload(unittest.TestCase):
    def test_real_stage_download_rebuild_and_hash_rejection(self):
        for name in ('make', 'git', 'perl', 'curl', 'flock', 'tar', 'xz'):
            self.assertIsNotNone(shutil.which(name), 'Missing required download tool: ' + name)
        loader = module('obfs_download_loader', 'wrt_core/managed_plugins.py')
        adapter = module('obfs_download_adapter', 'wrt_core/simple_obfs_compat.py')
        with tempfile.TemporaryDirectory(prefix='obfs-real-download-') as temporary:
            build = Path(temporary)
            setup_framework(build)
            package = build / 'custom_feed/simple-obfs'
            loader.stage_package(ROOT / 'wrt_core/managed', 'simple-obfs', package, build)
            environment = dict(os.environ, LC_ALL='C', GIT_CONFIG_COUNT='1',
                               GIT_CONFIG_KEY_0='core.autocrlf', GIT_CONFIG_VALUE_0='false')
            environment.pop('DOWNLOAD_MIRROR', None)
            environment.pop('XZ_OPT', None)
            environment.pop('XZ_DEFAULTS', None)
            print(subprocess.check_output(['xz', '--version'], text=True).strip(), flush=True)

            def download(label):
                result = subprocess.run(['make', '-f', str(package / 'Makefile'),
                                         'TOPDIR=' + str(build), 'download', '-j1', 'V=s'],
                                        cwd=build, env=environment, capture_output=True,
                                        text=True, timeout=240)
                (build / (label + '.log')).write_text(result.stdout + result.stderr)
                return result

            old = download('original')
            self.assertNotEqual(old.returncode, 0, 'Original bad hash must fail in the actual downloader')
            archive = build / 'dl' / (PREFIX + '.tar.xz')
            self.assertTrue(archive.is_file(), old.stdout + old.stderr)
            original_archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertIn(original_archive_hash, {
                ARCHIVE_SHA256,
                'be5d0534ee8d373b741c9d543ecadfa79662ade5626c5d3ab33e804a60836950',
            }, 'Unexpected unadapted XZ format')
            self.assertIn('expected ' + OLD_SHA256 + ', got ' + original_archive_hash, old.stdout + old.stderr)
            self.assertIn('Packing checkout...', old.stdout + old.stderr)
            self.assertIn(SUBMODULE_COMMIT, old.stdout + old.stderr)
            payload = independent_payload(build / 'independent')
            independently_built = build / 'independent.tar.xz'
            rebuild_archive(payload, independently_built)
            verify_payload(archive, payload)
            self.assertEqual(lzma.decompress(archive.read_bytes()), lzma.decompress(independently_built.read_bytes()))
            print('simple-obfs independent Git tree + GNU tar/XZ reconstruction: PASS (279 files)', flush=True)

            # Force a second real source acquisition with the production adapter.
            archive.unlink()
            adapter.prepare(package)
            fixed = download('adapted')
            self.assertEqual(fixed.returncode, 0, fixed.stdout + fixed.stderr)
            self.assertIn('Packing checkout...', fixed.stdout + fixed.stderr)
            self.assertIn(SUBMODULE_COMMIT, fixed.stdout + fixed.stderr)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), ARCHIVE_SHA256)
            self.assertEqual(archive.read_bytes(), independently_built.read_bytes())
            verify_payload(archive, payload)
            print('simple-obfs real managed stage -> adaptation -> clean download: PASS', flush=True)

            # The corrected recipe must still enforce integrity on a fresh fetch.
            makefile = package / 'Makefile'
            makefile.write_text(makefile.read_text().replace(ARCHIVE_SHA256, '0' * 64))
            archive.unlink()
            invalid = download('invalid-hash')
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn('expected ' + '0' * 64 + ', got ' + ARCHIVE_SHA256, invalid.stdout + invalid.stderr)
            print('simple-obfs wrong hash rejected by actual download.mk: PASS', flush=True)


if __name__ == '__main__':
    unittest.main()
