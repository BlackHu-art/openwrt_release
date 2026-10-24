#!/usr/bin/env python3
"""Current fw876 v198.2 integration; 190-r12 tests are historical fixtures only.

The integration preserves upstream init and DNS. Explicit transport and update
patches adapt the configuration generator and the shared core update policy.
Real Lua and shell execute with UCI/process/filesystem boundaries substituted.
"""
import base64
import copy
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "maintenance/plugins/ssrplus/upstream-v198.2/luci-app-ssr-plus"
COMMIT = "45893d778767f3bdb2fcb6e873cf8f9a667d94d4"
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
MANIFEST = "root/usr/share/shadowsocksr/ssrplus-build.json"
TRANSLATION_LINK = "po/zh-cn"


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage_source(package):
    """Use the same link/mode materialization as the firmware feed loader."""
    loader = load_module("ssr_test_managed", "wrt_core/managed_plugins.py")
    loader.stage_package(ROOT / "wrt_core/managed", "luci-app-ssr-plus", package, package.parent)


@contextmanager
def windows_translation_link_boundary(package):
    """Windows byte tests only: model the one recorded link, never other paths.

    This does not prove OS symlink creation. The separate POSIX pipeline tests
    must stage real links and execute the production shell entry point.
    """
    alias = package / TRANSLATION_LINK
    is_symlink, readlink = Path.is_symlink, os.readlink
    with mock.patch.object(Path, "is_symlink", lambda path: path == alias or is_symlink(path)), \
            mock.patch.object(os, "readlink", lambda path, *args, **kwargs:
                              alias.read_text(encoding="utf-8") if Path(path) == alias
                              else readlink(path, *args, **kwargs)):
        yield


