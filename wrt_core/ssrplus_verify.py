#!/usr/bin/env python3
"""Prepare pinned fw876 SSR and verify artifacts against its trusted manifest.

IPK ar and OpenWrt tar containers and APK v2 are read without extraction.
APK v3 requires a host apk-tools supporting adbdump JSON and extract; this
never installs the package, runs package scripts, or executes target binaries.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

MANIFEST_TARGET = "/usr/share/shadowsocksr/ssrplus-build.json"
PACKAGE_NAME = "luci-app-ssr-plus"
SOURCE_COMMIT = "45893d778767f3bdb2fcb6e873cf8f9a667d94d4"
# Upstream Git mode 120000 entries for this pinned revision. Managed storage
# keeps link text; the production feed loader restores these directory links.
SOURCE_LINKS = {"po/zh-cn": "zh_Hans"}


class VerificationError(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_object(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise VerificationError("duplicate JSON field: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def target_parts(target):
    if (not isinstance(target, str) or not target.startswith("/") or
            "\\" in target or "\0" in target or
            any(part in ("", ".", "..") for part in target.split("/")[1:])):
        raise VerificationError("invalid absolute protected path: " + repr(target))
    return PurePosixPath(target).parts[1:]


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise VerificationError("manifest must be a JSON object")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit", ""))):
        raise VerificationError("manifest source_commit must be a full Git commit")
    if (not isinstance(manifest.get("repair_version"), str) or
            not re.fullmatch(r"[A-Za-z0-9_.+~-]+", manifest["repair_version"])):
        raise VerificationError("manifest repair_version is missing or invalid")
    patches = manifest.get("patches")
    if not isinstance(patches, dict) or not patches:
        raise VerificationError("manifest must identify the source repair patches")
    for name, checksum in patches.items():
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise VerificationError("invalid patch name")
        if not re.fullmatch(r"[0-9a-f]{64}", str(checksum)):
            raise VerificationError("invalid patch SHA-256: " + name)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise VerificationError("manifest must protect at least one file")
    for target, expected in files.items():
        target_parts(target)
        if target == MANIFEST_TARGET:
            raise VerificationError("manifest cannot recursively hash itself")
        if not isinstance(expected, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(expected.get("sha256", ""))):
            raise VerificationError("invalid protected SHA-256: " + target)
        if not re.fullmatch(r"[0-7]{4}", str(expected.get("mode", ""))):
            raise VerificationError("protected modes must be four-digit octal strings: " + target)
    return manifest


def root_file(root, target):
    path = Path(root).resolve()
    if not path.is_dir():
        raise VerificationError("root directory does not exist: " + str(root))
    for part in target_parts(target):
        path = path / part
        if path.is_symlink():
            raise VerificationError("protected path must not use symlinks: " + target)
    if not path.is_file():
        raise VerificationError("missing protected file: " + target)
    return path


def verify_files(manifest, read):
    embedded, _ = read(MANIFEST_TARGET)
    if json_object(embedded) != manifest:
        raise VerificationError("embedded SSR repair manifest differs from the trusted source manifest")
    for target, expected in manifest["files"].items():
        data, mode = read(target)
        if sha256(data) != expected["sha256"]:
            raise VerificationError("SHA-256 mismatch: " + target)
        if stat.S_IMODE(mode) != int(expected["mode"], 8):
            raise VerificationError(f"mode mismatch: {target}: expected {expected['mode']}, got {stat.S_IMODE(mode):04o}")


def verify_rootfs(manifest, root):
    def read(target):
        path = root_file(root, target)
        return path.read_bytes(), path.stat().st_mode
    verify_files(manifest, read)


def archive_name(name):
    while name.startswith("./"):
        name = name[2:]
    if name in ("", "."):
        return ""
    # Directory trailing slashes are harmless; absolute and traversal members
    # are rejected even though tar payloads are never extracted by this code.
    name = name.rstrip("/")
    target_parts("/" + name)
    return name


def tar_entries(data, wanted=None):
    entries = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*", ignore_zeros=True) as archive:
        for member in archive:
            name = archive_name(member.name)
            if not name or member.isdir() or (wanted is not None and name not in wanted):
                continue
            if not member.isfile():
                raise VerificationError("protected archive entry is not a regular file: " + name)
            if name in entries:
                raise VerificationError("duplicate archive entry: " + name)
            stream = archive.extractfile(member)
            if stream is None:
                raise VerificationError("unreadable archive entry: " + name)
            entries[name] = (stream.read(), member.mode)
    return entries


def ar_entries(data):
    if not data.startswith(b"!<arch>\n"):
        raise VerificationError("invalid ar package header")
    entries, offset = {}, 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:] != b"`\n":
            raise VerificationError("truncated or invalid ar member")
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        offset += 60
        if not name or name in entries or size < 0 or offset + size > len(data):
            raise VerificationError("invalid or duplicate ar member: " + name)
        entries[name] = (data[offset:offset + size], 0)
        offset += size + size % 2
    return entries


def package_identity(name, version, expected_version):
    if name != PACKAGE_NAME:
        raise VerificationError("wrong compiled package name: " + str(name))
    # opkg uses 198-2 while apk uses 198-r2 for the same recipe release.
    normalize = lambda value: re.sub(r"-r([0-9]+)$", r"-\1", str(value))
    if normalize(version) != normalize(expected_version):
        raise VerificationError(f"compiled package version mismatch: expected {expected_version}, got {version}")


def text_fields(data, separator):
    fields = {}
    for line in data.decode("utf-8").splitlines():
        if separator in line:
            key, value = line.split(separator, 1)
            fields[key.strip()] = value.strip()
    return fields


def native_apk(manifest, package, tool):
    if not tool:
        raise VerificationError("APK v3 needs a host apk-tools with adbdump/extract; pass --apk-tool <path>")
    dump = subprocess.run([str(tool), "adbdump", "--format", "json", str(package.resolve())],
                          capture_output=True, text=True, timeout=60)
    if dump.returncode:
        raise VerificationError("host apk adbdump failed: " + dump.stderr.strip())
    metadata = json_object(dump.stdout)
    candidates = []

    def find_info(value):
        if isinstance(value, dict):
            info = value.get("info")
            if isinstance(info, dict) and "name" in info and "version" in info:
                candidates.append(info)
            for child in value.values():
                find_info(child)
        elif isinstance(value, list):
            for child in value:
                find_info(child)

    find_info(metadata)
    if len(candidates) != 1:
        raise VerificationError("host apk adbdump did not identify exactly one package")
    package_identity(candidates[0]["name"], candidates[0]["version"], manifest["repair_version"])
    with tempfile.TemporaryDirectory(prefix="ssrplus-apk-") as destination:
        result = subprocess.run([str(tool), "--allow-untrusted", "extract", "--no-chown",
                                 "--destination", destination, str(package.resolve())],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise VerificationError("host apk extract failed: " + result.stderr.strip())
        verify_rootfs(manifest, destination)


def verify_package(manifest, package, apk_tool=None):
    package = Path(package)
    data = package.read_bytes()
    wanted = {target.lstrip("/") for target in manifest["files"]} | {MANIFEST_TARGET.lstrip("/")}
    if package.suffix == ".ipk":
        outer = ar_entries(data) if data.startswith(b"!<arch>\n") else tar_entries(data)
        if outer.get("debian-binary", (b"",))[0].strip() != b"2.0":
            raise VerificationError("IPK debian-binary must identify format 2.0")
        archives = {}
        for prefix in ("control.tar", "data.tar"):
            matches = [value[0] for name, value in outer.items() if name == prefix or name.startswith(prefix + ".")]
            if len(matches) != 1:
                raise VerificationError("IPK must contain exactly one " + prefix + " archive")
            archives[prefix] = matches[0]
        control = tar_entries(archives["control.tar"], {"control"})
        if "control" not in control:
            raise VerificationError("IPK control metadata is missing")
        fields = text_fields(control["control"][0], ":")
        package_identity(fields.get("Package"), fields.get("Version"), manifest["repair_version"])
        entries = tar_entries(archives["data.tar"], wanted)
    elif package.suffix == ".apk":
        if data.startswith(b"ADB"):
            return native_apk(manifest, package, apk_tool)
        if not data.startswith(b"\x1f\x8b"):
            raise VerificationError("unsupported APK format; provide --apk-tool for APK v3")
        entries = tar_entries(data, wanted | {".PKGINFO"})
        if ".PKGINFO" not in entries:
            raise VerificationError("APK v2 .PKGINFO metadata is missing")
        fields = text_fields(entries[".PKGINFO"][0], "=")
        package_identity(fields.get("pkgname"), fields.get("pkgver"), manifest["repair_version"])
    else:
        raise VerificationError("compiled package must have .ipk or .apk suffix")

    def read(target):
        if target.lstrip("/") not in entries:
            raise VerificationError("missing protected package file: " + target)
        return entries[target.lstrip("/")]
    verify_files(manifest, read)


def create_manifest(arguments):
    overrides = {}
    for override in getattr(arguments, "file_mode_override", None) or []:
        if override.count("=") != 1:
            raise VerificationError("file mode override must be PATH=MODE: " + override)
        target, mode = override.split("=")
        try:
            target_parts(target)
        except VerificationError as error:
            raise VerificationError("invalid file mode override: " + str(error)) from error
        if target not in arguments.file:
            raise VerificationError("file mode override must name a protected path: " + target)
        if target in overrides:
            raise VerificationError("duplicate file mode override: " + target)
        if mode not in ("0755", "0644"):
            raise VerificationError("file mode override must use 0755 or 0644: " + override)
        overrides[target] = mode
    patches = {}
    for path in arguments.patch:
        path = Path(path)
        if path.name in patches:
            raise VerificationError("duplicate patch name: " + path.name)
        patches[path.name] = sha256(path.read_bytes())
    files = {}
    for target in arguments.file:
        if target in files:
            raise VerificationError("duplicate protected path: " + target)
        path = root_file(arguments.root, target)
        files[target] = {"sha256": sha256(path.read_bytes()),
                         "mode": overrides.get(target) or arguments.file_mode or f"{stat.S_IMODE(path.stat().st_mode):04o}"}
    result = validate_manifest({"source_commit": arguments.source_commit, "repair_version": arguments.repair_version,
                                "patches": patches, "files": files})
    Path(arguments.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_source_link(package, relative, target, expected_blob):
    """Accept only the recorded package-local translation directory alias."""
    data = target.encode("utf-8")
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != expected_blob:
        raise VerificationError("source symlink lock mismatch: " + relative)
    path = package / relative
    if not path.is_symlink():
        raise VerificationError("source symlink missing or replaced: " + relative)
    if os.readlink(path) != target:
        raise VerificationError("source symlink target mismatch: " + relative)
    destination = package
    for part in target_parts("/" + (PurePosixPath(relative).parent / target).as_posix()):
        destination = destination / part
        if destination.is_symlink():
            raise VerificationError("source symlink target uses another symlink: " + relative)
    if not destination.is_dir() or not destination.resolve().is_relative_to(package):
        raise VerificationError("source symlink target must be an existing package directory: " + relative)


def prepare_source(core, package):
    """Apply only reviewed package integration, rejecting unknown upstream bytes.

    Every original file is locked, including LuCI and updater sources. Reviewed
    integration covers package dependencies/modes, Xray transport and updates;
    init and DNS remain upstream bytes.
    Work is staged in a private tree so drift never partially patches a feed.
    """
    core, package = Path(core).resolve(), Path(package).resolve()
    table = core / "compat/ssrplus/source-files.tsv"
    expected = {}
    for line in table.read_text(encoding="utf-8").splitlines():
        blob, relative, mode = line.split()
        target_parts("/" + relative)
        if relative in expected or not re.fullmatch(r"[0-9a-f]{40}", blob):
            raise VerificationError("invalid or duplicate source lock: " + relative)
        if mode not in ("-", "0644", "0755") or (mode == "-") == relative.startswith("root/"):
            raise VerificationError("invalid installed source mode: " + relative)
        expected[relative] = (blob, mode)
    if not expected:
        raise VerificationError("empty upstream source lock")
    for relative, target in SOURCE_LINKS.items():
        if relative not in expected or expected[relative][1] != "-":
            raise VerificationError("source symlink missing from upstream lock: " + relative)
        verify_source_link(package, relative, target, expected[relative][0])
    marker = package / ".ssrplus-upstream-commit"
    if marker.exists() and marker.read_text().strip() != SOURCE_COMMIT:
        raise VerificationError("SSR source commit differs from the pinned fw876 revision")
    manifest_relative = "root" + MANIFEST_TARGET
    allowed = set(expected) | {".ssrplus-upstream-commit", manifest_relative}
    present = set()
    for path in package.rglob("*"):
        relative = path.relative_to(package).as_posix()
        if relative in SOURCE_LINKS:
            present.add(relative)
            continue
        if path.is_symlink():
            raise VerificationError("source must not use symlinks: " + relative)
        if path.is_file():
            if relative not in allowed:
                raise VerificationError("unexpected source file: " + relative)
            present.add(relative)
    missing = set(expected) - present
    if missing:
        raise VerificationError("missing upstream source file: " + sorted(missing)[0])
    patches = []
    for name in (core / "compat/ssrplus/patches.list").read_text().splitlines():
        if not name or "/" in name or "\\" in name or name in [p.name for p in patches]:
            raise VerificationError("invalid integration patch name: " + name)
        patch = core / "patches" / name
        if not patch.is_file():
            raise VerificationError("missing integration patch: " + name)
        patches.append(patch)
    with tempfile.TemporaryDirectory(prefix="ssrplus-v198-") as temporary:
        staged = Path(temporary)
        def git(*args, check=True):
            result = subprocess.run(["git", "-C", str(staged), *args], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=60)
            if check and result.returncode:
                raise VerificationError("SSR integration failed: " + result.stderr.strip())
            return result.returncode == 0
        git("init", "-q")
        git("config", "core.autocrlf", "false")
        for relative in expected:
            if relative in SOURCE_LINKS:
                continue
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root_file(package, "/" + relative), target)
        for patch in reversed(patches):
            if git("apply", "--reverse", "--check", str(patch), check=False):
                git("apply", "--reverse", str(patch))
        for relative, (blob, _mode) in expected.items():
            if relative in SOURCE_LINKS:
                continue
            data = (staged / relative).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != blob:
                raise VerificationError("unreviewed upstream source drift: " + relative)
        for patch in patches:
            git("apply", str(patch))
        files = {}
        for relative, (_blob, mode) in expected.items():
            if mode != "-":
                target = staged / relative
                target.chmod(int(mode, 8))
                files["/" + relative[5:]] = {"sha256": sha256(target.read_bytes()), "mode": mode}
        manifest = validate_manifest({"source_commit": SOURCE_COMMIT, "repair_version": "198-r2",
            "patches": {patch.name: sha256(patch.read_bytes()) for patch in patches}, "files": files})
        current = package / manifest_relative
        if current.exists() and json_object(current.read_bytes()) != manifest:
            raise VerificationError("prepared source manifest drift")
        (staged / manifest_relative).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for relative in [*expected, manifest_relative]:
            # Integration only changes canonical translation files. Never
            # dereference, rewrite or replace the validated upstream alias.
            if relative in SOURCE_LINKS:
                continue
            source, destination = staged / relative, package / relative
            mode = expected[relative][1] if relative in expected else "0644"
            if not destination.exists() or source.read_bytes() != destination.read_bytes():
                # mkstemp starts at 0600 on POSIX; preserve source modes for
                # LuCI/recipe files instead of copying that temporary policy.
                publish_mode = (stat.S_IMODE(destination.stat().st_mode)
                                if mode == "-" else int(mode, 8))
                descriptor, temporary_file = tempfile.mkstemp(prefix=destination.name + ".ssrfix.", dir=destination.parent)
                try:
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(source.read_bytes())
                    os.chmod(temporary_file, publish_mode)
                    os.replace(temporary_file, destination)
                finally:
                    Path(temporary_file).unlink(missing_ok=True)
            if mode != "-":
                destination.chmod(int(mode, 8))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="prepare pinned fw876 v198.2 with reviewed integration patches")
    prepare.add_argument("--core", required=True)
    prepare.add_argument("--package", required=True)
    manifest = commands.add_parser("manifest", help="record the reviewed source repair identity")
    manifest.add_argument("--root", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--source-commit", required=True)
    manifest.add_argument("--repair-version", required=True)
    manifest.add_argument("--patch", action="append", required=True)
    manifest.add_argument("--file", action="append", required=True)
    manifest.add_argument("--file-mode", choices=("0755", "0644"),
                          help="explicit installed mode policy, also usable on non-POSIX source hosts")
    manifest.add_argument("--file-mode-override", action="append", metavar="PATH=MODE",
                          help="override installed mode for a protected --file path (0755 or 0644); repeatable")
    for command in ("rootfs", "package"):
        child = commands.add_parser(command)
        child.add_argument("--manifest", required=True, help="trusted manifest from repaired source, never from the artifact")
        child.add_argument("--root" if command == "rootfs" else "--package", required=True)
        if command == "package":
            child.add_argument("--apk-tool", help="host apk-tools with adbdump JSON and extract for APK v3")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "prepare":
            prepare_source(arguments.core, arguments.package)
        elif arguments.command == "manifest":
            create_manifest(arguments)
        else:
            expected = validate_manifest(json_object(Path(arguments.manifest).read_bytes()))
            if arguments.command == "rootfs":
                verify_rootfs(expected, arguments.root)
            else:
                verify_package(expected, arguments.package, arguments.apk_tool)
        print("SSR artifact verification: PASS (" + arguments.command + ")")
        return 0
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        print("SSR artifact verification failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
