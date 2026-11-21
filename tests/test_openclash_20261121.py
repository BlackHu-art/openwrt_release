#!/usr/bin/env python3
"""Execute the reviewed OpenClash shutdown and DNS backports offline."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from openclash_fixture import ROOT, SOURCES, make_package
from test_openclash_tun_stack import BASH, RUBY, shell_function


CORE = ROOT / "wrt_core"
HISTORY = SOURCES["openclash_history_get.sh"]
INIT = SOURCES["openclash.init"]
ACTIVE = "./etc/openclash/运行 配置.yaml"
SELECTED = "./etc/openclash/config/另一 配置.yaml"

STOP_PLATFORM = r'''
get_config() { enable=1; }
LOG_TIP() { :; }
LOG_OUT() { :; }
LOG_WARN() { :; }
revert_firewall() { :; }
revert_dnsmasq() { :; }
del_cron() { :; }
clear_overwrite_set() { :; }
unify_ps_pids() { :; }
unify_ps_cfgname() { if pidof clash >/dev/null; then printf '%s\n' "$ACTIVE"; fi; }
pidof() { [ "$1" = clash ] && [ -f core ] && printf '9876\n'; }
procd_send_signal() { :; }
procd_kill() { [ "$*" = 'openclash openclash' ] && touch stop-requested; }
procd_running() { [ "$PROCD_UNTRACKED" = 0 ] && pidof clash; }
procd_open_service() { :; }
procd_close_service() { :; }
sleep() {
   [ -f stop-requested ] || return 1
   tick=$(cat ticks)
   tick=$((tick + 1))
   printf '%s' "$tick" > ticks
   if [ "$tick" -eq "$EXIT_AT" ]; then
      printf 'cache finalized on exit' > ./tmp/etc/openclash/cache.db
      rm core
   fi
}
uci_get_config() {
   case "$1" in
      small_flash_memory) echo 1;;
      config_path) printf '%s\n' "$SELECTED";;
      dashboard_password) echo test-password;;
      lan_interface_name) echo 0;;
      cn_port) echo 9090;;
      *) return 1;;
   esac
}
uci() { [ "$*" = '-q get network.lan.ipaddr' ] && echo '192.0.2.1/24'; }
flock() { :; }
curl() { printf '%s\n' "$@" > curl-arguments; }
run_history() { "$BASH" history.sh "$@"; }
initscript=/etc/init.d/openclash
'''

DNS_PLATFORM = r'''
uci_get_config() {
   case "$1" in
      custom_fakeip_filter) echo "$CUSTOM_FILTER";;
      china_ip_route) echo "$CHINA_ROUTE";;
      *) return 1;;
   esac
}
uci() { return 1; }
config_load() { :; }
config_foreach() { :; }
LOG_TIP() { :; }
LOG_ERROR() { :; }
ruby() {
   "$RUBY_NATIVE" -E UTF-8 -ryaml -e '
      path, code = ARGV
      eval(File.read(path, encoding: "UTF-8").gsub("/tmp/", "tmp/"), TOPLEVEL_BINDING, path)
      eval(code, TOPLEVEL_BINDING)
   ' "$OPENCLASH_YAML" "${@: -1}"
}
'''


class OpenClashRepairs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = tempfile.TemporaryDirectory(prefix="openclash-20261121-")
        cls.addClassCleanup(cls.sandbox.cleanup)
        cls.package = Path(cls.sandbox.name) / "package"
        make_package(cls.package)
        result = cls.prepare(cls.package)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oc-repair-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    @staticmethod
    def prepare(package):
        return subprocess.run(
            [sys.executable, str(CORE / "openclash_runtime_compat.py"), "prepare",
             "--core", str(CORE), "--package", str(package)],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )

    @staticmethod
    def snapshot(package):
        return {p.relative_to(package).as_posix(): p.read_bytes()
                for p in package.rglob("*") if p.is_file() and ".git" not in p.parts}

    def run_command(self, command, source=None, **platform):
        result = subprocess.run(
            command, cwd=self.directory, input=source, env={**os.environ, **platform},
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def file(self, name, content):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def stop_or_backup(self, operation="stop_service", *, active=ACTIVE, exit_at=2,
                       untracked=False, cache=True):
        # Keep the real copy/compare and history pathname logic. The process
        # boundary writes the final cache only after shutdown was requested.
        self.file(ACTIVE, "running config")
        self.file(SELECTED, "selected config")
        self.file("etc/openclash/history/另一 配置.db", "previous B")
        self.file("etc/openclash/history/运行 配置.db", "previous A")
        self.file("core", "")
        self.file("ticks", "0")
        self.file("openwrt_release", "")
        (self.directory / "tmp/lock").mkdir(parents=True)
        if cache:
            self.file("tmp/etc/openclash/cache.db", "live cache")
        self.file("platform.sh", STOP_PLATFORM)
        history = (self.package / HISTORY).read_text(encoding="utf-8")
        history = re.sub(r"^\. /[^\n]+\n", "", history, flags=re.M)
        history = re.sub(r"/(?:tmp|etc/openclash)/", r".\g<0>", history)
        history = history.replace("/etc/openwrt_release", "./openwrt_release")
        self.file("history.sh", ". ./platform.sh\n" + history)
        init = (self.package / INIT).read_text(encoding="utf-8")
        stop = shell_function(init, "stop_service").replace("/tmp/", "./tmp/")
        stop = stop.replace("/usr/share/openclash/openclash_history_get.sh", "run_history")
        self.run_command(
            [BASH, "-s"], ". ./platform.sh\n" + stop + "\n" + operation + "\n",
            ACTIVE=active, SELECTED=SELECTED, EXIT_AT=str(exit_at), PROCD_UNTRACKED=str(int(untracked)),
        )
        history_dir = self.directory / "etc/openclash/history"
        return {p.name: p.read_text(encoding="utf-8") for p in history_dir.iterdir()}

    def test_backup_waits_for_final_write_and_uses_running_config(self):
        histories = self.stop_or_backup()
        self.assertEqual(histories, {"运行 配置.db": "cache finalized on exit", "另一 配置.db": "previous B"})

    def test_backup_waits_for_process_even_if_procd_has_unregistered_it(self):
        histories = self.stop_or_backup(untracked=True)
        self.assertEqual(histories["运行 配置.db"], "cache finalized on exit")

    def test_slow_core_does_not_overwrite_the_previous_history(self):
        histories = self.stop_or_backup(exit_at=11)
        self.assertEqual(histories["运行 配置.db"], "previous A")
        self.assertEqual((self.directory / "ticks").read_text(), "10")

    def test_after_stop_helper_rechecks_that_no_core_is_running(self):
        histories = self.stop_or_backup('run_history after_stop "$ACTIVE"')
        self.assertEqual(histories["运行 配置.db"], "previous A")

    def test_missing_running_config_does_not_backup_the_uci_config_on_stop(self):
        histories = self.stop_or_backup(active="")
        self.assertEqual(histories["另一 配置.db"], "previous B")

    def test_ordinary_live_backup_can_fall_back_to_the_uci_config(self):
        histories = self.stop_or_backup("run_history", active="")
        self.assertEqual(histories, {"运行 配置.db": "previous A", "另一 配置.db": "live cache"})

    def test_missing_cache_does_not_overwrite_the_previous_history(self):
        histories = self.stop_or_backup("run_history", cache=False)
        self.assertEqual(histories, {"运行 配置.db": "previous A", "另一 配置.db": "previous B"})

    def test_close_connections_still_calls_the_dashboard_without_copying_history(self):
        histories = self.stop_or_backup("run_history close_all_conection")
        self.assertEqual(histories, {"运行 配置.db": "previous A", "另一 配置.db": "previous B"})
        request = (self.directory / "curl-arguments").read_text().splitlines()
        self.assertEqual(request[-3:], ["-X", "DELETE", "http://192.0.2.1:9090/connections"])

    def generate_filters(self, filters, *, custom=None, pass_list=None, cn=False):
        self.assertTrue(RUBY, "Ruby is required to execute the YAML generator")
        (self.directory / "tmp").mkdir()
        (self.directory / "sys-net").mkdir()
        if custom is not None:
            self.file("custom/openclash_custom_fake_filter.list", custom)
        if pass_list is not None:
            self.file("custom/openclash_custom_chnroute_pass.list", pass_list)
        # JSON is valid YAML. Keeping the provider configured ensures the
        # dangling-provider cleanup cannot hide a missed CN pattern.
        config = {"dns": {"nameserver": ["1.1.1.1"], "fake-ip-filter": filters,
                          "fake-ip-filter-mode": "whitelist"},
                  "rule-providers": {"oc-cn-domain": {"type": "file", "behavior": "domain",
                                                     "path": "./cn.mrs", "format": "mrs"}},
                  "rules": ["MATCH,DIRECT"]}
        self.file("runtime.yaml", json.dumps(config))
        path = self.package / SOURCES["yml_change.sh"]
        source = re.sub(r"^\. /[^\n]+\n", "", path.read_text(encoding="utf-8"), flags=re.M)
        source = source.replace("/tmp/", "tmp/").replace("/etc/openclash/custom/", "custom/")
        source = source.replace("/sys/class/net/", "sys-net/")
        args = ["0"] * 48
        args[:5] = ["fake-ip", "", "9090", "7892", "runtime.yaml"]
        args[27], args[32] = "198.18.0.1/16", "whitelist"
        self.run_command([BASH, "-s", "--", *args], DNS_PLATFORM + source,
                         OPENCLASH_YAML=str(path.with_name("YAML.rb")), RUBY_NATIVE=RUBY,
                         CUSTOM_FILTER=str(int(custom is not None)), CHINA_ROUTE=str(int(cn)))
        result = self.run_command([RUBY, "-ryaml", "-rjson", "-e",
                                   'puts JSON.generate(YAML.load_file(ARGV.fetch(0)))', "runtime.yaml"])
        return json.loads(result.stdout)["dns"]["fake-ip-filter"]

    def test_custom_dns_list_replaces_a_scalar(self):
        self.assertEqual(self.generate_filters("invalid", custom="# comment\n+.first.test\n\n+.second.test # comment\n"),
                         ["+.first.test", "+.second.test"])

    def test_custom_dns_list_still_merges_and_deduplicates_arrays(self):
        self.assertEqual(self.generate_filters(["+.old.test", "+.first.test"], custom="+.first.test\n"),
                         ["+.first.test", "+.old.test"])

    def test_whitelist_removes_only_the_bypassed_domain_tree(self):
        filters = ["+.example.com", "*.WWW.EXAMPLE.COM", "sub.example.com", "notexample.com",
                   "example.com.test", "DOMAIN-SUFFIX,example.com,real-ip"]
        self.assertEqual(self.generate_filters(filters, pass_list="+.example.com\n", cn=True),
                         ["notexample.com", "example.com.test", "DOMAIN-SUFFIX,example.com,real-ip"])

    def test_whitelist_filters_cn_but_preserves_non_cn_and_no_cn(self):
        excluded = ["rule-set:oc-cn-domain", "GEOSITE:CN", "geosite:x@china", "RULE-SET,china,real-ip"]
        kept = ["geosite:geolocation-non-cn", "rule-set:test-no-cn", "rule-set:non-cn-domain", "rule-set:global"]
        self.assertEqual(self.generate_filters(excluded + kept, cn=True), kept)

    def test_prepare_rejects_drifted_or_missing_history_helper_before_writing(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                package = self.directory / str(missing)
                make_package(package)
                target = package / HISTORY
                if missing:
                    target.unlink()
                else:
                    target.write_bytes(target.read_bytes() + b"\n# unknown source drift\n")
                before = self.snapshot(package)
                result = self.prepare(package)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(HISTORY, result.stderr)
                self.assertEqual(self.snapshot(package), before)

    def test_prior_nine_patch_stack_upgrades_and_repeat_prepare_is_stable(self):
        package = self.directory / "prior-stack"
        make_package(package)
        self.run_command(["git", "init", "-q", str(package)])
        names = (
            "wan-subnets", "checksum-filename", "ruby-ast", "dashboard-switch",
            "filename-safety", "tun-stack", "subscription-safety", "group-rename", "etag-lock",
        )
        for name in names:
            self.run_command(["git", "-C", str(package), "apply", str(CORE / "patches" / f"openclash-{name}.patch")])
        before = self.snapshot(package)
        result = self.prepare(package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.snapshot(package)
        self.assertEqual({name for name in before if before[name] != after[name]}, {HISTORY, INIT, SOURCES["yml_change.sh"]})
        self.assertEqual(after, self.snapshot(self.package))
        result = self.prepare(package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(package), after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
