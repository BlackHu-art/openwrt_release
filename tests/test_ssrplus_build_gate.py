#!/usr/bin/env python3
"""Exercise selected SSR configuration and package/rootfs collection gates."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import test_ssrplus_artifacts as artifacts
import test_ssrplus_runtime_regressions as runtime_cases

ROOT = artifacts.ROOT
REQUIRED = ("CONFIG_PACKAGE_firewall4", "CONFIG_PACKAGE_dnsmasq-full",
            "CONFIG_PACKAGE_dnsmasq_full_nftset", "CONFIG_PACKAGE_flock",
            "CONFIG_PACKAGE_luci-app-ssr-plus_Nftables_Transparent_Proxy")


class BuildGate(unittest.TestCase):
    def setUp(self):
        self.case = artifacts.ArtifactVerification()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.base = self.case.base
        self.env = os.environ.copy()
        self.env.pop("MSYS_NO_PATHCONV", None)
        self.env.update(TEST_ROOT=self.base.as_posix(),
                        SSR_BUILD_MODULE=(ROOT / "wrt_core/modules/ssrplus_build.sh").as_posix())

    def config(self, selected="m", missing=None, per_device=False, device_ssr=False):
        lines = ["CONFIG_PACKAGE_luci-app-ssr-plus=" + selected]
        lines += [key + "=y" for key in REQUIRED if key != missing]
        if per_device:
            lines.append("CONFIG_TARGET_PER_DEVICE_ROOTFS=y")
        if device_ssr:
            lines += ["CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_fixture=y",
                      'CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq60xx_DEVICE_fixture="luci-app-ssr-plus"']
        (self.base / ".config").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def prepare_artifacts(self):
        target = self.base / "bin/packages/test/luci/luci-app-ssr-plus_190-9_all.ipk"
        target.parent.mkdir(parents=True)
        self.case.make_package().replace(target)
        expected = self.base / "feeds/custom_feed/luci-app-ssr-plus/root" / artifacts.MANIFEST_TARGET
        expected.parent.mkdir(parents=True)
        expected.write_bytes(self.case.expected.read_bytes())

    def install_root(self, relative):
        target = self.base / relative
        shutil.copytree(self.case.root, target)
        return target

    def shell(self, body):
        return subprocess.run([runtime_cases.BASH, "--noprofile", "--norc", "-c",
            '. "$SSR_BUILD_MODULE" || exit; cd "$TEST_ROOT" || exit; ' + body],
            env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)

    def source_fixture(self):
        package = self.base / "source/luci-app-ssr-plus"
        table = ROOT / "wrt_core/compat/ssrplus/source-files.tsv"
        for entry in table.read_text(encoding="utf-8").splitlines():
            _, relative, fixture = entry.split()
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "tests/fixtures" / fixture, target)
        # Real upstream packages already carry this generator, including r4-r8;
        # test its protection even before the source table learns about it.
        generator = package / "root/usr/share/shadowsocksr/gen_config.lua"
        generator.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tests/fixtures/ssrplus/2abdc9aa/gen_config.lua", generator)
        self.env.update(BASE_PATH=(ROOT / "wrt_core").as_posix(),
                        SSR_SOURCE_PACKAGE=package.as_posix())
        return package

    def prepare_source(self):
        return self.shell('. "$BASE_PATH/modules/plugin_compat.sh" && '
                          'fix_ssrplus_compat "$SSR_SOURCE_PACKAGE"')

    def test_source_preparation_embeds_r9_identity_with_matching_recipe_release(self):
        package = self.source_fixture()
        result = self.prepare_source()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((package / "root" / artifacts.MANIFEST_TARGET).read_text(encoding="utf-8"))
        self.assertEqual(manifest["repair_version"], "190-r9")
        self.assertEqual(len(manifest["patches"]), 21)
        self.assertIn("ssrplus-transport-config.patch", manifest["patches"])
        self.assertIn("PKG_RELEASE:=9\n", (package / "Makefile").read_text(encoding="utf-8"))

    def test_source_preparation_rejects_changed_generator_before_publishing(self):
        package = self.source_fixture()
        generator = package / "root/usr/share/shadowsocksr/gen_config.lua"
        generator.write_bytes(generator.read_bytes() + b"\n-- unreviewed generator change\n")
        before = {path.relative_to(package): path.read_bytes()
                  for path in package.rglob("*") if path.is_file()}
        result = self.prepare_source()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("gen_config.lua", result.stderr)
        after = {path.relative_to(package): path.read_bytes()
                 for path in package.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_rootfs_rejects_changed_generator_against_prepared_source_manifest(self):
        package = self.source_fixture()
        result = self.prepare_source()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        source_root = package / "root"
        embedded = source_root / artifacts.MANIFEST_TARGET
        manifest = json.loads(embedded.read_text(encoding="utf-8"))
        if os.name == "nt":
            # Windows cannot represent installed POSIX modes. Keep the actual
            # source digests, but adapt this byte-tamper probe's modes to the
            # host. Linux runs the unmodified 0755/0644 source policy.
            for relative, attributes in manifest["files"].items():
                target = source_root / relative.lstrip("/")
                attributes["mode"] = f"{stat.S_IMODE(target.stat().st_mode):04o}"
            embedded.write_text(json.dumps(manifest), encoding="utf-8")
        trusted = self.base / "prepared-source-manifest.json"
        trusted.write_bytes(embedded.read_bytes())
        arguments = [sys.executable, str(ROOT / "wrt_core/ssrplus_verify.py"),
                     "rootfs", "--manifest", str(trusted), "--root", str(source_root)]
        original = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        self.assertEqual(original.returncode, 0, original.stdout + original.stderr)
        generator = source_root / "usr/share/shadowsocksr/gen_config.lua"
        generator.write_bytes(generator.read_bytes() + b"\n-- stale compiled generator\n")
        changed = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(changed.returncode, 0, changed.stdout + changed.stderr)
        self.assertIn("gen_config.lua", changed.stderr)

    def test_unselected_ssr_does_not_require_other_plugins_backend(self):
        self.config(selected="n")
        result = self.shell("verify_ssrplus_final_config .config && verify_ssrplus_built_artifacts")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_selected_ssr_accepts_nft_dnsmasq_and_flock(self):
        self.config()
        result = self.shell("verify_ssrplus_final_config .config")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_missing_dependency_fails_before_compilation(self):
        for key in REQUIRED:
            with self.subTest(key=key):
                self.config(missing=key)
                self.assertNotEqual(self.shell("verify_ssrplus_final_config .config").returncode, 0)

    def test_compiled_module_package_verified_without_requiring_rootfs_install(self):
        self.config()
        target = self.base / "bin/packages/test/luci/luci-app-ssr-plus_190-9_all.ipk"
        target.parent.mkdir(parents=True)
        self.case.make_package().replace(target)
        expected = self.base / "feeds/custom_feed/luci-app-ssr-plus/root" / artifacts.MANIFEST_TARGET
        expected.parent.mkdir(parents=True)
        expected.write_bytes(self.case.expected.read_bytes())
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compiled_r8_package_cannot_pass_with_r9_payload_and_manifest(self):
        self.config()
        self.prepare_artifacts()
        target = self.base / "bin/packages/test/luci/luci-app-ssr-plus_190-9_all.ipk"
        for version in ("190-7", "190-r7", "190-8", "190-r8"):
            with self.subTest(version=version):
                self.case.make_package(version=version).replace(target)
                result = self.shell("verify_ssrplus_built_artifacts")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("compiled package version mismatch", result.stderr)

    def test_selected_rootfs_package_cannot_pass_without_final_rootfs(self):
        self.config(selected="y")
        target = self.base / "bin/packages/test/luci/luci-app-ssr-plus_190-9_all.ipk"
        target.parent.mkdir(parents=True)
        self.case.make_package().replace(target)
        expected = self.base / "feeds/custom_feed/luci-app-ssr-plus/root" / artifacts.MANIFEST_TARGET
        expected.parent.mkdir(parents=True)
        expected.write_bytes(self.case.expected.read_bytes())
        self.assertNotEqual(self.shell("verify_ssrplus_built_artifacts").returncode, 0)

    def test_missing_package_and_manifest_fail_closed(self):
        self.config()
        self.assertNotEqual(self.shell("verify_ssrplus_built_artifacts").returncode, 0)

    def test_per_device_build_cannot_pass_with_only_the_common_root(self):
        self.config(selected="y", per_device=True)
        self.prepare_artifacts()
        self.install_root("build_dir/target-fixture/root-qualcommax")
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_final_per_device_root_requires_intact_repair_files(self):
        self.config(selected="y", per_device=True)
        self.prepare_artifacts()
        self.install_root("build_dir/target-fixture/root-qualcommax")
        self.install_root("build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-12345678")
        other = self.install_root("build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-deadbeef")
        protected = other / artifacts.PROTECTED
        for damage in ("missing", "changed"):
            with self.subTest(damage=damage):
                if damage == "missing":
                    protected.unlink()
                else:
                    protected.write_bytes(b"unrepaired device payload\n")
                result = self.shell("verify_ssrplus_built_artifacts")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_per_device_roots_ignore_temporary_and_non_target_trees(self):
        self.config(selected="y", per_device=True)
        self.prepare_artifacts()
        self.install_root("build_dir/target-fixture/root-qualcommax")
        for suffix in ("12345678", "deadbeef"):
            self.install_root("build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-" + suffix)
        for relative in ("build_dir/target-fixture/linux-qualcommax_ipq60xx/tmp/target-dir-aabbccdd",
                         "build_dir/target-fixture/work/target-dir-aabbccdd",
                         "build_dir/host/linux-qualcommax_ipq60xx/target-dir-aabbccdd",
                         "build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-aabbccdd.work"):
            (self.base / relative).mkdir(parents=True)
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_module_selected_by_device_requires_an_installed_final_root(self):
        self.config(per_device=True, device_ssr=True)
        self.prepare_artifacts()
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.base / "build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-deadbeef").mkdir(parents=True)
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_module_selected_by_device_checks_its_repair_payload(self):
        self.config(per_device=True, device_ssr=True)
        self.prepare_artifacts()
        root = self.install_root("build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-deadbeef")
        (root / artifacts.PROTECTED).write_bytes(b"unrepaired device payload\n")
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_module_selected_by_device_allows_other_devices_without_ssr(self):
        self.config(per_device=True, device_ssr=True)
        self.prepare_artifacts()
        self.install_root("build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-deadbeef")
        (self.base / "build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-aabbccdd").mkdir(parents=True)
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plain_module_build_with_per_device_support_does_not_require_roots(self):
        self.config(per_device=True)
        self.prepare_artifacts()
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unselected_device_or_negative_package_does_not_require_ssr_roots(self):
        self.prepare_artifacts()
        for selection, packages in (("n", "luci-app-ssr-plus"), ("y", "-luci-app-ssr-plus")):
            with self.subTest(selection=selection, packages=packages):
                self.config(per_device=True)
                with (self.base / ".config").open("a", encoding="utf-8") as config:
                    config.write("CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_fixture=" + selection + "\n")
                    config.write('CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq60xx_DEVICE_fixture="' + packages + '"\n')
                result = self.shell("verify_ssrplus_built_artifacts")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_device_package_metadata_cannot_hide_missing_repair_payload(self):
        self.config(per_device=True, device_ssr=True)
        self.prepare_artifacts()
        root = self.base / "build_dir/target-fixture/linux-qualcommax_ipq60xx/target-dir-deadbeef"
        status = root / "usr/lib/opkg/status"
        status.parent.mkdir(parents=True)
        status.write_text("Package: luci-app-ssr-plus\nVersion: 190-9\n", encoding="utf-8")
        result = self.shell("verify_ssrplus_built_artifacts")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