def source_snapshot(package):
    return {p.relative_to(package).as_posix():
            ("link", os.readlink(p)) if p.is_symlink() else
            ("file", p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in package.rglob("*") if p.is_file() or p.is_symlink()}


def prepare_source(package):
    if os.name == "nt":
        verifier = load_module("ssr_test_verifier", "wrt_core/ssrplus_verify.py")
        try:
            with windows_translation_link_boundary(package):
                verifier.prepare_source(ROOT / "wrt_core", package)
        except verifier.VerificationError as error:
            return subprocess.CompletedProcess([], 1, "", str(error))
        return subprocess.CompletedProcess([], 0, "", "")
    env = os.environ.copy()
    env.pop("MSYS_NO_PATHCONV", None)
    return subprocess.run([BASH, "--noprofile", "--norc", "-c",
        'BASE_PATH=$1; source "$BASE_PATH/modules/plugin_compat.sh"; fix_ssrplus_compat "$2"',
        "ssr-v198", (ROOT / "wrt_core").as_posix(), package.as_posix()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60)


def lua_to_python(value):
    if hasattr(value, "items"):
        result = {key: lua_to_python(item) for key, item in value.items()}
        if result and set(result) == set(range(1, len(result) + 1)):
            return [result[index] for index in range(1, len(result) + 1)]
        return result
    return value


@lru_cache(maxsize=1)
def prepared_source():
    """Exercise the production preparer once and retain its resulting bytes."""
    with tempfile.TemporaryDirectory(prefix="ssr-v198-prepared-") as temporary:
        package = Path(temporary) / "package"
        if os.name == "nt":
            shutil.copytree(ROOT / "wrt_core/managed/packages/luci-app-ssr-plus", package)
        else:
            stage_source(package)
        result = prepare_source(package)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return {path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*") if path.is_file()}


def generate_xray_config(node, runtime_args=None, *, global_options=None, xray_version="26.10.21"):
    """Execute the full prepared v198.2 generator, including fw private protocols."""
    source = prepared_source()["root/usr/share/shadowsocksr/gen_config.lua"]
    lua = LuaRuntime(unpack_returned_tuples=True)
    output = []
    def value(item):
        return lua.table_from(item, recursive=True) if isinstance(item, (dict, list)) else item
    sections = {"candidate": copy.deepcopy(node), "@socks5_proxy[0]": {},
                "@global_xray_fragment[0]": {"fragment": "0", "noise": "0"},
                "@xray_noise_packets[0]": {"enabled": "0"}}
    def get_all(config, section):
        if config != "shadowsocksr" or section not in sections:
            raise AssertionError("unexpected UCI request: " + config + ":" + section)
        return value(sections[section])
    def get_first(config, section, option, default=None):
        if (config, section) != ("shadowsocksr", "global"):
            raise AssertionError("unexpected UCI global request")
        return (global_options or {}).get(option, default)
    def execute(command):
        if command == 'type -t -p "xray" -p "/usr/libexec/xray" 2>/dev/null':
            return "/usr/bin/xray\n"
        if command == "xray version 2>&1":
            return "Xray " + xray_version + "\n"
        raise AssertionError("unexpected generator command: " + command)
    globals_ = lua.globals()
    globals_.py_get_all, globals_.py_get_first, globals_.py_exec = get_all, get_first, execute
    globals_.py_decode = lambda text: base64.b64decode(text + "=" * (-len(text) % 4)).decode()
    globals_.py_encode = lambda text: base64.b64encode(text.encode()).decode()
    globals_.py_parse = lambda text: value(json.loads(text))
    globals_.py_stringify = lambda item, *args: json.dumps(lua_to_python(item))
    globals_.py_output = lambda text: output.append(json.loads(text))
    globals_.arg = value(["candidate", *(runtime_args or ["tcp", "1234", "1080"])])
    lua.execute('''
luci = {sys={exec=function(command) return py_exec(command) end}}
nixio = {bin={b64decode=function(text) return py_decode(text) end,
              b64encode=function(text) return py_encode(text) end}}
package.preload["luci.sys"] = function() return luci.sys end
package.preload["luci.model.uci"] = function() return {cursor=function() return {
    get_all=function(self, ...) return py_get_all(...) end,
    get_first=function(self, ...) return py_get_first(...) end} end} end
package.preload["luci.jsonc"] = function() return {
    parse=function(text) return py_parse(text) end,
    stringify=function(...) return py_stringify(...) end} end
print = function(text) py_output(text) end
''')
    lua.execute(source.decode("utf-8").split("\n", 1)[1])
    if len(output) != 1:
        raise AssertionError("v198.2 generator must emit exactly one configuration")
    return output[0]


class SourceIntegration(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssr-v198-")
        self.addCleanup(self.temporary.cleanup)
        self.package = Path(self.temporary.name) / "package"
        if os.name == "nt":
            shutil.copytree(UPSTREAM, self.package)
        else:
            stage_source(self.package)

    def snapshot(self):
        return source_snapshot(self.package)

    def test_new_source_prepares_idempotently_preserving_upstream_runtime(self):
        result = prepare_source(self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((self.package / MANIFEST).read_text())
        self.assertEqual(manifest["source_commit"], COMMIT)
        self.assertEqual(manifest["repair_version"], "198-r2")
        self.assertEqual(set(manifest["patches"]), {"ssrplus-v198-integration.patch", "ssrplus-v198-xray-transports.patch", "ssrplus-v198-update-policy.patch"})
        changed = {source.relative_to(UPSTREAM).as_posix() for source in UPSTREAM.rglob("*")
                   if source.is_file() and source.relative_to(UPSTREAM).as_posix() != TRANSLATION_LINK
                   and (self.package / source.relative_to(UPSTREAM)).read_bytes() != source.read_bytes()}
        self.assertEqual(changed, {
            "Makefile", "root/usr/share/shadowsocksr/gen_config.lua",
            "root/usr/share/shadowsocksr/update_components.sh",
            "luasrc/controller/shadowsocksr.lua", "luasrc/view/shadowsocksr/component.htm",
            "po/zh_Hans/ssr-plus.po",
        })
        for source in (UPSTREAM / "root").rglob("*"):
            if source.is_file():
                relative = source.relative_to(UPSTREAM)
                # Explicit exceptions adapt the selected core and updater policy.
                # Init, DNS helpers and firewall retain upstream bytes exactly.
                if relative.as_posix() not in {
                    "root/usr/share/shadowsocksr/gen_config.lua",
                    "root/usr/share/shadowsocksr/update_components.sh",
                }:
                    self.assertEqual((self.package / relative).read_bytes(), source.read_bytes(), relative)
                target = "/" + relative.relative_to("root").as_posix()
                self.assertEqual(manifest["files"][target]["sha256"], hashlib.sha256((self.package / relative).read_bytes()).hexdigest())
        self.assertFalse((self.package / "root/usr/share/shadowsocksr/ssrp-runtime.sh").exists())
        before = self.snapshot()
        result = prepare_source(self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_generator_is_rejected_without_partial_changes(self):
        path = self.package / "root/usr/share/shadowsocksr/gen_config.lua"
        path.write_bytes(path.read_bytes() + b"\n-- unknown generator\n")
        before = self.snapshot()
        result = prepare_source(self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_source_file_is_rejected_before_integration(self):
        (self.package / "root/usr/share/shadowsocksr/ssrp-runtime.sh").write_text("old runtime\n")
        before = self.snapshot()
        result = prepare_source(self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_origin_override_cannot_mislabel_the_upstream_commit(self):
        (self.package / ".ssrplus-upstream-commit").write_text("a" * 40 + "\n")
        before = self.snapshot()
        result = prepare_source(self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_prepared_manifest_drift_is_rejected_without_repairing_it(self):
        result = prepare_source(self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self.package / MANIFEST
        data = json.loads(manifest.read_text())
        data["source_commit"] = "0" * 40
        manifest.write_text(json.dumps(data), encoding="utf-8")
        before = self.snapshot()
        result = prepare_source(self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_atomic_publish_preserves_source_modes_with_restrictive_tempfiles(self):
        # mkstemp grants 0600 on POSIX. A deliberately restrictive real tempfile
        # also makes loss of the source write bit observable on Windows.
        spec = importlib.util.spec_from_file_location("ssr_v198_verify", ROOT / "wrt_core/ssrplus_verify.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        recipe = self.package / "Makefile"
        previous_mode = stat.S_IMODE(recipe.stat().st_mode)
        original_mkstemp = tempfile.mkstemp
        def restricted(*args, **kwargs):
            descriptor, name = original_mkstemp(*args, **kwargs)
            os.chmod(name, 0o444)
            return descriptor, name
        with mock.patch.object(verifier.tempfile, "mkstemp", side_effect=restricted):
            if os.name == "nt":
                with windows_translation_link_boundary(self.package):
                    verifier.prepare_source(ROOT / "wrt_core", self.package)
            else:
                verifier.prepare_source(ROOT / "wrt_core", self.package)
        self.assertEqual(stat.S_IMODE(recipe.stat().st_mode), previous_mode)

    def test_actual_prepared_payload_validates_in_ipk_and_apk_containers(self):
        import test_ssrplus_artifacts as containers
        result = prepare_source(self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = self.package / MANIFEST
        manifest = json.loads(expected.read_text())
        def data_files(damage=False):
            files = []
            for target, attrs in manifest["files"].items():
                data = (self.package / "root" / target.lstrip("/")).read_bytes()
                if damage and target == "/usr/share/shadowsocksr/ipv6.sh":
                    data += b"\n# stale firewall helper\n"
                files.append((target.lstrip("/"), data, int(attrs["mode"], 8)))
            files.append((MANIFEST.removeprefix("root/"), expected.read_bytes(), 0o644))
            return files
        for kind in ("ipk", "apk"):
            for damage in (False, True):
                with self.subTest(container=kind, tampered=damage):
                    payload = gzip.compress(containers.tar_bytes(data_files(damage)))
                    artifact = self.package.parent / ("compiled." + kind)
                    if kind == "ipk":
                        control = b"Package: luci-app-ssr-plus\nVersion: 198-2\nArchitecture: all\n"
                        artifact.write_bytes(containers.ar_bytes([
                            ("debian-binary", b"2.0\n"),
                            ("control.tar.gz", gzip.compress(containers.tar_bytes([("control", control, 0o644)]))),
                            ("data.tar.gz", payload)]))
                    else:
                        info = b"pkgname = luci-app-ssr-plus\npkgver = 198-r2\narch = all\n"
                        artifact.write_bytes(gzip.compress(containers.tar_bytes([(".PKGINFO", info, 0o644)])) + payload)
                    result = subprocess.run([os.sys.executable, str(ROOT / "wrt_core/ssrplus_verify.py"),
                        "package", "--manifest", str(expected), "--package", str(artifact)],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, int(damage), result.stdout + result.stderr)
                    if damage:
                        self.assertIn("ipv6.sh", result.stderr)


class SourceLinkContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssr-link-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.package = Path(self.temporary.name) / "package"
        shutil.copytree(ROOT / "wrt_core/managed/packages/luci-app-ssr-plus", self.package)
        self.verifier = load_module("ssr_link_verifier", "wrt_core/ssrplus_verify.py")

    def test_production_rejects_link_text_instead_of_a_real_translation_symlink(self):
        before = source_snapshot(self.package)
        with self.assertRaisesRegex(self.verifier.VerificationError, "symlink"):
            self.verifier.prepare_source(ROOT / "wrt_core", self.package)
        self.assertEqual(source_snapshot(self.package), before)

    def test_recorded_link_boundary_accepts_the_exact_upstream_alias_idempotently(self):
        # Deliberately controlled OS boundary, runnable without Windows privileges.
        # This regression was red with the original blanket symlink rejection.
        with windows_translation_link_boundary(self.package):
            self.verifier.prepare_source(ROOT / "wrt_core", self.package)
            before = source_snapshot(self.package)
            self.verifier.prepare_source(ROOT / "wrt_core", self.package)
            self.assertEqual(source_snapshot(self.package), before)
        self.assertEqual((self.package / TRANSLATION_LINK).read_bytes(), b"zh_Hans")

    def test_changed_link_targets_fail_without_partial_publication(self):
        alias = self.package / TRANSLATION_LINK
        for target in ("../po/zh_Hans", "../../outside", "missing", "/tmp/outside", "zh_Hans/ssr-plus.po"):
            with self.subTest(target=target):
                alias.write_text(target, encoding="utf-8")
                before = source_snapshot(self.package)
                with windows_translation_link_boundary(self.package):
                    with self.assertRaises(self.verifier.VerificationError):
                        self.verifier.prepare_source(ROOT / "wrt_core", self.package)
                self.assertEqual(source_snapshot(self.package), before)

    def test_missing_translation_target_fails_without_partial_publication(self):
        shutil.rmtree(self.package / "po/zh_Hans")
        before = source_snapshot(self.package)
        with windows_translation_link_boundary(self.package):
            with self.assertRaises(self.verifier.VerificationError):
                self.verifier.prepare_source(ROOT / "wrt_core", self.package)
        self.assertEqual(source_snapshot(self.package), before)


@unittest.skipIf(os.name == "nt", "real managed symlink -> shell integration requires POSIX; Linux CI must run it")
class ProductionFeedIntegration(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssr-real-feed-")
        self.addCleanup(self.temporary.cleanup)
        self.package = Path(self.temporary.name) / "package"
        stage_source(self.package)

    def test_real_stage_then_shell_prepare_preserves_translation_link_and_is_repeatable(self):
        alias = self.package / TRANSLATION_LINK
        self.assertTrue(alias.is_symlink())
        self.assertEqual(os.readlink(alias), "zh_Hans")
        before = source_snapshot(self.package)
        result = prepare_source(self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(os.readlink(alias), "zh_Hans")
        self.assertEqual((alias / "ssr-plus.po").read_bytes(), (self.package / "po/zh_Hans/ssr-plus.po").read_bytes())
        after = source_snapshot(self.package)
        expected_changes = {"Makefile", "root/usr/share/shadowsocksr/gen_config.lua",
            "root/usr/share/shadowsocksr/update_components.sh", "luasrc/controller/shadowsocksr.lua",
            "luasrc/view/shadowsocksr/component.htm", "po/zh_Hans/ssr-plus.po"}
        self.assertEqual({name for name in before if before[name][:2] != after[name][:2]}, expected_changes)
        expected_modes = {"root/etc/hotplug.d/iface/99-ssrplus-pppoe",
            *("root/usr/share/shadowsocksr/" + name for name in (
                "clash_yaml.lua", "gen_anytls_server.lua", "gen_naive_server.lua",
                "gen_snell_server.lua", "gen_ssr_server.lua", "gen_tuic_server.lua",
                "update_components.sh"))}
        self.assertEqual({name for name in before
                          if before[name][0] == "file" and before[name][2] != after[name][2]}, expected_modes)
        for name in expected_modes:
            self.assertEqual((before[name][2], after[name][2]), (0o644, 0o755), name)
        result = prepare_source(self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(source_snapshot(self.package), after)

    def test_candidate_cli_uses_real_managed_materialization(self):
        candidate = self.package.parent / "candidate"
        result = subprocess.run([os.sys.executable, str(ROOT / "tests/prepare_ssrplus_candidate.py"),
                                 "--output", str(candidate)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((candidate / TRANSLATION_LINK).is_symlink())
        self.assertEqual(os.readlink(candidate / TRANSLATION_LINK), "zh_Hans")
        manifest = json.loads((candidate / MANIFEST).read_text())
        self.assertEqual(manifest["source_commit"], COMMIT)

    def test_bad_real_link_shapes_are_rejected_before_any_source_changes(self):
        for mutation in ("text", "directory", "missing", "retarget", "outside", "dangling", "target_symlink", "extra"):
            with self.subTest(mutation=mutation):
                stage_source(self.package)
                alias = self.package / TRANSLATION_LINK
                if mutation == "extra":
                    (self.package / "po/extra").symlink_to("zh_Hans", target_is_directory=True)
                elif mutation == "target_symlink":
                    target = self.package / "po/zh_Hans"
                    target.rename(self.package / "po/real-translation")
                    target.symlink_to("real-translation", target_is_directory=True)
                else:
                    alias.unlink()
                    if mutation == "text":
                        alias.write_bytes(b"zh_Hans")
                    elif mutation == "directory":
                        alias.mkdir()
                    elif mutation != "missing":
                        target = {"retarget": "templates", "outside": "../../outside", "dangling": "absent"}[mutation]
                        alias.symlink_to(target, target_is_directory=True)
                before = source_snapshot(self.package)
                result = prepare_source(self.package)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(source_snapshot(self.package), before)


class UpstreamRuntime(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssr-v198-runtime-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        source = prepared_source()["root/etc/init.d/shadowsocksr"].decode("utf-8")
        # Relocate only fixed host filesystem paths; branch logic remains real.
        source = source.replace("mkdir -p /var/run /var/lock /var/log", 'mkdir -p "$TEST_ROOT/run"')
        source = source.replace("/etc/init.d/dnsmasq", '"$TEST_ROOT/dnsmasq"')
        source = source.replace("/usr/bin/ssr-rules", '"$TEST_ROOT/ssr-rules"')
        (self.base / "init").write_text(source, encoding="utf-8", newline="\n")
        for command in ("dnsmasq", "ssr-rules"):
            path = self.base / command
            path.write_text('#!/bin/sh\necho "' + command + ':$*" >> "$TEST_ROOT/events"\n', newline="\n")
            path.chmod(0o755)
        self.env = os.environ.copy()
        self.env.pop("MSYS_NO_PATHCONV", None)
        self.env["TEST_ROOT"] = self.base.as_posix()
        self.preamble = r'''
source "$TEST_ROOT/init"
TMP_PATH="$TEST_ROOT/runtime" TMP_BIN_PATH="$TEST_ROOT/bin"
DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d" TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
CLASH_CONFIG_DIR="$TEST_ROOT/clash"
USE_TABLES=nftables GLOBAL_SERVER=node
MODE=1 IPV6=0 KIND=v2ray FILTER=1
uci_get_by_type() {
    case "$2" in
        pdnsd_enable) echo "$MODE" ;; ipv6_support) echo "$IPV6" ;;
        global_server) echo node ;; apple_optimization) echo 0 ;;
        *) printf '%s\n' "$3" ;;
    esac
}
uci_get_by_name() { echo "$KIND"; }
uci() { case "$*" in *filter_aaaa*) echo "$FILTER";; *) :;; esac; }
normalize_run_mode() { echo gfw; }
echolog() { :; }
first_type() { echo "$TEST_ROOT/$1"; }
is_finded() { [ "$1" = dns2tcp ]; }
ln_start_bin() { printf '%s\n' "$*" >> "$TEST_ROOT/launched"; }
add_dns_into_ipset() { :; }
'''

    def shell(self, body):
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", self.preamble + body],
            env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)

    def test_start_rejects_ipv6_on_iptables_before_starting_clients(self):
        result = self.shell('''
set_lock() { :; }; unset_lock() { :; }
check_run_environment() { USE_TABLES=iptables; }
Start_Run() { echo incorrectly-started; }
IPV6=1
start
''')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("incorrectly-started", result.stdout)

    def test_rule_failure_unsets_lock_and_stops_before_dns(self):
        result = self.shell('''
set_lock() { echo lock; }; unset_lock() { echo unlock; }
check_run_environment() { :; }; normalize_xray_protocol_nodes() { :; }
load_config() { return 0; }; Start_Run() { echo client; }
start_http_proxy() { :; }; start_xhttp_addr() { :; }
start_rules() { echo rules; return 1; }; stop() { echo stop; }
start_dns() { echo incorrectly-dns; }
start
''')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["lock", "client", "rules", "unlock", "stop"])

    def test_successful_start_uses_upstream_rule_dns_snapshot_order(self):
        result = self.shell('''
set_lock() { :; }; unset_lock() { :; }; check_run_environment() { :; }
normalize_xray_protocol_nodes() { :; }; load_config() { return 0; }
Start_Run() { echo client >> "$TEST_ROOT/events"; }
start_http_proxy() { :; }; start_xhttp_addr() { :; }
start_rules() { echo rules >> "$TEST_ROOT/events"; }
set_ipv6_dns_filter() { :; }; start_dns() { echo dns >> "$TEST_ROOT/events"; }
add_cron() { :; }; start_switch() { :; }; check_server() { :; }
start_server() { :; }; start_monitor() { :; }; clean_log() { :; }
start
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.base / "events").read_text().splitlines(),
                         ["client", "rules", "dns", "ssr-rules:-P", "dnsmasq:restart"])
        self.assertIn("dnsmasq-ssrplus.d", (self.base / "dnsmasq.d/dnsmasq-ssrplus.conf").read_text())

    def test_dns2tcp_aaaa_feature_probe_changes_real_launch_arguments(self):
        tool = self.base / "dns2tcp"
        tool.write_text('#!/bin/sh\necho "usage: dns2tcp -A filter"\n', newline="\n")
        tool.chmod(0o755)
        result = self.shell('start_dns; echo "mode=$pdnsd_enable_flag"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("mode=1", result.stdout)
        self.assertIn("-L 127.0.0.1#5335 -R 8.8.4.4#53 -A", (self.base / "launched").read_text())
        (self.base / "launched").unlink()
        tool.write_text('#!/bin/sh\necho "usage: dns2tcp"\n', newline="\n")
        result = self.shell("start_dns")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(" -A", (self.base / "launched").read_text())

    def test_builtin_dns_launches_no_external_resolver_for_xray(self):
        result = self.shell('MODE=7; start_dns; echo "mode=$pdnsd_enable_flag"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("mode=7", result.stdout)
        self.assertFalse((self.base / "launched").exists())

    def test_ipv6_listen_and_aaaa_rules_are_the_upstream_nft_policy(self):
        result = self.shell('IPV6=1; ipt2socks_listen_args; get_filter_aaaa; USE_TABLES=iptables; ipt2socks_listen_args; get_filter_aaaa')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["-b 0.0.0.0 -B ::", "0", "-b 0.0.0.0 -4", "1"])

    def test_ipv6_dns_filter_start_and_stop_restore_previous_filter(self):
        result = self.shell(r'''
IPV6=1
echo 1 > "$TEST_ROOT/filter"
uci() {
    [ "$1" != -q ] || shift
    local operation=$1 key=$2 file="$TEST_ROOT/filter"
    case "$key" in *_ssrp_filter_aaaa*) file="$TEST_ROOT/saved" ;; esac
    case "$operation" in
        get) [ -f "$file" ] && cat "$file" ;;
        set) printf '%s\n' "${key#*=}" > "$file" ;;
        delete) rm "$file" ;;
        commit) : ;;
        *) return 1 ;;
    esac
}
set_ipv6_dns_filter start
cat "$TEST_ROOT/filter"
set_ipv6_dns_filter stop
cat "$TEST_ROOT/filter"
[ ! -e "$TEST_ROOT/saved" ]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "1"])

    def test_missing_mosdns_falls_back_only_when_dns2tcp_is_present(self):
        result = self.shell('MODE=4; start_dns; echo "mode=$pdnsd_enable_flag"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("mode=1", result.stdout)
        self.assertIn("dns2tcp -L", (self.base / "launched").read_text())
        (self.base / "launched").unlink()
        result = self.shell('MODE=4; is_finded() { return 1; }; start_dns')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.base / "launched").exists())


@unittest.skipUnless(LuaRuntime, "lupa.lua51 is required to execute the real v198.2 generator")
class CurrentGenerator(unittest.TestCase):
    def test_vless_tcp_and_udp_listener_ports_preserve_existing_node_settings(self):
        node = {"type": "v2ray", "v2ray_protocol": "vless", "server": "fixture.invalid",
                "server_port": "443", "vmess_id": "12345678-1234-1234-1234-123456789abc",
                "transport": "raw", "tls": "1", "tls_host": "fixture.invalid"}
        for proto in ("tcp", "udp"):
            with self.subTest(proto=proto):
                config = generate_xray_config(node, [proto, "2345", "0"])
                self.assertEqual(config["inbounds"][0]["port"], 2345)
                self.assertEqual(config["inbounds"][0]["settings"]["network"], proto)
                self.assertEqual(config["outbounds"][0]["protocol"], "vless")
                self.assertEqual(config["outbounds"][0]["streamSettings"]["method"], "raw")

    def test_anytls_legacy_type_is_migrated_by_real_generator(self):
        node = {"type": "anytls", "server": "fixture.invalid", "server_port": "443", "password": "secret"}
        config = generate_xray_config(node)
        self.assertEqual(config["outbounds"][0]["protocol"], "anytls")
        self.assertEqual(config["outbounds"][0]["streamSettings"]["security"], "tls")

    def test_ipv6_option_changes_real_transparent_listener_address(self):
        node = {"type": "ss-rust", "server": "fixture.invalid", "server_port": "443", "password": "secret", "encrypt_method_ss": "aes-128-gcm"}
        for option, expected in (("0", "0.0.0.0"), ("1", "::")):
            with self.subTest(ipv6=option):
                config = generate_xray_config(node, global_options={"ipv6_support": option})
                self.assertEqual(config["local_address"], expected)


@unittest.skipUnless(LuaRuntime, "lupa.lua51 is required to execute the real v198.2 subscription")
class CurrentSubscription(unittest.TestCase):
    def test_real_subscriber_parses_ss_vless_and_ssr(self):
        from ssrplus_v198_harness import new_subscription_node
        b64 = lambda value: base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")
        cases = [
            ("ss://" + b64("aes-128-gcm:secret") + "@ss.example:443#SS", "ss-rust"),
            ("vless://12345678-1234-1234-1234-123456789abc@vless.example:443?security=tls&type=ws&host=vless.example&path=%2Fws#VLESS", "v2ray"),
            ("ssr://" + b64("ssr.example:443:auth_sha1_v4:aes-128-cfb:plain:" + b64("secret") + "/?remarks=" + b64("SSR")), "ssr"),
        ]
        for uri, expected in cases:
            with self.subTest(protocol=expected):
                node = new_subscription_node(uri)
                self.assertEqual(node["type"], expected)
                self.assertEqual(str(node["server_port"]), "443")
                if expected == "v2ray":
                    generated = generate_xray_config(node)
                    self.assertEqual(generated["outbounds"][0]["protocol"], "vless")
                    self.assertEqual(generated["outbounds"][0]["streamSettings"]["wsSettings"]["path"], "/ws")

    def test_unchanged_subscription_keeps_selected_section_and_manual_nodes(self):
        from ssrplus_v198_harness import SubscriptionHarness
        harness = SubscriptionHarness()
        uri = "ss://YWVzLTEyOC1nY206c2VjcmV0@ss.example:443#SS"
        first = harness.run([uri])
        self.assertEqual(len(first), 1, harness.logs)
        sid = next(iter(first))
        harness.sections["global"].update(global_server=sid, udp_relay_server=sid)
        harness.sections["socks"] = {".type": "socks5_proxy", "server": sid}
        second = harness.run([uri])
        self.assertEqual(set(second), {sid})
        self.assertEqual(harness.persisted["global"]["global_server"], sid)
        self.assertEqual(harness.persisted["global"]["udp_relay_server"], sid)
        self.assertEqual(harness.persisted["socks"]["server"], sid)
        self.assertEqual(harness.persisted["manual"]["server"], "manual.invalid")


if __name__ == "__main__":
    unittest.main()
