#!/usr/bin/env python3
"""Run OpenClash's shell/Ruby generation and startup gate with real Mihomo.

Raw upstream files come from the pinned package and remain untouched. Windows
Ruby sees inconsistent native temporary-file bytes on this host, so Ruby's YAML
file/cache I/O boundary uses inline content; the actual generation code runs.
Mihomo receives the generated configuration using its official base64 flag.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from openclash_fixture import make_package

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("BASH") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
RUBY = os.environ.get("RUBY") or shutil.which("ruby")
OLD_CORE = os.environ.get("MIHOMO_OLD_TEST_BIN")
NEW_CORE = os.environ.get("MIHOMO_NEW_TEST_BIN")
if os.environ.get("OPENCLASH_REQUIRE_MIHOMO") == "1" and (not OLD_CORE or not NEW_CORE):
    raise RuntimeError("Mihomo old/new binaries are required by OPENCLASH_REQUIRE_MIHOMO")


def shell_function(source, name):
    match = re.search(r"^" + re.escape(name) + r"\(\)\s*\n\{.*?^\}[^\n]*", source, re.M | re.S)
    return match.group(0) if match else ""


class OpenClashTunStack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RUBY:
            raise RuntimeError("Ruby is required to execute OpenClash's actual YAML generator")
        cls.temporary = tempfile.TemporaryDirectory(prefix="openclash-tun-stack-")
        cls.package = Path(cls.temporary.name) / "package"
        make_package(cls.package)
        for relative, expected in {
            "root/usr/share/openclash/yml_change.sh": "abbce9f50b25f5459611f7d32940a018caf40ecd",
            "luasrc/model/cbi/openclash/settings.lua": "047b497980b53b159f95a3f38d41106097ee0f16",
        }.items():
            data = (cls.package / relative).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != expected:
                raise AssertionError("unreviewed upstream TUN input: " + relative)
        subprocess.run(["git", "init", "-q", str(cls.package)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(cls.package), "config", "core.autocrlf", "false"], check=True, capture_output=True)
        command = 'BASE_PATH="$1/wrt_core"; source "$BASE_PATH/modules/plugin_compat.sh"; fix_openclash_compat "$2"'
        fixed = subprocess.run([BASH, "-c", command, "test", ROOT.as_posix(), cls.package.as_posix()], text=True, encoding="utf-8", capture_output=True)
        if fixed.returncode:
            raise AssertionError("production OpenClash fixer failed:\n" + fixed.stdout + fixed.stderr)
        cls.generator = (cls.package / "root/usr/share/openclash/yml_change.sh").read_text(encoding="utf-8")
        cls.init = (cls.package / "root/etc/init.d/openclash").read_text(encoding="utf-8")
        cls.library = (cls.package / "root/usr/share/openclash/YAML.rb").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def generate(self, ipv4_stack="", ipv6_stack="", ipv4_tun="1", ipv6_mode="0"):
        with tempfile.TemporaryDirectory(prefix="oc-stack-gen-") as temporary:
            directory = Path(temporary)
            capture = directory / "ruby-argv"
            # UCI and filesystem calls are the OpenWrt platform boundaries.
            # Keep all production shell selection and the entire Ruby generator.
            source = re.sub(r"^\. /[^\n]+\n", "", self.generator, flags=re.M)
            source = source.replace("/tmp/", directory.as_posix() + "/tmp/").replace("/etc/openclash/", directory.as_posix() + "/etc/openclash/")
            (directory / "tmp").mkdir()
            prefix = r'''
uci_get_config() { case "$1" in enable_redirect_dns) echo 1;; *) echo 0;; esac; }
uci() { return 1; }
config_load() { :; }
config_foreach() { :; }
LOG_TIP() { :; }
LOG_ERROR() { :; }
ruby() { printf '%s\000' "$@" > "$RUBY_CAPTURE"; }
'''
            args = ["redir-host", "", "9090", "7892", (directory / "runtime.yaml").as_posix(), "0", "7890", "7891", "silent", "rule", ipv4_tun, ipv4_stack,
                    "7874", "7893", "7895", "0", "0", "0", "0", "0", "0", "0", "0", "Meta", "0", "0", "0", "198.18.0.1/16", ipv6_mode, ipv6_stack,
                    "0", "0", "blacklist", "1", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "2001:2::1/64", "0", "0"]
            environment = os.environ.copy()
            environment["RUBY_CAPTURE"] = str(capture)
            result = subprocess.run([BASH, "-s", "--", *args], input=prefix + source, env=environment, text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            argv = capture.read_bytes().decode("utf-8").split("\0")[:-1]
            code = argv[argv.index("-e") + 1]
            # This adapter only transports filesystem input/output. Its return
            # values are never the test expectations or the generated TUN map.
            adapter = r'''
module Kernel
  def `(command)
    raise "unexpected platform command: #{command}" unless command.start_with?('ls -l /sys/class/net/')
    "lo\nbr-lan\n"
  end
end
module YAML
  def self.load_file_cached(*)
    {'dns' => {'nameserver' => ['1.1.1.1']}, 'rules' => ['MATCH,DIRECT']}
  end
  def self.dump(value, *)
    STDOUT.write(::JSON.generate(value))
  end
  def self.cache_write(*)
  end
  def self.LOG_ERROR(message)
    STDERR.puts(message)
  end
  def self.LOG_TIP(*)
  end
end
'''
            if os.name == "nt":
                environment["PATH"] = "C:/Program Files/Git/usr/bin;" + environment.get("PATH", "")
            ruby = subprocess.run([RUBY, "-ryaml", "-rjson", "-e", "eval(STDIN.read, TOPLEVEL_BINDING)"], input=self.library + adapter + code, env=environment,
                                  text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(ruby.returncode, 0, ruby.stdout + ruby.stderr)
            self.assertEqual(ruby.stderr, "", "production Ruby generation reported an error: " + ruby.stderr)
            return json.loads(ruby.stdout)

    def core_check(self, core, config):
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        with tempfile.TemporaryDirectory(prefix="oc-core-dry-run-") as temporary:
            return subprocess.run([core, "-t", "-d", temporary, "-config", encoded], text=True, encoding="utf-8", capture_output=True)

    def test_missing_ipv4_and_ipv6_stack_uses_compatible_mixed(self):
        for kwargs in ({}, {"ipv4_tun": "0", "ipv6_mode": "2"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.generate(**kwargs)["tun"]["stack"], "mixed")

    def test_existing_explicit_stack_is_preserved_in_generation(self):
        for choice in ("system", "gvisor", "mixed", "mips"):
            for kwargs in ({"ipv4_stack": choice}, {"ipv4_tun": "0", "ipv6_mode": "2", "ipv6_stack": choice}):
                with self.subTest(choice=choice, kwargs=kwargs):
                    self.assertEqual(self.generate(**kwargs)["tun"]["stack"], choice)

    def startup(self, core, stack, quick_start, service=False, tun_enabled=True, runtime_config=None):
        with tempfile.TemporaryDirectory(prefix="oc-stack-start-") as temporary:
            directory = Path(temporary)
            record = directory / "events"
            config = directory / "runtime.yaml"
            tun = {"stack": stack}
            if tun_enabled is not None:
                tun["enable"] = tun_enabled
            raw = json.dumps(runtime_config if runtime_config is not None else {"tun": tun, "rules": ["MATCH,DIRECT"]})
            config.write_text(raw, encoding="utf-8")
            before = config.read_bytes()
            # The Ruby boundary uses stdin on this Windows host. The helper's
            # production -e program still parses the real supplied YAML bytes.
            command = r'''
LOG_ERROR() { printf '%s\n' "$*" >> "$EVENTS"; }
LOG_TIP() { :; }
LOG_OUT() { :; }
uci() { printf 'uci %s\n' "$*" >> "$EVENTS"; }
ulimit() { :; }
chown() { :; }
procd_open_instance() { echo core-start >> "$EVENTS"; }
procd_set_param() { :; }
procd_append_param() { :; }
procd_close_instance() { :; }
ruby() {
   "$RUBY_NATIVE" -ryaml -e 'class << YAML; def load_file(*) = load(ENV.fetch("RUNTIME_YAML")); end; eval(ARGV[0])' "${@: -2:1}"
}
'''
            definitions = shell_function(self.init, "check_tun_stack") + "\n" + shell_function(self.init, "start_run_core")
            if service:
                definitions += "\n" + shell_function(self.init, "start_service")
                command += r'''
uci_get_config() { echo 1; }
procd_running() { return 1; }
check_run_quick() { :; }
overwrite_file() { :; }
get_config() { :; }
config_choose() { :; }
do_run_mode() { :; }
do_run_file() { :; }
add_cron() { echo add-cron >> "$EVENTS"; }
check_core_status() { echo core-status >> "$EVENTS"; }
'''
            environment = os.environ.copy()
            environment.update({"EVENTS": str(record), "CLASH": core, "CLASH_CONFIG": directory.as_posix(), "CONFIG_FILE": config.as_posix(),
                                "TMP_CONFIG_FILE": config.as_posix(), "LOG_FILE": (directory / "log").as_posix(), "QUICK_START": "true" if quick_start else "false",
                                "RUBY_NATIVE": RUBY, "RUNTIME_YAML": raw})
            # mv's same-file status is unrelated to the gate; this boundary
            # leaves the already generated runtime bytes in their final path.
            command += "mv() { :; }\nrm() { :; }\n" + definitions + ("\nstart_service" if service else "\nstart_run_core")
            result = subprocess.run([BASH, "-s"], input=command, env=environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(config.read_bytes(), before, "startup rewrote the explicit runtime stack")
            return result, record.read_text(encoding="utf-8") if record.exists() else ""

    def test_real_core_accepts_generated_default_and_supported_choices(self):
        if not OLD_CORE or not NEW_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN and MIHOMO_NEW_TEST_BIN enable the real-core matrix")
        for core in (OLD_CORE, NEW_CORE):
            for stack in ("", "system", "gvisor", "mixed"):
                with self.subTest(core=core, stack=stack):
                    config = self.generate(ipv4_stack=stack)
                    result = self.core_check(core, config)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_mips_is_version_gated_by_real_core(self):
        if not OLD_CORE or not NEW_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN and MIHOMO_NEW_TEST_BIN enable the real-core mips check")
        for kwargs in ({"ipv4_stack": "mips"}, {"ipv4_tun": "0", "ipv6_mode": "2", "ipv6_stack": "mips"}):
            with self.subTest(kwargs=kwargs):
                config = self.generate(**kwargs)
                old = self.core_check(OLD_CORE, config)
                self.assertNotEqual(old.returncode, 0)
                self.assertIn("invalid tun stack", old.stdout + old.stderr)
                new = self.core_check(NEW_CORE, config)
                self.assertEqual(new.returncode, 0, new.stdout + new.stderr)

    def test_old_core_rejects_mips_before_registering_core_even_in_quick_start(self):
        if not OLD_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN enables the old-core startup check")
        for quick in (False, True):
            with self.subTest(quick_start=quick):
                result, events = self.startup(OLD_CORE, "mips", quick)
                self.assertNotEqual(result.returncode, 0, "unsupported mips reached the startup path")
                self.assertNotIn("core-start", events, "unsupported mips registered a respawning core")
                self.assertIn("mips", events)
                self.assertIn("mixed", events)
                self.assertNotIn("uci ", events, "rejected startup changed saved UCI settings")

    def test_start_service_propagates_rejection_without_cron_or_status_work(self):
        if not OLD_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN enables the old-core service check")
        result, events = self.startup(OLD_CORE, "mips", True, service=True)
        self.assertNotEqual(result.returncode, 0)
        for forbidden in ("core-start", "uci ", "add-cron", "core-status"):
            self.assertNotIn(forbidden, events)
        self.assertIn("mips", events, result.stdout + result.stderr)

    def test_old_core_rejects_disabled_or_unset_tun_with_retained_mips_before_startup(self):
        if not OLD_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN enables the disabled-TUN startup check")
        for enabled in (False, None):
            tun = {"stack": "mips"}
            if enabled is not None:
                tun["enable"] = enabled
            parsed = self.core_check(OLD_CORE, {"tun": tun, "rules": ["MATCH,DIRECT"]})
            self.assertNotEqual(parsed.returncode, 0)
            self.assertIn("invalid tun stack", parsed.stdout + parsed.stderr)
            for quick in (False, True):
                with self.subTest(quick_start=quick, tun_enabled=enabled):
                    result, events = self.startup(OLD_CORE, "mips", quick, tun_enabled=enabled)
                    self.assertNotEqual(result.returncode, 0, "disabled/unset TUN with retained mips reached startup")
                    self.assertNotIn("core-start", events)
                    self.assertNotIn("uci ", events)
                    self.assertIn("mips", events)

    def test_absent_null_and_non_mips_tun_skip_capability_probe(self):
        if not OLD_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN enables non-mips core checks")
        for config in ({}, {"tun": None}, {"tun": {}}, {"tun": {"enable": False, "stack": "mixed"}}):
            with self.subTest(config=config):
                config["rules"] = ["MATCH,DIRECT"]
                parsed = self.core_check(OLD_CORE, config)
                self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
                # Any attempted capability probe of this path would fail. The
                # normal launch boundary is recorded without executing a core.
                result, events = self.startup("no-core-probe-expected", "", True, runtime_config=config)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr + events)
                self.assertEqual(events, "core-start\n")

    def test_new_core_retains_mips_and_old_core_retains_supported_choices(self):
        if not OLD_CORE or not NEW_CORE:
            self.skipTest("MIHOMO_OLD_TEST_BIN and MIHOMO_NEW_TEST_BIN enable the startup matrix")
        for core, stacks in ((OLD_CORE, ("system", "gvisor", "mixed")), (NEW_CORE, ("system", "gvisor", "mixed", "mips"))):
            for stack in stacks:
                with self.subTest(core=core, stack=stack):
                    result, events = self.startup(core, stack, True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr + events)
                    self.assertEqual(events, "core-start\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
