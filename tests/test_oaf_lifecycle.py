#!/usr/bin/env python3
"""Execute captured target postinst/rc.common against the prepared OAF init.

Only filesystem roots, host kernel/procd commands and UCI are adapted. Package
manager list selection, defaults ordering, enable/start and init dispatch use
immutable upstream source, independently of the compatibility helper's template.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from test_oaf_compat import ROOT, SOURCE, INPUTS, bash_path

FIXTURES = ROOT / "tests/fixtures/oaf-lifecycle"
OFF = {"fwx.appfilter.enable": "0", "fwx.macfilter.enable": "0", "fwx.record.enable": "0"}
BASH = os.environ.get("BASH") or shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"


class OafOnlineLifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oaf-online-lifecycle-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        receipt = json.loads((FIXTURES / "receipt.json").read_text(encoding="utf-8"))
        for target in receipt["targets"]:
            for name in ("functions.sh", "rc.common"):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(),
                                 target["files"][name]["sha256"])
        spec = importlib.util.spec_from_file_location("oaf_lifecycle_compat", ROOT / "wrt_core/oaf_compat.py")
        self.compat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.compat)
        self.build = self.base / "build"
        for relative in INPUTS:
            destination = self.build / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
        self.backend, self.luci = self.build / "open-app-filter", self.build / "luci-app-oaf"
        self.compat.prepare(self.backend, self.luci)
        self.index = 0

    def exercise(self, manager, upgrade, flags, *, enabled=False, manual=False, firstboot=False, stale_token=False):
        self.index += 1
        root = self.base / ("root-" + str(self.index))
        for relative in ("etc/init.d", "etc/rc.d", "etc/uci-defaults", "etc/config", "usr/lib/opkg/info",
                         "lib/apk/packages", "lib/functions", "usr/share/libubox", "body", "tmp", "var/run", "bin"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        prefix = bash_path(root)
        postinst = re.search(r"(?ms)^default_postinst\(\) \{.*?^\}",
                             (FIXTURES / "functions.sh").read_text(encoding="utf-8")).group(0)
        for path in ("/usr/lib/opkg/", "/lib/apk/", "/etc/", "/tmp/"):
            postinst = postinst.replace(path, prefix + path)
        rc = (FIXTURES / "rc.common").read_text(encoding="utf-8")
        rc = rc.replace("/lib/functions", prefix + "/lib/functions").replace("/etc/rc.d", prefix + "/etc/rc.d")
        if os.name == "nt":
            # MSYS represents an enable link as a copied file on this Windows
            # host. Adapt only the symlink filesystem predicate; Linux executes
            # native rc.common link checks without this substitution.
            self.assertEqual(rc.count('[ -L '), 2)
            rc = rc.replace('[ -L ', '[ -e ')
        (root / "rc.common").write_text(rc, encoding="utf-8", newline="\n")
        (root / "lib/functions.sh").write_text('''list_contains() {
    eval "case \\" \\${$1} \\" in *\\" $2 \\"*) return 0;; *) return 1;; esac"
}
''', encoding="utf-8", newline="\n")
        (root / "lib/functions/service.sh").write_text("")
        (root / "usr/share/libubox/jshn.sh").write_text("")
        (root / "lib/functions/procd.sh").write_text('''procd_open_service() { :; }
procd_close_service() { :; }
procd_open_instance() { :; }
procd_close_instance() { :; }
procd_lock() { :; }
procd_kill() { rm -f "$TEST_RUNNING"; }
procd_set_param() {
    if [ "$1" = command ]; then
        printf 'procd-command:%s\\n' "$2" >> "$TEST_LOG"
        : > "$TEST_RUNNING"
    fi
}
''', encoding="utf-8", newline="\n")
        init = (self.backend / "files/appfilter.init").read_text(encoding="utf-8")
        defaults = (self.backend / "files/99_disable_oaf").read_text(encoding="utf-8")
        for path in ("/etc/config", "/etc/init.d/appfilter", "/lib/functions.sh", "/usr/share/libubox/jshn.sh", "/var/run/.oaf-postinst-"):
            init = init.replace(path, prefix + path)
            defaults = defaults.replace(path, prefix + path)
        init = init.replace("/usr/bin/hnat.sh", prefix + "/absent-hnat")
        (root / "body/appfilter").write_text(init, encoding="utf-8", newline="\n")
        service = root / "etc/init.d/appfilter"
        service.write_text('#!/bin/sh\nprintf "service:%s\\n" "$1" >> "$TEST_LOG"\n' +
                           '[ "$1" != start ] || for marker in ' + shlex.quote(prefix + '/tmp') + '/.oaf-postinst-*; do [ ! -f "$marker" ] || echo public-token-before-start >> "$TEST_LOG"; done\n' +
                           'exec bash ' +
                           shlex.quote(prefix + "/rc.common") + " " + shlex.quote(prefix + "/body/appfilter") + ' "$@"\n',
                           encoding="utf-8", newline="\n")
        (root / "etc/uci-defaults/99_disable_oaf").write_text(defaults, encoding="utf-8", newline="\n")
        listing = "usr/lib/opkg/info/appfilter.list" if manager == "opkg" else "lib/apk/packages/appfilter.list"
        (root / listing).write_text(prefix + "/etc/init.d/appfilter\n" + prefix + "/etc/uci-defaults/99_disable_oaf\n",
                                   encoding="utf-8", newline="\n")
        cases = "\n".join("    " + shlex.quote(key) + ") printf '%s' " + shlex.quote(value) + ";;" for key, value in flags.items())
        uci = '''[ "$1" != commit ] || exit 0
[ "$1" = -q ] && [ "$2" = get ] || exit 71
case "$3" in
''' + cases + '\n    *) exit 1;;\nesac\n'
        for name, body in (("uci", uci), ("modprobe", 'printf "module:%s\\n" "$*" >> "$TEST_LOG"'),
                           ("lsmod", "exit 0"), ("killall", 'printf "kill:%s\\n" "$*" >> "$TEST_LOG"')):
            (root / "bin" / name).write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
        # Existing formatting/custom keys are protected independently of mock UCI.
        saved = b"# saved administrator configuration\nconfig appfilter appfilter\n option custom 'keep me'\n"
        (root / "etc/config/fwx").write_bytes(saved)
        log = root / "events"
        command = "export TEST_LOG=" + shlex.quote(bash_path(log)) + "\n"
        command += "export TEST_RUNNING=" + shlex.quote(prefix + "/running") + "\n"
        command += "export PATH=" + shlex.quote(prefix + "/bin") + ":$PATH\n"
        command += "chmod +x " + shlex.quote(prefix) + "/bin/* " + shlex.quote(bash_path(service)) + "\n"
        command += "IPKG_INSTROOT=\nexport PKG_UPGRADE=" + shlex.quote("1" if upgrade else "") + "\n"
        if enabled:
            command += shlex.quote(bash_path(service)) + " enable\n"
        command += ': > "$TEST_LOG"\n'
        if firstboot:
            command += ". " + shlex.quote(prefix + "/etc/uci-defaults/99_disable_oaf") + "\n"
        else:
            command += "pkgname=appfilter\nadd_group_and_user() { :; }\nupdate_alternatives() { :; }\n"
            command += postinst + "\ndefault_postinst appfilter.postinst || exit\n"
        if stale_token:
            # A terminated installer can leave a token; a reused PID must not
            # suppress a later administrator's start from a different process.
            command += "printf 'invalid-process-birth\\n' > " + shlex.quote(prefix + "/var/run/.oaf-postinst-") + "$$\n"
        if manual:
            command += "printf 'manual-boundary\\n' >> \"$TEST_LOG\"\n"
            command += shlex.quote(bash_path(service)) + " enable\n"
            command += shlex.quote(bash_path(service)) + " start\n"
        result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], input=command, capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual((root / "etc/config/fwx").read_bytes(), saved)
        return {"events": log.read_text().splitlines(), "enabled": (root / "etc/rc.d/S96appfilter").exists(),
                "running": (root / "running").exists(), "markers": list((root / "var/run").glob(".oaf-postinst-*"))}

    def test_root_installer_never_writes_its_token_in_the_public_tmp_directory(self):
        result = self.exercise("opkg", False, OFF)
        self.assertNotIn("public-token-before-start", result["events"])

    def test_real_opkg_apk_install_and_upgrade_finish_disabled_for_default_off(self):
        for manager in ("opkg", "apk"):
            for upgrade in (False, True):
                with self.subTest(manager=manager, upgrade=upgrade):
                    result = self.exercise(manager, upgrade, OFF)
                    self.assertFalse(result["enabled"], result)
                    self.assertFalse(result["running"], result)
                    self.assertFalse(any(e.startswith("procd-command:") for e in result["events"]), result)
                    self.assertEqual(result["markers"], [])

    def test_explicit_enabled_unknown_or_missing_feature_values_keep_normal_start(self):
        for manager in ("opkg", "apk"):
            for value in ("1", "unknown", None):
                flags = dict(OFF)
                if value is None:
                    del flags["fwx.record.enable"]
                else:
                    flags["fwx.record.enable"] = value
                with self.subTest(manager=manager, value=value):
                    result = self.exercise(manager, False, flags)
                    self.assertTrue(result["running"], result)
                    self.assertTrue(result["enabled"], result)
                    self.assertEqual(result["markers"], [])

    def test_upgrade_preserves_administrator_enabled_choice_with_all_flags_off(self):
        for manager in ("opkg", "apk"):
            with self.subTest(manager=manager):
                result = self.exercise(manager, True, OFF, enabled=True)
                self.assertTrue(result["enabled"], result)
                self.assertTrue(result["running"], result)
                self.assertNotIn("service:disable", result["events"])
                self.assertEqual(result["markers"], [])

    def test_manual_enable_start_works_after_default_online_install_or_upgrade(self):
        for manager in ("opkg", "apk"):
            for upgrade in (False, True):
                with self.subTest(manager=manager, upgrade=upgrade):
                    result = self.exercise(manager, upgrade, OFF, manual=True)
                    self.assertTrue(result["enabled"], result)
                    self.assertTrue(result["running"], result)
                    boundary = result["events"].index("manual-boundary")
                    self.assertIn("procd-command:/usr/bin/oafd", result["events"][boundary:])
                    self.assertEqual(result["markers"], [])

    def test_stale_install_token_cannot_block_manual_start_after_pid_reuse(self):
        result = self.exercise("opkg", False, OFF, manual=True, stale_token=True)
        self.assertTrue(result["enabled"], result)
        self.assertTrue(result["running"], result)
        self.assertEqual(result["markers"], [])

    def test_firstboot_does_not_leave_an_online_install_token(self):
        result = self.exercise("opkg", False, OFF, enabled=True, firstboot=True)
        self.assertFalse(result["enabled"], result)
        self.assertFalse(result["running"], result)
        self.assertEqual(result["markers"], [])


if __name__ == "__main__":
    unittest.main()
