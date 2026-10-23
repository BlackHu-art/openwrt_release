#!/usr/bin/env python3
"""The firmware intentionally ships Passwall2, without Passwall1 sources."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Passwall2OnlyTests(unittest.TestCase):
    def test_removed_plugin_has_no_snapshot_or_patches(self):
        for relative in (
            "maintenance/plugins/passwall", "maintenance/plugins/manifests/passwall.json",
            "maintenance/plugins/licenses/passwall", "wrt_core/patches/passwall-singbox-tls-pin.patch",
            "wrt_core/patches/passwall-singbox-launch.patch",
        ):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())
        lock = json.loads((ROOT / "maintenance/plugins/sources.lock.json").read_text())
        ids = {row["id"] for row in lock["sources"]}
        self.assertNotIn("passwall", ids)
        self.assertIn("passwall2", ids)

    def test_build_imports_only_passwall2(self):
        feed = (ROOT / "wrt_core/modules/custom_feed.sh").read_text(encoding="utf-8")
        self.assertNotIn("Openwrt-Passwall/openwrt-passwall|", feed)
        self.assertIn("Openwrt-Passwall/openwrt-passwall2|", feed)
        update = (ROOT / "wrt_core/update.sh").read_text(encoding="utf-8")
        self.assertIn('fix_passwall2_compat "$(get_custom_feed_worktree_dir)/luci-app-passwall2"', update)
        self.assertNotIn("apply_passwall_tweaks", update)

    def test_defconfig_cannot_reenable_removed_plugin(self):
        with tempfile.TemporaryDirectory() as temporary:
            requested, resolved = Path(temporary) / "requested", Path(temporary) / "resolved"
            requested.write_text("# CONFIG_PACKAGE_luci-app-passwall is not set\nCONFIG_PACKAGE_luci-app-passwall2=y\n")
            resolved.write_text("CONFIG_PACKAGE_luci-app-passwall=y\nCONFIG_PACKAGE_luci-app-passwall2=y\n")
            result = subprocess.run([sys.executable, str(ROOT / "wrt_core/check_selected_plugins.py"),
                                     str(requested), str(resolved)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("luci-app-passwall", result.stderr)

    def test_shared_firmware_selection(self):
        fragment = (ROOT / "wrt_core/deconfig/fragments/proxy.config").read_text()
        self.assertIn("# CONFIG_PACKAGE_luci-app-passwall is not set", fragment)
        self.assertIn("CONFIG_PACKAGE_luci-app-passwall2=y", fragment)
        self.assertNotIn("CONFIG_PACKAGE_luci-app-passwall=y", fragment)


if __name__ == "__main__":
    unittest.main()
