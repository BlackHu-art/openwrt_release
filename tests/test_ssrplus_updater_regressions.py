#!/usr/bin/env python3
"""Execute patched update.lua with real Lua 5.1 control flow and file I/O.

Only LuCI/UCI and shell-program boundaries are substituted. Absolute router
paths map into a temporary directory; no network, router or service is used.
Lupa is optional and is never installed automatically by this test.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None


ROOT = Path(__file__).resolve().parents[1]
GFW_SOURCE = ("server=/google.com/127.0.0.1#5335\n"
              "ipset=/google.com/gfwlist\n"
              "server=/corp.example/127.0.0.1#5335\n"
              "ipset=/corp.example/gfwlist\n").encode()


class ScriptExit(Exception):
    def __init__(self, code):
        self.code = int(code)


@unittest.skipUnless(LuaRuntime, "optional lupa.lua51 is required to execute the real updater")
class UpdaterRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssr-updater-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.filesystem = self.base / "filesystem"
        self.filesystem.mkdir()
        package = self.base / "package"
        init = package / "root/etc/init.d/shadowsocksr"
        share = package / "root/usr/share/shadowsocksr"
        init.parent.mkdir(parents=True)
        share.mkdir(parents=True)
        fixtures = ROOT / "tests/fixtures/ssrplus/2abdc9aa"
        shutil.copyfile(fixtures / "shadowsocksr.init", init)
        for name in ("gfw2ipset.sh", "update.lua"):
            shutil.copyfile(fixtures / name, share / name)
        for arguments in (("init", "-q"),
                          ("apply", str(ROOT / "wrt_core/patches/ssrplus-startup-lock.patch")),
                          ("apply", str(ROOT / "wrt_core/patches/ssrplus-dns-transaction.patch"))):
            result = subprocess.run(["git", "-C", str(package), *arguments],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        validation_patch = ROOT / "wrt_core/patches/ssrplus-updater-validation.patch"
        if validation_patch.exists():
            result = subprocess.run(["git", "-C", str(package), "apply", str(validation_patch)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.source = (share / "update.lua").read_text(encoding="utf-8")
        # Lua's standalone loader skips a shebang; LuaRuntime.execute receives
        # a chunk instead of a filename, so reproduce that loader behavior.
        if self.source.startswith("#!"):
            self.source = "\n" + self.source.split("\n", 1)[1]
        self.canonical = self.path("/etc/ssrplus/gfw_list.conf")
        self.old_source = b"# old complete canonical rules\n"
        self.canonical.parent.mkdir(parents=True)
        self.canonical.write_bytes(self.old_source)
        self.active = self.path("/tmp/dnsmasq.d/dnsmasq-ssrplus.conf")
        self.active.parent.mkdir(parents=True)
        self.old_active = b"server=/active.example/192.0.2.1\n"
        self.active.write_bytes(self.old_active)
        self.commands = []
        self.operations = []
        self.io_paths = []
        self.logs = []
        self.scratch = []
        self.reload_status = 0
        self.download_status = 0
        self.copy_failure = False
        self.rename_failure = False
        self.runtime_copy_failure = False
        self.ipset_available = False
        self.ipset_status = 0
        self.http_status = 200
        self.newer_source = None
        self.marker_write_failure = False
        self.backup_copy_failure = False
        self.lock_proof_status = 0
        self.outer_status = 0
        self.curl_version = "curl 8.16.0 (fixture) libcurl/8.16.0\n"
        self.downloads = {
            "https://fixture.invalid/gfw": b"||google.com\n||corp.example\n",
            "https://fixture.invalid/ip": b"192.0.2.0/24\n",
        }
        self.uci = {
            "gfwlist_url": "https://fixture.invalid/gfw",
            "chnroute_url": "https://fixture.invalid/ip",
            "apple_dns": "223.5.5.5",
            "apple_optimization": "0", "adblock": "0", "netflix_enable": "0",
        }

    def path(self, virtual):
        value = PurePosixPath(str(virtual))
        if not value.is_absolute() or ".." in value.parts:
            raise AssertionError(f"unexpected updater path: {virtual!r}")
        return self.filesystem.joinpath(*value.parts[1:])

    def io_path(self, virtual):
        self.io_paths.append(str(virtual))
        return self.path(virtual).as_posix()

    def remove(self, virtual):
        target = self.path(virtual)
        try:
            target.rmdir() if target.is_dir() else target.unlink()
            return True
        except OSError as error:
            return None, str(error), error.errno

    def shell_exec(self, command):
        self.commands.append(command)
        if command == "curl --version 8>&-":
            return self.curl_version
        if command == "mktemp -d /tmp/ssr-update.XXXXXX":
            virtual = f"/tmp/ssr-update.T{len(self.scratch) + 1:05d}"
            self.path(virtual).mkdir(parents=True)
            self.scratch.append(virtual)
            return virtual + "\n"
        if "md5sum " in command:
            match = re.search(r"md5sum\s+([^\s]+)", command)
            target = self.path(match[1].strip("'\""))
            return hashlib.md5(target.read_bytes()).hexdigest() if target.exists() else ""
        match = re.fullmatch(r"cat (\S+) \| wc -l", command)
        if match:
            return str(self.path(match[1]).read_bytes().count(b"\n")) + "\n"
        raise AssertionError(f"unexpected luci.sys.exec: {command}")

    def shell_call(self, command):
        self.commands.append(command)
        normalized = command.removesuffix(" 8>&-")
        if "readlink" in command and "flock -n -x 8" in command:
            return self.lock_proof_status
        if command.startswith("( umask 077;"):
            return self.outer_status
        if normalized == "/etc/init.d/shadowsocksr reload":
            if self.reload_status and self.newer_source is not None:
                self.canonical.write_bytes(self.newer_source)
            return self.reload_status
        if command == "command -v ipset >/dev/null 2>&1":
            return 0 if self.ipset_available else 1
        if command.startswith("/usr/share/shadowsocksr/chinaipset.sh "):
            return self.ipset_status
        tokens = shlex.split(command)
        if tokens and tokens[0] == "curl":
            destination = tokens[tokens.index("-o") + 1]
            url = tokens[tokens.index("--") + 1] if "--" in tokens else tokens[-1]
            target = self.path(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"partial download" if self.download_status else self.downloads[url])
            self.operations.append(("download", destination, url))
            fail_http = "--fail" in tokens or any(
                token.startswith("-") and not token.startswith("--") and "f" in token[1:]
                for token in tokens)
            return 22 if self.http_status >= 400 and fail_http else self.download_status
        if command.startswith(("cp -f ", "mv -f ")):
            for operation in normalized.split(" && "):
                words = shlex.split(operation)
                self.assertEqual(words[:2], [words[0], "-f"])
                action, source, destination = words[0], words[2], words[3]
                self.assertIn(action, ("cp", "mv"))
                self.assertNotIn("dnsmasq", destination,
                                 "updater copied raw rule input into active DNS files")
                self.operations.append((action, source, destination))
                src, dst = self.path(source), self.path(destination)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if action == "cp":
                    if ((self.copy_failure and ".previous." not in destination) or
                            (self.backup_copy_failure and ".previous." in destination) or
                            (self.runtime_copy_failure and
                                             destination.startswith("/var/etc/ssrplus/"))):
                        dst.write_bytes(b"partial copy")
                        return 1
                    shutil.copyfile(src, dst)
                elif self.rename_failure:
                    return 1
                else:
                    src.replace(dst)
            return 0
        raise AssertionError(f"unexpected luci.sys.call: {command}")

    def run_updater(self, argument="gfw_data", *, locked=True):
        lua = LuaRuntime(unpack_returned_tuples=True)
        globals_ = lua.globals()
        globals_.py_exec = self.shell_exec
        globals_.py_call = self.shell_call
        globals_.py_path = self.io_path
        globals_.py_remove = self.remove
        globals_.py_uci = lambda _config, _section, key, default: self.uci.get(key, default)
        globals_.py_log = lambda *values: self.logs.append(" ".join(str(value) for value in values))
        globals_.py_locked = locked

        def finish(code):
            raise ScriptExit(code)

        globals_.py_exit = finish
        lua.execute(r'''
luci = {sys={exec=function(command) return py_exec(command) end,
             call=function(command) return py_call(command) end}}
package.preload["luci.sys"] = function() return luci.sys end
package.preload["luci.model.uci"] = function()
    return {cursor=function()
        return {get_first=function(self, config, section, key, default)
            return py_uci(config, section, key, default)
        end}
    end}
end
local original_open, original_lines = io.open, io.lines
io.open = function(path, mode)
    -- Match OpenWrt's Unix byte semantics with Lua's Windows CRT as well.
    mode = mode or "r"
    if not mode:find("b") then mode = mode .. "b" end
    return original_open(py_path(path), mode)
end
io.lines = function(path) return original_lines(py_path(path)) end
os.remove = function(path) return py_remove(path) end
local original_getenv = os.getenv
os.getenv = function(name)
    if name == "SSRP_UPDATER_LOCKED" then return py_locked and "1" or nil end
    return original_getenv(name)
end
os.exit = function(code) py_exit(code or 0) end
print = function(...) py_log(...) end
''')
        globals_.arg = lua.table_from([] if argument is None else [argument])
        try:
            lua.execute(self.source)
        except ScriptExit as result:
            return result.code
        self.fail("updater finished without its explicit exit status")

    def assert_scratch_cleaned(self):
        self.assertTrue(self.scratch, "updater did not allocate a private scratch directory")
        for virtual in self.scratch:
            self.assertFalse(self.path(virtual).exists(), f"scratch leaked: {virtual}")
        self.assertEqual(list(self.canonical.parent.glob("*.ssr-update.*")), [])
        self.assertEqual(list(self.canonical.parent.glob("*.previous.*")), [])

    def test_new_rules_are_staged_then_atomically_replaced_and_reloaded(self):
        self.assertEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), GFW_SOURCE)
        mutations = [operation for operation in self.operations if operation[0] in ("cp", "mv")]
        canonical_writes = [operation for operation in mutations
                            if operation[0] == "mv" and operation[2] == "/etc/ssrplus/gfw_list.conf"]
        self.assertEqual(len(canonical_writes), 1)
        self.assertNotEqual(canonical_writes[0][1], "/etc/ssrplus/gfw_list.conf")
        self.assertEqual(len([command for command in self.commands
                              if command.startswith("/etc/init.d/shadowsocksr reload")]), 1)
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_partial_copy_failure_preserves_canonical_and_reports_failure(self):
        self.copy_failure = True
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertNotIn("/etc/init.d/shadowsocksr reload", self.commands)
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_rename_failure_preserves_canonical_and_reports_failure(self):
        self.rename_failure = True
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_reload_failure_is_reported_without_copying_to_active_dns(self):
        self.reload_status = 1
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertEqual(self.path("/etc/ssrplus/gfw_list.conf.pending").read_bytes(), GFW_SOURCE)
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_unchanged_source_retries_failed_activation(self):
        self.reload_status = 1
        self.assertNotEqual(self.run_updater(), 0)
        prior_mutations = len([op for op in self.operations if op[0] in ("cp", "mv")])
        self.reload_status = 0
        self.assertEqual(self.run_updater(), 0)
        self.assertEqual(len([command for command in self.commands
                              if command.startswith("/etc/init.d/shadowsocksr reload")]), 2,
                         "equal source hashes suppressed retry after failed activation")
        self.assertGreater(len([op for op in self.operations if op[0] in ("cp", "mv")]),
                           prior_mutations)
        self.assertEqual(self.canonical.read_bytes(), GFW_SOURCE)
        self.assertFalse(self.path("/etc/ssrplus/gfw_list.conf.pending").exists())
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_requested_download_failure_returns_nonzero_and_cleans_partial_data(self):
        self.download_status = 22
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertNotIn("/etc/init.d/shadowsocksr reload", self.commands)
        self.assert_scratch_cleaned()

    def test_noargs_download_failure_returns_nonzero(self):
        self.download_status = 22
        self.assertNotEqual(self.run_updater(argument=None), 0)
        self.assertEqual(len([op for op in self.operations if op[0] == "download"]), 2)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_each_invocation_uses_distinct_private_scratch(self):
        self.assertEqual(self.run_updater(), 0)
        self.assertEqual(self.run_updater(), 0)
        self.assertEqual(len(set(self.scratch)), 2)
        downloaded = [op[1] for op in self.operations if op[0] == "download"]
        self.assertEqual({str(PurePosixPath(path).parent) for path in downloaded},
                         set(self.scratch))
        for path in self.io_paths:
            if path.startswith("/tmp/ssr-update"):
                self.assertIn(str(PurePosixPath(path).parent), self.scratch,
                              "updater used a shared conversion scratch file")
        self.assert_scratch_cleaned()

    def test_ip_source_activation_failure_restores_old_source_and_retries_incoming_data(self):
        canonical = self.path("/etc/ssrplus/china_ssr.txt")
        runtime = self.path("/var/etc/ssrplus/china_ssr.txt")
        canonical.write_bytes(b"198.51.100.0/24\n")
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b"198.51.100.0/24\n")
        self.reload_status = 1
        self.assertNotEqual(self.run_updater("ip_data"), 0)
        self.assertEqual(canonical.read_bytes(), b"198.51.100.0/24\n")
        self.assertEqual(runtime.read_bytes(), b"198.51.100.0/24\n")
        self.reload_status = 0
        self.assertEqual(self.run_updater("ip_data"), 0)
        self.assertEqual(canonical.read_bytes(), b"192.0.2.0/24\n")
        self.assertEqual(runtime.read_bytes(), b"198.51.100.0/24\n",
                         "updater must leave all runtime mutations to the lifecycle")
        self.assert_scratch_cleaned()

    def test_no_ipset_ip_update_still_enters_checked_lifecycle_reload(self):
        self.ipset_available = False
        self.assertEqual(self.run_updater("ip_data"), 0)
        commands = [command for command in self.commands if "shadowsocksr reload" in command]
        self.assertEqual(len(commands), 1)
        self.assertFalse(any("chinaipset.sh" in command for command in self.commands))
        self.assert_scratch_cleaned()

    def assert_rejected_download(self, argument="gfw_data"):
        self.assertNotEqual(self.run_updater(argument), 0)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertFalse(any("shadowsocksr reload" in command for command in self.commands))
        self.assertEqual(self.active.read_bytes(), self.old_active)
        self.assert_scratch_cleaned()

    def test_http_404_is_rejected_before_conversion_or_canonical_replace(self):
        self.http_status = 404
        self.downloads[self.uci["gfwlist_url"]] = b"||google.com\n"
        self.assert_rejected_download()

    def test_http_200_html_is_rejected_even_when_it_contains_parseable_domains(self):
        self.downloads[self.uci["gfwlist_url"]] = b"<html><body>google.com outage.example</body></html>\n"
        self.assert_rejected_download()

    def test_empty_download_is_rejected(self):
        self.downloads[self.uci["gfwlist_url"]] = b""
        self.assert_rejected_download()

    def test_zero_parsed_rules_are_rejected(self):
        self.downloads[self.uci["gfwlist_url"]] = b"! google comment only\n@@||google.com\n"
        self.assert_rejected_download()

    def test_invalid_cidr_preserves_old_canonical_and_never_activates(self):
        canonical = self.path("/etc/ssrplus/china_ssr.txt")
        old = b"198.51.100.0/24\n"
        canonical.write_bytes(old)
        for value in (b"999.1.1.0/24\n", b"192.0.2.0/33\n", b"not-a-cidr\n"):
            with self.subTest(value=value):
                self.downloads[self.uci["chnroute_url"]] = value
                self.assertNotEqual(self.run_updater("ip_data"), 0)
                self.assertEqual(canonical.read_bytes(), old)
        self.assertFalse(any("shadowsocksr reload" in command for command in self.commands))
        self.assert_scratch_cleaned()

    def test_download_has_connection_total_and_size_bounds_and_closes_lock_fd(self):
        self.assertEqual(self.run_updater(), 0)
        command = next(command for command in self.commands if command.startswith("curl ") and " -o " in command)
        tokens = shlex.split(command)
        for option in ("--connect-timeout", "--max-time", "--max-filesize"):
            self.assertIn(option, tokens)
            self.assertGreater(int(tokens[tokens.index(option) + 1]), 0)
        self.assertTrue(command.endswith(" 8>&-"))
        reload = next(command for command in self.commands if "shadowsocksr reload" in command)
        self.assertTrue(reload.endswith(" 8>&-"))

    def test_url_ampersand_and_quotes_are_one_literal_curl_argument(self):
        url = "https://fixture.invalid/gfw?token=one&name=Bob's$(echo-surprise)"
        self.uci["gfwlist_url"] = url
        self.downloads[url] = b"||google.com\n||corp.example\n"
        self.assertEqual(self.run_updater(), 0)
        command = next(command for command in self.commands if command.startswith("curl ") and " -o " in command)
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
        self.assertIn(url, tokens)
        self.assertNotIn("&", tokens)
        self.assertEqual(self.canonical.read_bytes(), GFW_SOURCE)

    def test_rollback_does_not_overwrite_a_newer_external_canonical_write(self):
        self.reload_status = 1
        self.newer_source = b"server=/newer.example/192.0.2.3\n"
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), self.newer_source)
        self.assertTrue(self.path("/etc/ssrplus/gfw_list.conf.pending").exists())
        self.assert_scratch_cleaned()

    def test_backup_copy_failure_cannot_replace_canonical(self):
        self.backup_copy_failure = True
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertFalse(any("shadowsocksr reload" in command for command in self.commands))
        self.assert_scratch_cleaned()

    def test_successful_unchanged_source_still_retries_activation(self):
        self.canonical.write_bytes(GFW_SOURCE)
        self.reload_status = 23
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.canonical.read_bytes(), GFW_SOURCE)
        self.assertTrue(self.path("/etc/ssrplus/gfw_list.conf.pending").exists())
        self.reload_status = 0
        self.assertEqual(self.run_updater(), 0)
        self.assertEqual(len([command for command in self.commands
                              if "shadowsocksr reload" in command]), 2)
        self.assertFalse(self.path("/etc/ssrplus/gfw_list.conf.pending").exists())
        self.assert_scratch_cleaned()

    def test_every_rule_type_uses_lifecycle_activation(self):
        cases = (("apple_data", "apple_url", b"apple.example\n", "/etc/ssrplus/applechina.conf"),
                 ("ad_data", "adblock_url", b"address=/ads.example/0.0.0.0\n", "/etc/ssrplus/ad.conf"),
                 ("nfip_data", "nfip_url", b"198.51.100.0/24\n", "/etc/ssrplus/netflixip.list"))
        for argument, key, data, destination in cases:
            with self.subTest(argument=argument):
                self.uci[key] = "https://fixture.invalid/" + argument
                self.downloads[self.uci[key]] = data
                self.assertEqual(self.run_updater(argument), 0)
                self.assertTrue(self.path(destination).exists())
        self.assertEqual(len([command for command in self.commands
                              if "shadowsocksr reload" in command]), 3)
        self.assertFalse(any("chinaipset.sh" in command for command in self.commands))
        self.assert_scratch_cleaned()

    def test_forged_lock_marker_without_matching_locked_fd_is_rejected(self):
        self.lock_proof_status = 1
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.scratch, [])
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        self.assertEqual(self.operations, [])

    def test_outer_lock_failure_cannot_enter_transaction(self):
        self.outer_status = 75
        self.assertEqual(self.run_updater(locked=False), 75)
        self.assertEqual(self.scratch, [])
        self.assertEqual(self.operations, [])
        self.assertEqual(self.canonical.read_bytes(), self.old_source)
        envelope = self.commands[0]
        self.assertIn("exec 8>>/var/lock/ssrplus-update.lock", envelope)
        self.assertIn("flock -w 30 -x 8", envelope)

    def test_oversized_download_is_rejected_even_if_curl_reports_success(self):
        self.downloads[self.uci["gfwlist_url"]] = b"x" * (16777216 + 1)
        self.assert_rejected_download()

    def test_old_curl_without_unknown_length_size_cap_is_rejected_before_download(self):
        self.curl_version = "curl 8.3.0 (fixture) libcurl/8.3.0\n"
        self.assertNotEqual(self.run_updater(), 0)
        self.assertEqual(self.scratch, [])
        self.assertEqual(self.operations, [])
        self.assertEqual(self.canonical.read_bytes(), self.old_source)

    def test_lock_proof_accepts_var_lock_symlink_to_tmp_lock(self):
        self.assertEqual(self.run_updater(), 0)
        proof = next(command for command in self.commands if "readlink" in command)
        bash = shutil.which("bash") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else None)
        if not bash:
            self.skipTest("Bash is required to execute the lock identity check")
        # Only OS path resolution is substituted. Execute the actual proof's
        # comparisons with /var/lock -> /tmp/lock, matching OpenWrt's layout.
        preamble = r'''
readlink() {
    case "$*" in
        '-f /proc/self/fd/8'|'/proc/self/fd/8') echo /tmp/lock/ssrplus-update.lock ;;
        '-f /var/lock/ssrplus-update.lock') echo /tmp/lock/ssrplus-update.lock ;;
        *) return 1 ;;
    esac
}
flock() { [ "$*" = '-n -x 8' ]; }
'''
        result = subprocess.run([bash, "--noprofile", "--norc", "-c", preamble + proof],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def real_linux_lock_death(self, kill_owner, symlink_lock=False):
        self.assertEqual(self.run_updater(locked=False), 0)
        envelope = self.commands[0]
        lock = self.base / "updater.lock"
        if symlink_lock:
            real_directory = self.base / "tmp-lock"
            real_directory.mkdir()
            alias = self.base / "var-lock"
            alias.symlink_to(real_directory, target_is_directory=True)
            lock = alias / "updater.lock"
        source = self.source.replace("/var/lock/ssrplus-update.lock", lock.as_posix())
        header = source[:source.index("local update_root =")]
        worker = self.base / "lock-worker.py"
        worker.write_text("""import os, subprocess, time
