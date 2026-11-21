#!/usr/bin/env python3
"""Run the captured themes' real browser and Linux RPC regression harnesses."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

PACKAGES = Path(__file__).resolve().parents[1] / "wrt_core/managed/packages"


class ThemeUpstreamRepairs(unittest.TestCase):
    def node_tests(self, package, files):
        node = shutil.which("node")
        if not node:
            if os.environ.get("OPENCLASH_REQUIRE_NODE") == "1":
                self.fail("Node is required by the Linux regression gate")
            self.skipTest("Node is unavailable")
        result = subprocess.run([node, "--test", *files], cwd=PACKAGES / package,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_argon_navigation_cache_and_graph_repairs(self):
        self.node_tests("luci-theme-argon", ["tests/menu-navigation.test.js",
            "tests/browser-compat.test.js", "tests/graphs.test.js"])

    def test_aurora_navigation_replay_and_nonblocking_load(self):
        self.node_tests("luci-theme-aurora", [".dev/tests/navigation-loading.test.js",
            ".dev/tests/nav-replay.test.js"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Wallpaper RPC uses Linux flock, timeout and date")
    def test_argon_https_wallpaper_bounded_fetch_and_cache(self):
        self.node_tests("luci-theme-argon", ["tests/wallpaper-rpc.test.js"])


if __name__ == "__main__":
    unittest.main()
