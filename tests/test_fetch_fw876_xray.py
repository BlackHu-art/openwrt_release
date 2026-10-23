#!/usr/bin/env python3
"""The custom core gate must authenticate the package and executable identity."""
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ELF = b'\x7fELF\x02\x01\x01' + bytes(11) + b'\x3e\x00' + bytes(44)


def tar_payload(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, data, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(data) if kind == tarfile.REGTYPE else 0
            entry.mode = 0o755
            if kind == tarfile.SYMTYPE:
                entry.linkname = '/host/xray'
            archive.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
    return output.getvalue()


def package(*, container='ar', identity=None, payload=None):
    control = (identity or 'Package: xray-core\nVersion: 26.10.21-r2\nArchitecture: x86_64\n').encode()
    entries = [('debian-binary', b'2.0\n', tarfile.REGTYPE),
               ('control.tar.gz', tar_payload([('control', control, tarfile.REGTYPE)]), tarfile.REGTYPE),
               ('data.tar.gz', tar_payload(payload or [('usr/bin/xray', ELF, tarfile.REGTYPE)]), tarfile.REGTYPE)]
    if container == 'tar':
        return tar_payload(entries)
    output = bytearray(b'!<arch>\n')
    for name, data, _ in entries:
        output.extend(f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{0o100644:<8o}{len(data):<10}`\n'.encode())
        output.extend(data)
        if len(data) % 2:
            output.extend(b'\n')
    return bytes(output)


class FetchFw876Core(unittest.TestCase):
    def setUp(self):
        source = ROOT / 'tests/fetch_fw876_xray.py'
        self.assertTrue(source.is_file(), 'fw876 package identity gate is not implemented')
        spec = importlib.util.spec_from_file_location('fw_fetch_under_test', source)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def extract(self, data, **overrides):
        values = {'archive_sha256': hashlib.sha256(data).hexdigest(),
                  'executable_sha256': hashlib.sha256(ELF).hexdigest()}
        values.update(overrides)
        return self.module.extract_core(data, **values)

    def test_reads_exact_xray_from_both_openwrt_ipk_containers(self):
        for container in ('ar', 'tar'):
            with self.subTest(container=container):
                self.assertEqual(self.extract(package(container=container)), ELF)

    def test_rejects_changed_download_before_parsing(self):
        with self.assertRaisesRegex(ValueError, 'archive.*SHA-256'):
            self.extract(package(), archive_sha256='0' * 64)

    def test_rejects_official_or_other_binary_with_same_version(self):
        with self.assertRaisesRegex(ValueError, 'executable.*SHA-256'):
            self.extract(package(), executable_sha256='0' * 64)

    def test_rejects_wrong_package_version_or_architecture(self):
        correct = 'Package: xray-core\nVersion: 26.10.21-r2\nArchitecture: x86_64\n'
        for old, new in (('xray-core', 'other-core'), ('26.10.21-r2', '26.10.21-r1'),
                         ('x86_64', 'aarch64_cortex-a53')):
            with self.subTest(field=old), self.assertRaisesRegex(ValueError, 'identity'):
                self.extract(package(identity=correct.replace(old, new)))

    def test_rejects_link_and_duplicate_executable(self):
        for payload in ([('usr/bin/xray', b'', tarfile.SYMTYPE)],
                        [('usr/bin/xray', ELF, tarfile.REGTYPE)] * 2):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.extract(package(payload=payload))

    def test_rejects_missing_executable(self):
        with self.assertRaisesRegex(ValueError, 'xray'):
            self.extract(package(payload=[('usr/bin/unrelated', ELF, tarfile.REGTYPE)]))


if __name__ == '__main__':
    unittest.main()
