#!/usr/bin/env python3
"""Fetch the exact fw876 Linux test core; never run it or download on import."""
import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import time
import urllib.request


TAG = 'v198.2'
SOURCE_COMMIT = '45893d778767f3bdb2fcb6e873cf8f9a667d94d4'
VERSION = '26.10.21-r2'
ASSET = 'xray-core_' + VERSION + '_x86_64.ipk'
URL = 'https://github.com/fw876/helloworld/releases/download/' + TAG + '/' + ASSET
ARCHIVE_SHA256 = '790fd76aacedfb5ec75721470323050fe119de546b354c9fbfce0560acd49153'
EXECUTABLE_SHA256 = '8275f03f7715326c6de6b3e25e1f4fa6991738002ac33e620f114437b76236aa'
MAX_BYTES = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _name(value):
    value = value.removeprefix('./').rstrip('/')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value:
        raise ValueError('unsafe archive name')
    return value


def _tar_members(data, wanted):
    found = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for index, entry in enumerate(archive):
            if index > 10000:
                raise ValueError('too many package entries')
            name = _name(entry.name)
            if name not in wanted:
                continue
            if name in found or not entry.isfile() or entry.size > MAX_BYTES:
                raise ValueError('duplicate, non-regular or oversized archive entry: ' + name)
            found[name] = archive.extractfile(entry).read(MAX_BYTES + 1)
    return found


def _ar_members(data):
    found, offset = {}, 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b'`\n':
            raise ValueError('invalid ar header')
        name = _name(header[:16].decode('ascii').strip())
        size = int(header[48:58].decode('ascii').strip())
        if name in found or size < 0 or size > MAX_BYTES or offset + 60 + size > len(data):
            raise ValueError('invalid ar member')
        found[name] = data[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
    return found


def extract_core(data, *, archive_sha256=ARCHIVE_SHA256, executable_sha256=EXECUTABLE_SHA256):
    if len(data) > MAX_BYTES or digest(data) != archive_sha256:
        raise ValueError('fw876 archive SHA-256 mismatch')
    wanted = {'debian-binary', 'control.tar.gz', 'data.tar.gz'}
    members = _ar_members(data) if data.startswith(b'!<arch>\n') else _tar_members(data, wanted)
    if not wanted.issubset(members) or members['debian-binary'] != b'2.0\n':
        raise ValueError('invalid OpenWrt IPK container')
    controls = _tar_members(members['control.tar.gz'], {'control'})
    if 'control' not in controls:
        raise ValueError('missing package identity')
    fields = {}
    for line in controls['control'].decode('utf-8').splitlines():
        if ': ' not in line or line.startswith((' ', '\t')):
            continue
        key, value = line.split(': ', 1)
        if key in fields:
            raise ValueError('duplicate package identity field')
        fields[key] = value
    expected = {'Package': 'xray-core', 'Version': VERSION, 'Architecture': 'x86_64'}
    if any(fields.get(key) != value for key, value in expected.items()):
        raise ValueError('unexpected fw876 package identity')
    binaries = _tar_members(members['data.tar.gz'], {'usr/bin/xray'})
    if 'usr/bin/xray' not in binaries:
        raise ValueError('missing usr/bin/xray')
    executable = binaries['usr/bin/xray']
    if digest(executable) != executable_sha256:
        raise ValueError('fw876 executable SHA-256 mismatch')
    if executable[:7] != b'\x7fELF\x02\x01\x01' or executable[18:20] != b'\x3e\x00':
        raise ValueError('fw876 executable is not a Linux x86_64 ELF')
    return executable


def fetch_core(output, archive=None):
    output = Path(output).resolve()
    if archive is None:
        request = urllib.request.Request(URL, headers={'User-Agent': 'openwrt-release-core-tests'})
        data, started = bytearray(), time.monotonic()
        with urllib.request.urlopen(request, timeout=30) as response:
            while chunk := response.read(1024 * 1024):
                data.extend(chunk)
                if len(data) > MAX_BYTES or time.monotonic() - started > 120:
                    raise ValueError('fw876 download exceeds size or time limit')
        data = bytes(data)
    else:
        data = Path(archive).read_bytes()
    executable = extract_core(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fw876-verified-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'xray'
        staged.write_bytes(executable)
        staged.chmod(0o755)
        os.replace(staged, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--archive', type=Path, help='optional already downloaded IPK; same hash checks apply')
    args = parser.parse_args()
    output = fetch_core(args.output, args.archive)
    print('fw876/' + TAG + ' Xray ' + VERSION + '; SHA-256=' + EXECUTABLE_SHA256)
    print(output)


if __name__ == '__main__':
    main()
