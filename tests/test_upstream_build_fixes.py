#!/usr/bin/env python3
"""Exercise upstream build repairs at their real shell/Git boundaries."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("BASH") or shutil.which("bash")


class UpstreamBuildFixes(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="upstream-build-fixes-")
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name)

    def shell(self, source, *arguments):
        environment = dict(os.environ, BUILD_DIR=self.build.as_posix(),
                           BASE_PATH=(ROOT / "wrt_core").as_posix())
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", source, "upstream-fix", *map(str, arguments)],
                              cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)

    def test_direct_iptables_dependency_is_gated_for_new_kernels_and_repeat_is_stable(self):
        include = self.build / "include/netfilter.mk"
        include.parent.mkdir()
        include.write_text("\n".join((
            "CONFIG_IP_NF_IPTABLES_LEGACY, $(P_V4)ip_tables, ge 6.12",
            "CONFIG_IP6_NF_IPTABLES_LEGACY, $(P_V6)ip6_tables, ge 6.12",
            "CONFIG_IP_NF_IPTABLES_LEGACY, xt_standard ipt_icmp xt_tcp xt_udp xt_comment xt_set xt_SET, ge 6.12",
            "CONFIG_IP6_NF_IPTABLES_LEGACY, ip6t_icmp6, ge 6.12",
        )) + "\n")
        recipe = self.build / "package/kernel/linux/modules/netfilter.mk"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("define KernelPackage/ipt-nat\n  DEPENDS:=+kmod-iptables +kmod-nf-nat\nendef\n")
        script = 'source "$BASE_PATH/modules/service_fixes.sh"; fix_netfilter_kmod_clash'
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DEPENDS:=+(!(LINUX_6_12||LINUX_6_18)):kmod-iptables +kmod-nf-nat", recipe.read_text())
        before = recipe.read_bytes()
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, recipe.read_bytes())

    def test_airoha_root_recipe_is_unique_and_uses_the_installed_luci_feed(self):
        package = self.build / "luci-app-airoha-npu"
        nested = package / "luci-app-airoha-npu"
        nested.mkdir(parents=True)
        (package / "Makefile").write_text("LUCI_TITLE:=Airoha NPU\ninclude ../../luci.mk\n")
        (nested / "Makefile").write_text("LUCI_TITLE:=Duplicate Airoha NPU\ninclude ../../luci.mk\n")
        script = ('source "$BASE_PATH/modules/custom_feed.sh"; '
                  'remove_nested_airoha_npu_package "$1" && fix_airoha_npu_luci_mk "$1"')
        result = self.shell(script, package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.relative_to(package).as_posix() for p in package.rglob("Makefile")], ["Makefile"])
        self.assertEqual((package / "Makefile").read_text(),
                         "LUCI_TITLE:=Airoha NPU\ninclude $(TOPDIR)/feeds/luci/luci.mk\n")
        before = (package / "Makefile").read_bytes()
        result = self.shell(script, package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, (package / "Makefile").read_bytes())

    def test_pinned_root_package_fetch_uses_reviewed_commit_after_remote_advances(self):
        writer = self.build / "writer"
        writer.mkdir()
        def git(*arguments):
            return subprocess.run(["git", "-C", str(writer), *arguments], capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Source fixture")
        git("config", "user.email", "source-fixture@example.invalid")
        (writer / "Makefile").write_text("LUCI_TITLE:=Reviewed package\n")
        git("add", ".")
        git("commit", "-qm", "reviewed")
        reviewed = git("rev-parse", "HEAD")
        (writer / "Makefile").write_text("LUCI_TITLE:=Unreviewed newer package\n")
        git("commit", "-qam", "newer")
        target = self.build / "custom_feed"
        target.mkdir()
        script = ('source "$BASE_PATH/modules/custom_feed.sh"; git_retry() { git "$@"; }; '
                  'sync_repo_root_package_to_feed_dir "$1" main "$2" fixture luci-app-airoha-npu "$3"')
        result = self.shell(script, writer.as_uri(), target, reviewed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((target / "luci-app-airoha-npu/Makefile").read_text(), "LUCI_TITLE:=Reviewed package\n")
        self.assertFalse((target / "luci-app-airoha-npu/.git").exists())

    def test_local_feed_registration_creates_link_before_index_only_update(self):
        custom = self.build / 'custom_feed'
        custom.mkdir()
        conf = self.build / 'feeds.conf.default'
        conf.write_text('')
        script = ('source "$BASE_PATH/modules/custom_feed.sh"; '
                  'register_local_feed_source "$1" "$2"')
        result = self.shell(script, custom, conf)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        link = self.build / 'feeds/custom_feed'
        self.assertTrue(link.is_symlink(), 'index-only updates do not create src-link checkouts')
        self.assertEqual(link.resolve(), custom.resolve())
        result = self.shell(script, custom, conf)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(conf.read_text().count('src-link custom_feed '), 1)


if __name__ == "__main__":
    unittest.main()
