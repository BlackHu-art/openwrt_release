#!/usr/bin/env python3
"""Run OAF's real config initializer and first-boot policy in an isolated tree."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "wrt_core/managed/packages"
MODULE = ROOT / "wrt_core/oaf_compat.py"
INPUTS = (
    "open-app-filter/Makefile",
    "open-app-filter/files/appfilter.init",
    "open-app-filter/files/luci-app-oaf.json",
    "luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json",
)


def bash_path(path):
    path = Path(path).resolve().as_posix()
    return "/" + path[0].lower() + path[2:] if os.name == "nt" else path


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def uci_values(text):
    """Read the named sections used by these hand-checked UCI fixtures."""
    section = None
    result = {}
    for line in text.splitlines():
        words = shlex.split(line, comments=True)
        if words and words[0] == "config":
            section = words[2] if len(words) == 3 else words[1]
        elif words and words[0] == "option":
            result[(section, words[1])] = words[2]
    return result


class OafCompatibility(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oaf-compat-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in INPUTS:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, target)
        self.backend = self.root / "open-app-filter"
        self.luci = self.root / "luci-app-oaf"
        self.prepare = None
        if MODULE.exists():
            spec = importlib.util.spec_from_file_location("oaf_compat", MODULE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.prepare = module.prepare
        self.assertIsNotNone(self.prepare, "OAF build-copy compatibility preparer is missing")

    def run_bash(self, source):
        bash = os.environ.get("BASH") or shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
        result = subprocess.run([bash, "--noprofile", "--norc", "-s"], input=source,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def initialize(self, config):
        config.mkdir(parents=True, exist_ok=True)
        source = (self.backend / "files/appfilter.init").read_text(encoding="utf-8")
        start = source.index("ensure_config_file()")
        end = source.index("\nstop_service()", start)
        helpers = source[start:end].replace("/etc/config", '"${TEST_CONFIG_DIR}"')
        self.run_bash("set -eu\nTEST_CONFIG_DIR=" + shlex.quote(bash_path(config)) +
                      "\n" + helpers + "\nensure_default_configs\n")

    def run_defaults(self, values):
        script = (self.backend / "files/99_disable_oaf").read_text(encoding="utf-8")
        # Only replace the router's UCI and init-service boundaries. Execute the
        # actual produced first-boot policy, including all its conditionals.
        script = script.replace("/etc/init.d/appfilter", 'oaf_service')
        flags = "\n".join("    '" + name + "') printf '%s' " + shlex.quote(value) + ";;"
                          for name, value in values.items())
        boundary = '''set -eu
uci() {
    [ "$1" = -q ] && [ "$2" = get ] || exit 71
    case "$3" in
''' + flags + '''
    *) return 1;;
    esac
}
oaf_service() { printf '%s\n' "$*"; }
'''
        return self.run_bash(boundary + script).stdout.splitlines()

    def test_fresh_initializer_and_packaged_config_disable_features_without_dropping_defaults(self):
        self.prepare(self.backend, self.luci)
        config = self.root / "runtime-config"
        self.initialize(config)
        actual = (config / "fwx").read_bytes()
        self.assertEqual(actual, (self.backend / "files/fwx").read_bytes())
        values = uci_values(actual.decode())
        for section in ("appfilter", "macfilter", "record"):
            self.assertEqual(values[(section, "enable")], "0")
        self.assertEqual(values[("advanced", "disable_hnat")], "0")
        self.assertEqual(values[("global", "lan_ifname")], "br-lan")
        self.assertEqual(values[("record", "history_data_path")], "/tmp/oaf")
        recipe = (self.backend / "Makefile").read_text(encoding="utf-8")
        conffiles = re.search(r"(?ms)^define Package/appfilter/conffiles\n(.*?)^endef", recipe).group(1)
        self.assertEqual(conffiles.splitlines().count("/etc/config/fwx"), 1)
        self.assertIn("$(INSTALL_CONF) ./files/fwx $(1)/etc/config/fwx", recipe)
        self.assertIn("./files/99_disable_oaf", recipe)

    def test_existing_explicit_values_and_custom_fields_survive_initializer_byte_for_byte(self):
        self.prepare(self.backend, self.luci)
        for enable in ("0", "1"):
            with self.subTest(enable=enable):
                config = self.root / ("existing-" + enable)
                config.mkdir()
                payload = ("# User formatting and unknown options remain intact.\n"
                           "config appfilter 'appfilter'\n\toption enable '" + enable + "'\n"
                           "\toption custom 'user value'\nconfig record 'record'\n"
                           "\toption enable '1'\n").encode()
                (config / "fwx").write_bytes(payload)
                (config / "appfilter").write_bytes(b"config rule 'saved'\n option id '42'\n")
                before = snapshot(config)
                self.initialize(config)
                for path, content in before.items():
                    self.assertEqual((config / path).read_bytes(), content)

    def test_legacy_config_is_preserved_without_schema_migration(self):
        self.prepare(self.backend, self.luci)
        config = self.root / "legacy-config"
        config.mkdir()
        old = b"config global global\n option enable '1'\nconfig time time\n option deny_time '60'\n"
        (config / "appfilter").write_bytes(old)
        self.initialize(config)
        self.assertEqual((config / "appfilter").read_bytes(), old)

    def test_firstboot_only_stops_when_all_three_features_are_explicitly_off(self):
        self.prepare(self.backend, self.luci)
        off = {"fwx.appfilter.enable": "0", "fwx.macfilter.enable": "0", "fwx.record.enable": "0"}
        self.assertEqual(self.run_defaults(off), ["disable", "stop"])
        for enabled in off:
            with self.subTest(enabled=enabled):
                self.assertEqual(self.run_defaults(dict(off, **{enabled: "1"})), [])
        for missing in off:
            with self.subTest(missing=missing):
                self.assertEqual(self.run_defaults({k: v for k, v in off.items() if k != missing}), [])

    def test_manual_start_retains_the_control_plane_even_when_default_features_are_off(self):
        self.prepare(self.backend, self.luci)
        config = self.root / "manual-config"
        config.mkdir()
        original = (self.backend / "files/appfilter.init").read_text(encoding="utf-8")
        # Source actual initializer/start_service code. Stub only host-facing
        # kernel/process/service boundaries so no router command can execute.
        source = original[original.index("ensure_config_file()") :]
        source = source.replace("/etc/config", '"${TEST_CONFIG_DIR}"')
        source = source.replace("/usr/bin/hnat.sh", "/nonexistent/oaf-test-hnat")
        boundary = '''set -u
TEST_CONFIG_DIR=''' + shlex.quote(bash_path(config)) + '''
FWXD_BIN=/usr/bin/oafd
CUSTOM_FEATURE_FILE=/nonexistent/oaf-test-feature
LEGACY_CUSTOM_FEATURE_FILE=/nonexistent/oaf-test-legacy-feature
lsmod() { :; }
modprobe() { printf 'module:%s\n' "$*"; }
procd_open_instance() { :; }
procd_close_instance() { :; }
procd_set_param() { [ "$1" != command ] || printf 'process:%s\n' "$2"; }
'''
        output = self.run_bash(boundary + source + "\nstart_service\n").stdout.splitlines()
        self.assertEqual(output, ["module:oaf", "process:/usr/bin/oafd", "process:/usr/bin/rule_manager"])
        self.assertEqual(uci_values((config / "fwx").read_text())[('appfilter', 'enable')], "0")

    def test_acl_has_one_payload_owner_and_preserves_both_permission_groups(self):
        baseline = [json.loads((SOURCE / relative).read_text(encoding="utf-8"))
                    for relative in INPUTS[2:]]
        self.prepare(self.backend, self.luci)
        payloads = list(self.root.rglob("luci-app-oaf.json"))
        self.assertEqual(payloads, [self.backend / "files/luci-app-oaf.json"])
        merged = json.loads(payloads[0].read_text(encoding="utf-8"))
        for document in baseline:
            for group, permissions in document.items():
                self.assertEqual(merged[group], permissions)

    def test_actual_install_stanza_ships_the_default_conffile_and_single_acl(self):
        shutil.copytree(SOURCE / "open-app-filter/files", self.backend / "files", dirs_exist_ok=True)
        self.prepare(self.backend, self.luci)
        recipe = (self.backend / "Makefile").read_text(encoding="utf-8")
        install = re.search(r"(?ms)^define Package/appfilter/install\n(.*?)^endef", recipe).group(1)
        destination = self.root / "rootfs"
        build = self.root / "built"
        build.mkdir()
        (build / "oafd").write_bytes(b"test core artifact\n")
        substitutions = {
            "$(INSTALL_DIR)": "install -d", "$(INSTALL_CONF)": "install -m 0600",
            "$(INSTALL_BIN)": "install -m 0755", "$(INSTALL_DATA)": "install -m 0644",
            "$(PKG_BUILD_DIR)": shlex.quote(bash_path(build)),
            "$(1)": shlex.quote(bash_path(destination)),
        }
        for expression, replacement in substitutions.items():
            install = install.replace(expression, replacement)
        self.assertNotIn("$(", install, "installation stanza gained an unexercised macro")
        self.run_bash("set -eu\ncd " + shlex.quote(bash_path(self.backend)) + "\n" + install)
        self.assertEqual((destination / "etc/config/fwx").read_bytes(), (self.backend / "files/fwx").read_bytes())
        self.assertEqual((destination / "usr/share/rpcd/acl.d/luci-app-oaf.json").read_bytes(),
                         (self.backend / "files/luci-app-oaf.json").read_bytes())
        self.assertTrue((destination / "etc/uci-defaults/99_disable_oaf").is_file())
        self.assertFalse((self.luci / "root/usr/share/rpcd/acl.d/luci-app-oaf.json").exists())

    def test_command_line_prepares_then_verifies_the_same_build_copies(self):
        before = snapshot(self.root)
        for expected in ("prepared", "verified"):
            result = subprocess.run([sys.executable, "-B", str(MODULE), str(self.backend), str(self.luci)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout)
        self.assertNotEqual(snapshot(self.root), before)

    def test_prepare_repeats_without_writes_and_keeps_original_snapshot_unchanged(self):
        raw_before = {relative: (SOURCE / relative).read_bytes() for relative in INPUTS}
        first = self.prepare(self.backend, self.luci)
        self.assertTrue(first["changed"])
        before = snapshot(self.root)
        stamps = {p: (self.root / p).stat().st_mtime_ns for p in before}
        self.assertFalse(self.prepare(self.backend, self.luci)["changed"])
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual({p: (self.root / p).stat().st_mtime_ns for p in before}, stamps)
        self.assertEqual({p: (SOURCE / p).read_bytes() for p in INPUTS}, raw_before)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.backend / "files/99_disable_oaf").stat().st_mode), 0o755)

    def test_any_source_drift_is_rejected_before_publishing_or_deleting_payloads(self):
        for relative in INPUTS:
            with self.subTest(path=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(original + b"\n# unexpected upstream change\n")
                before = snapshot(self.root)
                with self.assertRaisesRegex(ValueError, "OAF|unreviewed|source|drift"):
                    self.prepare(self.backend, self.luci)
                self.assertEqual(snapshot(self.root), before)
                path.write_bytes(original)

    def test_unknown_generated_file_and_partial_preparation_are_rejected_without_changes(self):
        path = self.backend / "files/fwx"
        path.write_bytes(b"user owned file\n")
        before = snapshot(self.root)
        with self.assertRaises(ValueError):
            self.prepare(self.backend, self.luci)
        self.assertEqual(snapshot(self.root), before)
        path.unlink()
        self.prepare(self.backend, self.luci)
        (self.backend / "files/appfilter.init").write_bytes((SOURCE / INPUTS[1]).read_bytes())
        before = snapshot(self.root)
        with self.assertRaises(ValueError):
            self.prepare(self.backend, self.luci)
        self.assertEqual(snapshot(self.root), before)

    def test_raw_managed_snapshot_cannot_be_used_as_mutation_target(self):
        before = {relative: (SOURCE / relative).read_bytes() for relative in INPUTS}
        with self.assertRaises(ValueError):
            self.prepare(SOURCE / "open-app-filter", SOURCE / "luci-app-oaf")
        self.assertEqual({p: (SOURCE / p).read_bytes() for p in INPUTS}, before)


if __name__ == "__main__":
    unittest.main()
