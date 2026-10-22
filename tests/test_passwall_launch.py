#!/usr/bin/env python3
"""Exercise the real Passwall launch functions with isolated OS boundaries.

Source comes from the checked maintenance snapshots. Only the selected shell
functions are loaded, so app.sh's top-level router initialization never runs.
The production patch helper prepares private copies; Lua, UCI and core/process
boundaries are replaced, while config redirection, cleanup and control flow run
unchanged. PASSWALL_LAUNCH_UNPATCHED=1 reproduces the upstream failure.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHELL = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
CASES = (
    ("passwall", "run_singbox", False),
    ("passwall", "run_singbox", True),
    ("passwall2", "run_singbox", False),
    ("passwall2", "run_socks", False),
    ("passwall2", "run_socks", True),
)


def function_source(source, name):
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", source, re.M | re.S)
    if match is None:
        raise AssertionError("upstream function not found: " + name)
    return match.group(0) + "\n"


@unittest.skipUnless(SHELL and Path(SHELL).exists(), "Bash is required")
class PasswallLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = tempfile.TemporaryDirectory(prefix="passwall-launch-source-")
        cls.addClassCleanup(cls.prepared.cleanup)
        cls.functions = {}
        for plugin in ("passwall", "passwall2"):
            source = ROOT / "maintenance/plugins" / plugin / ("luci-app-" + plugin)
            package = Path(cls.prepared.name) / plugin
            manifest = json.loads((ROOT / "maintenance/plugins/manifests" /
                                   (plugin + ".json")).read_text(encoding="utf-8"))
            hashes = {row["path"]: row["sha256"] for row in manifest["files"]}
            for name in ("app.sh", "utils.sh"):
                relative = "root/usr/share/" + plugin + "/" + name
                data = (source / relative).read_bytes()
                if hashlib.sha256(data).hexdigest() != hashes[relative]:
                    raise AssertionError("maintenance snapshot changed: " + relative)
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            subprocess.run(["git", "init", "-q", str(package)], check=True,
                           capture_output=True, timeout=20)
            subprocess.run(["git", "-C", str(package), "config", "core.autocrlf", "false"],
                           check=True, capture_output=True, timeout=20)
            app = package / ("root/usr/share/" + plugin + "/app.sh")
            if not os.environ.get("PASSWALL_LAUNCH_UNPATCHED"):
                environment = os.environ.copy()
                environment.update(REPO_ROOT=ROOT.as_posix(), PACKAGE=package.as_posix(),
                                   PLUGIN=plugin, MSYS_NO_PATHCONV="1")
                helper = '''BASE_PATH="$REPO_ROOT/wrt_core"
source "$BASE_PATH/modules/plugin_compat.sh"
apply_plugin_compat_patches "$PACKAGE" "$PLUGIN" "$PLUGIN-singbox-launch.patch"
'''
                for attempt in range(2):
                    before = app.read_bytes()
                    result = subprocess.run([SHELL, "--noprofile", "--norc", "-c", helper],
                                            env=environment, capture_output=True, text=True, timeout=20)
                    if result.returncode:
                        raise AssertionError(result.stdout + result.stderr)
                    if attempt and app.read_bytes() != before:
                        raise AssertionError("repeated helper changed " + plugin)
            subprocess.run([SHELL, "-n", str(app)], check=True, capture_output=True, timeout=20)
            app_code = app.read_text(encoding="utf-8")
            utils = (app.parent / "utils.sh").read_text(encoding="utf-8")
            for function in ("run_singbox", "run_socks"):
                if plugin == "passwall" and function == "run_socks":
                    continue
                cls.functions[plugin, function] = (function_source(utils, "eval_set_val") +
                                                   function_source(app_code, function))

    def run_case(self, plugin, function, no_run, lua_status):
        temporary = tempfile.TemporaryDirectory(prefix="passwall-launch-run-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        (base / "plugin.log").write_text("existing log entry\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(TEST_ROOT=base.as_posix(), LUA_STATUS=str(lua_status),
                           TEST_FUNCTION=function, TEST_NO_RUN="1" if no_run else "",
                           MSYS_NO_PATHCONV="1")
        if os.name == "nt":
            environment["TEST_ROOT"] = subprocess.check_output(
                [SHELL, "--noprofile", "--norc", "-c", 'cygpath -u "$1"', "path", str(base)],
                env=environment, text=True, timeout=20).strip()
        boundaries = r'''
TMP_PATH="$TEST_ROOT"
LOG_FILE="$TEST_ROOT/plugin.log"
UTIL_SINGBOX="test-generator.lua"
SINGBOX_BIN=fake_core
LOCAL_DNS=127.0.0.1
DIRECT_DNS_PROTO=udp
DIRECT_DNS_SERVER=127.0.0.1
DIRECT_DNS_PORT=53
DIRECT_DNS_QUERY_STRATEGY=UseIP
json_init(){ :; }
json_add_string(){ :; }
json_add_null(){ :; }
json_dump(){ printf '{}'; }
config_n_get(){
    case "$2" in
        type) printf 'sing-box';;
        protocol) printf 'trojan';;
        address) printf '198.51.100.10';;
        port) printf '443';;
        remarks) printf 'fixture';;
        *) printf '%s' "$3";;
    esac
}
check_host(){ :; }
echolog(){ printf '%s\n' "$*" >> "$LOG_FILE"; }
log(){ printf '%s\n' "$*" >> "$LOG_FILE"; }
lua(){
    [ "$#" = 3 ] && [ "$1" = "$UTIL_SINGBOX" ] && [ "$2" = gen_config ] || {
        forbidden unexpected-lua; return 97;
    }
    printf 'lua\n' >> "$TEST_ROOT/events"
    if [ "$LUA_STATUS" != 0 ]; then
        printf '{"partial":'
        printf 'TLS certificate pin requires a supported sing-box version.\n' >&2
        return "$LUA_STATUS"
    fi
    printf '{"outbounds":[{"type":"trojan"}]}\n'
}
fake_core(){
    case "$1" in
        version) printf 'Tags: with_quic\n';;
        check)
            [ "$#" = 3 ] && [ "$2" = -c ] && [ "$3" = "$TEST_ROOT/config.json" ] || {
                forbidden unexpected-core-check; return 97;
            }
            printf 'check\n' >> "$TEST_ROOT/events";;
        *) forbidden unexpected-core-call; return 97;;
    esac
}
ln_run(){
    [ "$1" = fake_core ] && [ "$2" = sing-box ] && [ "$4" = run ] &&
        [ "$5" = -c ] && [ "$6" = "$TEST_ROOT/config.json" ] || {
            forbidden unexpected-core-start; return 97;
        }
    printf 'start\n' >> "$TEST_ROOT/events"
}
forbidden(){ printf '%s\n' "$*" >> "$TEST_ROOT/forbidden"; return 97; }
uci(){ forbidden uci; }
procd_open_instance(){ forbidden procd; }
procd_set_param(){ forbidden procd; }
procd_close_instance(){ forbidden procd; }
busybox(){ forbidden busybox; }
kill(){ forbidden kill; }
killall(){ forbidden killall; }
xargs(){ forbidden xargs; }
nft(){ forbidden nft; }
iptables(){ forbidden iptables; }
ip(){ forbidden ip; }
'''
        invoke = r'''
"$TEST_FUNCTION" node=fixture type=sing-box bind=127.0.0.1 socks_port=1080 \
    config_file="$TEST_ROOT/config.json" log_file=/dev/null \
    run_in_global=1 no_run="$TEST_NO_RUN"
printf '%s\n' "$?" > "$TEST_ROOT/status"
'''
        runner = base / "runner.sh"
        runner.write_text(boundaries + self.functions[plugin, function] + invoke,
                          encoding="utf-8", newline="\n")
        result = subprocess.run([SHELL, "--noprofile", "--norc", str(runner)],
                                env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((base / "forbidden").exists(), "unexpected OS operation")
        return base, result

    def test_lua_failure_never_checks_or_starts_core(self):
        for plugin, function, no_run in CASES:
            with self.subTest(plugin=plugin, function=function, no_run=no_run):
                base, _ = self.run_case(plugin, function, no_run, 23)
                self.assertEqual((base / "events").read_text(), "lua\n")
                self.assertNotEqual((base / "status").read_text().strip(), "0")

    def test_lua_failure_removes_partial_config(self):
        for plugin, function, no_run in CASES:
            with self.subTest(plugin=plugin, function=function, no_run=no_run):
                base, _ = self.run_case(plugin, function, no_run, 23)
                self.assertFalse((base / "config.json").exists())

    def test_lua_failure_appends_actionable_error_to_plugin_log(self):
        for plugin, function, no_run in CASES:
            with self.subTest(plugin=plugin, function=function, no_run=no_run):
                base, result = self.run_case(plugin, function, no_run, 23)
                log = base / "plugin.log"
                logged = log.read_text()
                self.assertTrue(logged.startswith("existing log entry\n"))
                self.assertIn("TLS certificate pin requires", logged)
                self.assertNotIn("TLS certificate pin requires", result.stderr)

    def test_success_preserves_config_and_requested_launch_mode(self):
        for plugin, function, no_run in CASES:
            with self.subTest(plugin=plugin, function=function, no_run=no_run):
                base, result = self.run_case(plugin, function, no_run, 0)
                self.assertEqual(json.loads((base / "config.json").read_text()),
                                 {"outbounds": [{"type": "trojan"}]})
                events = "lua\n"
                if not no_run:
                    if function == "run_singbox":
                        events += "check\n"
                    events += "start\n"
                self.assertEqual((base / "events").read_text(), events)
                self.assertEqual(result.stderr, "")
                # Upstream PW2 run_socks ends in a false direct-node-list test
                # even on success. This change preserves that unrelated quirk.
                if function == "run_singbox":
                    self.assertEqual((base / "status").read_text().strip(), "0")


if __name__ == "__main__":
    unittest.main()