from pathlib import Path
from lupa.lua51 import LuaRuntime
lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().py_call = lambda command: subprocess.call(command, shell=True, pass_fds=(8,))
lua.globals().py_exec = lambda command: subprocess.check_output(command, shell=True, pass_fds=(8,), text=True)
lua.execute('''package.preload["luci.sys"] = function()
    luci = {sys={call=function(command) return py_call(command) end,
                 exec=function(command) return py_exec(command) end}}; return luci.sys
end
package.preload["luci.model.uci"] = function() return {} end''')
lua.execute(""" + repr(header) + """)
Path(os.environ['TEST_UPDATER_PID']).write_text(str(os.getpid()))
while True: time.sleep(0.05)
""", encoding="utf-8", newline="\n")
        envelope = envelope.replace("/var/lock/ssrplus-update.lock", shlex.quote(str(lock)))
        envelope = envelope.replace("SSRP_UPDATER_LOCKED=1 /usr/bin/lua /usr/share/shadowsocksr/update.lua",
                                    'echo "$BASHPID" > "$TEST_OWNER_PID"; SSRP_UPDATER_LOCKED=1 ' +
                                    shlex.quote(sys.executable) + " " + shlex.quote(str(worker)))
        # Keep a distinct guardian even if Bash would otherwise exec its final
        # child; the source's worker must hold the lock independently of it.
        envelope = envelope.removesuffix(" )") + '; result=$?; exit "$result" )'
        owner_file, worker_file = self.base / "owner.pid", self.base / "worker.pid"
        env = os.environ.copy()
        env.update(TEST_OWNER_PID=str(owner_file), TEST_UPDATER_PID=str(worker_file))
        guardian = subprocess.Popen([shutil.which("bash"), "--noprofile", "--norc", "-c", envelope],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        owner = child = None
        try:
            deadline = time.monotonic() + 5
            while not worker_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(worker_file.exists(), "real Lua guard rejected the inherited lock")
            owner, child = int(owner_file.read_text()), int(worker_file.read_text())
            probe = ["flock", "-n", str(lock), "true"]
            self.assertNotEqual(subprocess.run(probe).returncode, 0)
            os.kill(owner if kill_owner else child, 9)
            if kill_owner:
                self.assertNotEqual(subprocess.run(probe).returncode, 0,
                                    "killing the owner unlocked an active Lua worker")
                os.kill(child, 9)
                child = None
            deadline = time.monotonic() + 5
            while subprocess.run(probe).returncode and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(subprocess.run(probe).returncode, 0,
                             "dead updater worker left its transaction lock held")
        finally:
            for pid in (child, owner):
                if pid:
                    try:
                        os.kill(pid, 9)
                    except ProcessLookupError:
                        pass
            if guardian.poll() is None:
                guardian.kill()
            guardian.communicate(timeout=5)

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock") and shutil.which("bash"),
                         "requires Linux /proc and kernel flock for owner/worker death semantics")
    def test_real_linux_killed_owner_does_not_unlock_active_lua_worker(self):
        self.real_linux_lock_death(kill_owner=True, symlink_lock=True)

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock") and shutil.which("bash"),
                         "requires Linux /proc and kernel flock for owner/worker death semantics")
    def test_real_linux_killed_lua_worker_releases_transaction_lock(self):
        self.real_linux_lock_death(kill_owner=False)


if __name__ == "__main__":
    unittest.main()
