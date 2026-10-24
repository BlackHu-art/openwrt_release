#!/usr/bin/env python3
"""Removed proxy apps have no build inputs and cannot return via defconfig."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RemovedProxyPlugins(unittest.TestCase):
    def test_removed_plugins_have_no_snapshot_manifest_license_or_patches(self):
        for plugin in ("passwall", "passwall2"):
            for relative in (f"maintenance/plugins/{plugin}",
                             f"maintenance/plugins/manifests/{plugin}.json",
                             f"maintenance/plugins/licenses/{plugin}"):
                with self.subTest(path=relative):
                    self.assertFalse((ROOT / relative).exists(), relative)
            self.assertFalse(list((ROOT / "wrt_core/patches").glob(plugin + "-*.patch")))
        lock = json.loads((ROOT / "maintenance/plugins/sources.lock.json").read_text())
        ids = {row["id"] for row in lock["sources"]}
        self.assertTrue({"passwall", "passwall2"}.isdisjoint(ids))
        self.assertIn("ssrplus-v198.2", ids)

    def test_build_has_no_removed_import_or_adapter(self):
        for relative in ("wrt_core/modules/custom_feed.sh", "wrt_core/update.sh",
                         "wrt_core/modules/xray_core_compat.sh", "wrt_core/modules/verify.sh"):
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertNotIn("passwall2", path.read_text(encoding="utf-8").lower())

    def test_firmware_selection_explicitly_disables_removed_apps_and_translation(self):
        paths = [ROOT / "wrt_core/deconfig/fragments/proxy.config"]
        paths += [ROOT / "wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config"]
        for path in paths:
            content = path.read_text()
            for package in ("luci-app-passwall2", "luci-i18n-passwall2-zh-cn"):
                with self.subTest(path=path.name, package=package):
                    self.assertRegex(content, r"(?m)^(?:# CONFIG_PACKAGE_" + package +
                                     r" is not set|CONFIG_PACKAGE_" + package + r"=n)$")
                    self.assertNotRegex(content, r"(?m)^CONFIG_PACKAGE_" + package + r"=[ym]$")
        self.assertIn("CONFIG_PACKAGE_luci-app-ssr-plus=y", paths[1].read_text())

    def test_defconfig_cannot_reenable_removed_app_or_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            requested, resolved = Path(temporary) / "requested", Path(temporary) / "resolved"
            for package in ("luci-app-passwall", "luci-i18n-passwall-zh-cn",
                            "luci-app-passwall2", "luci-i18n-passwall2-zh-cn"):
                for disabled in (f"# CONFIG_PACKAGE_{package} is not set\n", f"CONFIG_PACKAGE_{package}=n\n"):
                    for enabled in ("y", "m"):
                        with self.subTest(package=package, disabled=disabled.strip(), enabled=enabled):
                            requested.write_text(disabled)
                            resolved.write_text(f"CONFIG_PACKAGE_{package}={enabled}\n")
                            result = subprocess.run([sys.executable, str(ROOT / "wrt_core/check_selected_plugins.py"),
                                                     str(requested), str(resolved)], capture_output=True, text=True)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn(f"{package}: requested=n, resolved={enabled}", result.stderr)


if __name__ == "__main__":
    unittest.main()
