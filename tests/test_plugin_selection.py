"""Verify that feed/Kconfig changes cannot silently remove requested LuCI packages."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "wrt_core/check_selected_plugins.py"


class PluginSelectionTests(unittest.TestCase):
    def check_selection(self, requested, resolved):
        with tempfile.TemporaryDirectory(prefix="plugin-selection-") as directory:
            source = Path(directory) / "requested.config"
            final = Path(directory) / ".config"
            source.write_text(requested, encoding="utf-8")
            final.write_text(resolved, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECKER), str(source), str(final)],
                capture_output=True, text=True, encoding="utf-8",
            )

    def test_missing_and_demoted_apps_are_reported_together(self):
        result = self.check_selection(
            "CONFIG_PACKAGE_luci-app-homeproxy=y\nCONFIG_PACKAGE_luci-app-ssr-plus=y\n",
            "CONFIG_PACKAGE_luci-app-ssr-plus=m\n",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("luci-app-homeproxy: requested=y, resolved=n", result.stderr)
        self.assertIn("luci-app-ssr-plus: requested=y, resolved=m", result.stderr)

    def test_module_can_be_built_in_and_disabled_overrides_win(self):
        result = self.check_selection(
            "CONFIG_PACKAGE_luci-app-athena-led=m\n"
            "CONFIG_PACKAGE_luci-app-mosdns=y\n"
            "# CONFIG_PACKAGE_luci-app-mosdns is not set\n"
            "CONFIG_PACKAGE_luci-app-dockerman=y\n"
            "CONFIG_PACKAGE_luci-app-dockerman=n\n"
            "CONFIG_PACKAGE_luci-app-homeproxy=y\n",
            "CONFIG_PACKAGE_luci-app-athena-led=y\nCONFIG_PACKAGE_luci-app-homeproxy=y\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_themes_protocols_and_module_loss_are_checked(self):
        result = self.check_selection(
            "CONFIG_PACKAGE_luci-theme-argon=y\n"
            "CONFIG_PACKAGE_luci-proto-wireguard=y\n"
            "CONFIG_PACKAGE_luci-app-athena-led=m\n", "",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        for package in ("luci-theme-argon", "luci-proto-wireguard", "luci-app-athena-led"):
            self.assertIn(package, result.stderr)

    def test_feature_switches_and_non_luci_symbols_are_not_packages(self):
        result = self.check_selection(
            "CONFIG_PACKAGE_luci-app-adguardhome_INCLUDE_binary=y\n"
            "CONFIG_PACKAGE_luci-app-example_Basic_Core_All=y\n"
            "CONFIG_PACKAGE_NSS_FIRMWARE_VERSION_11_4=y\n", "",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_positive_last_override_is_checked(self):
        result = self.check_selection(
            "# CONFIG_PACKAGE_luci-app-homeproxy is not set\n"
            "CONFIG_PACKAGE_luci-app-homeproxy=y\n",
            "# CONFIG_PACKAGE_luci-app-homeproxy is not set\n",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("luci-app-homeproxy", result.stderr)

    def test_explicitly_disabled_docker_components_cannot_be_reenabled(self):
        for package in (
            "luci-app-dockerman", "luci-i18n-dockerman-zh-cn", "luci-lib-docker",
            "docker", "dockerd", "docker-compose", "containerd", "runc",
        ):
            for value in ("y", "m"):
                with self.subTest(package=package, value=value):
                    result = self.check_selection(
                        f"CONFIG_PACKAGE_{package}=n\n",
                        f"CONFIG_PACKAGE_{package}={value}\n",
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(
                        f"{package}: requested=n, resolved={value}", result.stderr,
                    )

    def test_docker_is_allowed_when_not_explicitly_disabled(self):
        for requested in (
            "",
            "CONFIG_PACKAGE_dockerd=y\n",
            "CONFIG_PACKAGE_dockerd=n\nCONFIG_PACKAGE_dockerd=y\n",
        ):
            with self.subTest(requested=requested):
                result = self.check_selection(requested, "CONFIG_PACKAGE_dockerd=y\n")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_commented_docker_disable_and_non_docker_dependencies(self):
        result = self.check_selection(
            "# CONFIG_PACKAGE_containerd is not set\n"
            "CONFIG_PACKAGE_luci-app-mosdns=n\n",
            "CONFIG_PACKAGE_containerd=m\nCONFIG_PACKAGE_luci-app-mosdns=y\n",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("containerd: requested=n, resolved=m", result.stderr)
        self.assertNotIn("luci-app-mosdns:", result.stderr)


if __name__ == "__main__":
    unittest.main()
