#!/usr/bin/env python3
"""Exercise real feed recipes, OpenWrt metadata, and a Kconfig evaluator."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/kconfig-compat"
ADAPTER = ROOT / "wrt_core/kconfig_compat.py"
QT = "feeds/video/frameworks/qt5/qt5base"
SQUEEZE = "feeds/packages/sound/squeezelite"
FWKNOP = "feeds/packages/net/fwknop"
GNUPG2 = "feeds/packages/utils/gnupg2"
LUCIFWKNOP = "feeds/luci/applications/luci-app-fwknopd"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def stage(build):
    shutil.copytree(FIXTURE / "video", build / "feeds/video")
    shutil.copytree(FIXTURE / "packages", build / "feeds/packages")
    shutil.copytree(FIXTURE / "immortalwrt/scripts", build / "scripts")
    include = build / "include"
    include.mkdir()
    for name in ("package-defaults.mk", "package-dumpinfo.mk"):
        shutil.copy2(FIXTURE / "immortalwrt/include" / name, include / name)
    # Only compiler/toolchain setup is stubbed. Package definitions, inheritance,
    # Dumpinfo/Package, metadata.pl, and Kconfig parsing are genuine upstream code.
    write(build / "rules.mk", "")
    for name in ("host-build.mk", "nls.mk", "meson.mk"):
        write(include / name, "")
    for name in ("rust/rust-values.mk", "python/python3-host.mk"):
        write(build / "feeds/packages/lang" / name, "")
    write(include / "package.mk", """include $(INCLUDE_DIR)/package-defaults.mk
include $(INCLUDE_DIR)/package-dumpinfo.mk
define BuildPackage
$(eval $(Package/Default))
$(eval $(Package/$(1)))
$(call Dumpinfo/Package,$(1))
endef
FORCE:
""")
    write(build / "package/base/image-config.in", "")


def stage_fwknop(build, branch="master"):
    source = FIXTURE / "variants/fwknop/master"
    shutil.copytree(source / "packages", build / "feeds/packages", dirs_exist_ok=True)
    shutil.copytree(source / "luci", build / "feeds/luci", dirs_exist_ok=True)
    if branch != "master":
        variant = FIXTURE / "variants/fwknop" / branch / "packages"
        shutil.copytree(variant, build / "feeds/packages", dirs_exist_ok=True)


def command(argv, cwd, timeout=30):
    return subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def bash_path(path):
    value = Path(path).resolve().as_posix()
    return "/" + value[0].lower() + value[2:] if os.name == "nt" else value


def generate(build, group="both", legacy=True):
    make = os.environ.get("MAKE") or shutil.which("make")
    perl = shutil.which("perl")
    if not make or not perl:
        raise RuntimeError("GNU Make and Perl are required for the real metadata gate")
    packages = []
    if group in ("qt", "both"):
        packages += [QT, "feeds/video/libs/mesa", "feeds/packages/libs/libdrm"]
    if group in ("squeeze", "both"):
        packages += [SQUEEZE, "feeds/packages/multimedia/ffmpeg", "feeds/packages/libs/libx264"]
    if group == "fwknop":
        packages += [FWKNOP, GNUPG2, "feeds/packages/libs/gpgme", LUCIFWKNOP]
    if group == "gnupg2":
        packages += [GNUPG2]
    dumps = []
    for package in packages:
        relative = os.path.relpath(build, build / package).replace("\\", "/")
        result = command([make, "--no-print-directory", "-s", "DUMP=1", "TOPDIR=" + relative,
                          "INCLUDE_DIR=" + relative + "/include",
                          "__pkg_source_makefile=" + package, "dumpinfo"], build / package)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        # SOURCE is normally a build-root path supplied by Package/Default;
        # normalize it for the generated config's build-root working directory.
        output = result.stdout.replace(str((build / package).as_posix()), package)
        dumps.append("Source-Makefile: " + package + "/Makefile\n" + output)
    metadata = "\n".join(dumps)
    # All other libraries are independent leaves of this bounded reproduction.
    # Actual Mesa and ffmpeg providers, and x264's @BUILD_PATENTED, remain real.
    defined = set(re.findall(r"^Package: (\S+)", metadata, re.M))
    provided = set(" ".join(re.findall(r"^Provides: (.*)", metadata, re.M)).split())
    leaves = set()
    for deps in re.findall(r"^Depends: (.*)", metadata, re.M):
        for dependency in deps.split():
            if dependency.startswith("@"):
                continue
            name = dependency.lstrip("+").split(":")[-1]
            if name not in defined | provided:
                leaves.add(name)
    for name in sorted(leaves):
        metadata += (f"\nSource-Makefile: package/leaves/{name}/Makefile\nPackage: {name}\n"
                     f"Category: Libraries\nTitle: {name}\nType: ipkg\nDescription: leaf\n@@\n")
    write(build / "packageinfo", metadata)
    script = build / "scripts/package-metadata.pl"
    if legacy:
        write(script, script.read_text(encoding="utf-8").replace("<PACKAGE_$pkgname", "!=y"))
    result = command([perl, "scripts/package-metadata.pl", "config", "packageinfo"], build)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    # Current upstream conf renamed "option modules" to "modules"; kconfiglib
    # 14.1.0 implements the former syntax with the same MODULES semantics.
    modules = "modules" if os.environ.get("KCONFIG_CONF") else "option modules"
    prelude = f'mainmenu "Real feed compatibility regression"\nconfig MODULES\n bool\n {modules}\n default y\n'
    for name in ("ALL", "ALL_NONSHARED", "BUILD_PATENTED", "aarch64", "arm", "i386", "i686",
                 "x86_64", "mips", "mips64", "mipsel", "mips64el", "riscv64", "HAS_FPU"):
        prelude += f'config {name}\n bool "{name}"\n'
    write(build / "Kconfig", prelude + result.stdout)
    return build / "Kconfig"


def evaluate(build, selections=None):
    selections = selections or {}
    text = "".join(f"CONFIG_{name}={value}\n" for name, value in selections.items())
    write(build / "input.config", text)
    conf = os.environ.get("KCONFIG_CONF")
    if conf:
        environment = dict(os.environ, KCONFIG_CONFIG=str(build / "result.config"))
        result = subprocess.run([conf, "--fatalrecursive", "--defconfig=input.config", "Kconfig"], cwd=build,
                                env=environment, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError(result.stdout + result.stderr)
        values = dict(re.findall(r"^CONFIG_([^=]+)=(.*)$", (build / "result.config").read_text(), re.M))
        return values
    import kconfiglib
    previous = Path.cwd()
    try:
        os.chdir(build)
        config = kconfiglib.Kconfig("Kconfig", warn=False)
        config.load_config("input.config")
        return {name: symbol.str_value for name, symbol in config.syms.items()}
    finally:
        os.chdir(previous)


class KconfigCompatibility(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kconfig-compat-")
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name)
        stage(self.build)

    def prepare(self):
        self.assertTrue(ADAPTER.is_file(), "Kconfig compatibility adapter is not implemented")
        spec = importlib.util.spec_from_file_location("kconfig_compat_test", ADAPTER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.prepare(self.build)

    def test_unmodified_real_recipes_reproduce_each_cycle_after_existing_global_fix(self):
        for group, symbol in (("qt", "BUILD_qt5base-gui_OPENGL_OPENGLES2"),
                              ("squeeze", "SQUEEZELITE_WMA_ALAC")):
            with self.subTest(group=group):
                generate(self.build, group)
                with self.assertRaises(Exception) as error:
                    evaluate(self.build)
                self.assertRegex(str(error.exception), "[Dd]ependency loop|recursive dependency")
                self.assertIn(symbol, str(error.exception))

    def test_fixed_real_metadata_parses_without_enabling_unselected_packages(self):
        self.prepare()
        generate(self.build)
        values = evaluate(self.build)
        self.assertFalse({k: v for k, v in values.items() if k.startswith("PACKAGE_") and v in ("y", "m")})
        self.assertEqual(values.get("BUILD_qt5base-gui_OPENGL_NONE"), "y")
        self.assertEqual(values.get("BUILD_qt5base-gui_OPENGL_OPENGLES2", "n"), "n")
        self.assertEqual(values.get("SQUEEZELITE_WMA_ALAC", "n"), "n")

    def test_gui_opengl_choice_and_dependency_selection_are_preserved(self):
        self.prepare()
        generate(self.build)
        for mode in ("NONE", "OPENGLES2"):
            with self.subTest(mode=mode):
                values = evaluate(self.build, {"PACKAGE_qt5base-gui": "y",
                    "BUILD_qt5base-gui_OPENGL_" + mode: "y", "aarch64": "y", "HAS_FPU": "y",
                    "PACKAGE_video-support": "y"})
                self.assertEqual(values.get("PACKAGE_qt5base-gui"), "y")
                self.assertEqual(values.get("BUILD_qt5base-gui_OPENGL_" + mode), "y")
                mesa = {k: v for k, v in values.items() if k.startswith("PACKAGE_libmesa-") and v in ("y", "m")}
                self.assertEqual(bool(mesa), mode == "OPENGLES2", mesa)

    def test_squeezelite_wma_keeps_conditional_ffmpeg_and_codec_dependencies(self):
        self.prepare()
        generate(self.build)
        for enabled in ("n", "y"):
            with self.subTest(enabled=enabled):
                values = evaluate(self.build, {"PACKAGE_squeezelite-custom": "y", "BUILD_PATENTED": "y",
                    "PACKAGE_video-support": "y",
                    "SQUEEZELITE_WMA_ALAC": enabled, "FFMPEG_LIBX264": "y"})
                self.assertEqual(values.get("PACKAGE_squeezelite-custom"), "y")
                self.assertEqual(values.get("SQUEEZELITE_WMA_ALAC", "n"), enabled)
                self.assertEqual(values.get("PACKAGE_libffmpeg", "n"), enabled)
                self.assertEqual(values.get("PACKAGE_libx264", "n"), enabled)

    def test_feature_library_prerequisites_are_still_enforced(self):
        self.prepare()
        generate(self.build)
        for package, option in (("qt5base-gui", "BUILD_qt5base-gui_OPENGL_OPENGLES2"),
                                ("squeezelite-custom", "SQUEEZELITE_WMA_ALAC")):
            with self.subTest(package=package):
                values = evaluate(self.build, {"PACKAGE_" + package: "y", option: "y",
                    "PACKAGE_video-support": "n", "FFMPEG_LIBDRM": "y"})
                self.assertEqual(values.get("PACKAGE_" + package, "n"), "n")

    def test_options_alone_do_not_select_their_parent_packages_or_libraries(self):
        self.prepare()
        generate(self.build)
        values = evaluate(self.build, {"BUILD_qt5base-gui_OPENGL_OPENGLES2": "y",
            "SQUEEZELITE_WMA_ALAC": "y", "BUILD_PATENTED": "y", "aarch64": "y", "HAS_FPU": "y"})
        self.assertFalse({k: v for k, v in values.items() if k.startswith("PACKAGE_") and v in ("y", "m")})

    def test_module_selection_preserves_module_library_dependencies(self):
        self.prepare()
        generate(self.build)
        values = evaluate(self.build, {"PACKAGE_qt5base-gui": "m", "PACKAGE_squeezelite-custom": "m",
            "BUILD_qt5base-gui_OPENGL_OPENGLES2": "y", "SQUEEZELITE_WMA_ALAC": "y",
            "PACKAGE_video-support": "y", "BUILD_PATENTED": "y", "aarch64": "y"})
        for name in ("qt5base-gui", "squeezelite-custom", "libffmpeg", "libmesa-softpipe"):
            self.assertEqual(values.get("PACKAGE_" + name), "m", name)

    def snapshot(self):
        return {str(p.relative_to(self.build)): p.read_bytes() for p in self.build.rglob("*") if p.is_file()}

    def test_only_reviewed_guards_change_and_repeat_does_not_rewrite(self):
        before = self.snapshot()
        self.prepare()
        after = self.snapshot()
        changed = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed, {str(Path(QT) / "Config.in"), str(Path(SQUEEZE) / "Makefile")})
        timestamps = {p: p.stat().st_mtime_ns for p in self.build.rglob("*") if p.is_file()}
        self.prepare()
        self.assertEqual(after, self.snapshot())
        self.assertEqual(timestamps, {p: p.stat().st_mtime_ns for p in timestamps})

    def test_unknown_extra_or_missing_input_rejected_without_partial_writes(self):
        for relative in (QT + "/Config.in", QT + "/Makefile", SQUEEZE + "/Makefile"):
            path = self.build / relative
            original = path.read_bytes()
            for mutation in (original + b"\n# upstream drift\n", None):
                with self.subTest(relative=relative, missing=mutation is None):
                    if mutation is None:
                        path.unlink()
                    else:
                        path.write_bytes(mutation)
                    before = self.snapshot()
                    with self.assertRaises(ValueError):
                        self.prepare()
                    self.assertEqual(before, self.snapshot())
                    path.write_bytes(original)

    def test_recorded_upstream_blobs_and_checksums_match_fixtures(self):
        for item in json.loads((FIXTURE / "sources.json").read_text()):
            data = (FIXTURE / item["fixture"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"], item["fixture"])
            self.assertEqual(hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(), item["git_blob"])

    def test_reviewed_feed_branches_keep_versions_dependencies_and_feature_semantics(self):
        cases = (
            ("master", "2.0.0.1584", "2", True),
            ("openwrt-25.12", "2.0.0.1518", "1", False),
            ("openwrt-24.10", "1.9.9.1432", "3", False),
        )
        protected = re.compile(rb'^(?:PKG_(?:VERSION|RELEASE|SOURCE[^:]*|MIRROR_HASH)|\s*(?:DEPENDS\+?|CONFLICTS))[:+]?=.*$', re.M)
        for branch, version, release, modern_qt in cases:
            with self.subTest(branch=branch):
                for relative in (QT + "/Makefile", QT + "/Config.in", SQUEEZE + "/Makefile"):
                    source = FIXTURE / relative.removeprefix("feeds/")
                    (self.build / relative).write_bytes(source.read_bytes())
                squeeze = self.build / SQUEEZE / "Makefile"
                squeeze.write_bytes((FIXTURE / "variants" / branch / "packages/sound/squeezelite/Makefile").read_bytes())
                if modern_qt:
                    (self.build / QT / "Makefile").write_bytes((FIXTURE / "variants/master/video/frameworks/qt5/qt5base/Makefile").read_bytes())
                recipes = [self.build / QT / "Makefile", squeeze]
                before = {p: protected.findall(p.read_bytes()) for p in recipes}
                result = command([sys.executable, ADAPTER, self.build], ROOT)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"PKG_VERSION:={version}\n".encode(), squeeze.read_bytes())
                self.assertIn(f"PKG_RELEASE:={release}\n".encode(), squeeze.read_bytes())
                self.assertEqual(before, {p: protected.findall(p.read_bytes()) for p in recipes})
                generate(self.build)
                defaults = evaluate(self.build)
                self.assertFalse({k: v for k, v in defaults.items() if k.startswith("PACKAGE_") and v in ("y", "m")})
                self.assertEqual(defaults.get("BUILD_qt5base-gui_OPENGL_NONE"), "y")
                for enabled in ("n", "y"):
                    values = evaluate(self.build, {"PACKAGE_squeezelite-custom": "y",
                        "SQUEEZELITE_WMA_ALAC": enabled, "BUILD_PATENTED": "y",
                        "PACKAGE_video-support": "y", "aarch64": "y", "HAS_FPU": "y"})
                    self.assertEqual(values.get("PACKAGE_squeezelite-custom"), "y")
                    self.assertEqual(values.get("PACKAGE_libffmpeg", "n"), enabled)
                before_repeat = self.snapshot()
                mtimes = {p: p.stat().st_mtime_ns for p in recipes}
                self.prepare()
                self.assertEqual(before_repeat, self.snapshot())
                self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in recipes})

    def test_new_reviewed_branch_still_rejects_unreviewed_changes_before_writing(self):
        for branch in ("master", "openwrt-25.12", "openwrt-24.10"):
            with self.subTest(branch=branch):
                path = self.build / SQUEEZE / "Makefile"
                path.write_bytes((FIXTURE / "variants" / branch / "packages/sound/squeezelite/Makefile").read_bytes() + b"\n# unknown upstream change\n")
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "unreviewed Kconfig feed input"):
                    self.prepare()
                self.assertEqual(before, self.snapshot())

    def test_real_fwknop_luci_gnupg2_metadata_reproduces_original_cycle(self):
        stage_fwknop(self.build)
        generate(self.build, "fwknop")
        with self.assertRaises(Exception) as error:
            evaluate(self.build)
        self.assertRegex(str(error.exception), "[Dd]ependency loop|recursive dependency")
        for symbol in ("FWKNOPD_GPG", "PACKAGE_fwknopd", "PACKAGE_luci-app-fwknopd"):
            self.assertIn(symbol, str(error.exception))

    def test_fwknop_fix_keeps_parent_guards_and_optional_gpg_capture_libraries(self):
        stage_fwknop(self.build)
        unchanged = {p: p.read_bytes() for p in (
            self.build / FWKNOP / "Makefile", self.build / FWKNOP / "Config.in",
            self.build / LUCIFWKNOP / "Makefile", self.build / "feeds/luci/luci.mk")}
        self.prepare()
        self.assertEqual(unchanged, {p: p.read_bytes() for p in unchanged})
        generate(self.build, "fwknop")
        for selections in ({}, {"FWKNOPD_GPG": "y", "FWKNOPD_NFQ_CAPTURE": "y"}):
            values = evaluate(self.build, selections)
            self.assertFalse({k: v for k, v in values.items() if k.startswith("PACKAGE_") and v in ("y", "m")})
            self.assertEqual(values.get("FWKNOPD_GPG", "n"), "n")
            self.assertEqual(values.get("FWKNOPD_NFQ_CAPTURE", "n"), "n")
        defaults = evaluate(self.build, {"PACKAGE_luci-app-fwknopd": "y"})
        self.assertEqual(defaults.get("FWKNOPD_GPG", "n"), "n")
        self.assertEqual(defaults.get("FWKNOPD_NFQ_CAPTURE", "n"), "n")
        for parent in ("fwknopd", "luci-app-fwknopd"):
            for gpg in ("n", "y"):
                for capture in ("n", "y"):
                    with self.subTest(parent=parent, gpg=gpg, capture=capture):
                        values = evaluate(self.build, {"PACKAGE_" + parent: "y",
                            "FWKNOPD_GPG": gpg, "FWKNOPD_NFQ_CAPTURE": capture})
                        self.assertEqual(values.get("PACKAGE_" + parent), "y")
                        self.assertEqual(values.get("PACKAGE_fwknopd"), "y")
                        self.assertEqual(values.get("FWKNOPD_GPG", "n"), gpg)
                        self.assertEqual(values.get("FWKNOPD_NFQ_CAPTURE", "n"), capture)
                        for library in ("gnupg2", "gnupg2-utils", "libgpgme"):
                            self.assertEqual(values.get("PACKAGE_" + library, "n"), gpg, library)
                        for library in ("iptables-mod-nfqueue", "libnetfilter-queue", "libnfnetlink"):
                            self.assertEqual(values.get("PACKAGE_" + library, "n"), capture, library)
                        self.assertEqual(values.get("PACKAGE_libpcap", "n"), "y" if capture == "n" else "n")
        values = evaluate(self.build, {"PACKAGE_luci-app-fwknopd": "m", "FWKNOPD_GPG": "y"})
        for package in ("luci-app-fwknopd", "fwknopd", "libfko", "gnupg2-utils", "libgpgme"):
            self.assertEqual(values.get("PACKAGE_" + package), "m", package)
        # The original option's menu guard caps its runtime selection at m.
        self.assertEqual(values.get("PACKAGE_gnupg2"), "m")

    def test_reviewed_gnupg2_branches_select_required_runtime_and_repeat_without_rewrite(self):
        for branch in ("master", "current-master", "openwrt-25.12", "openwrt-24.10"):
            with self.subTest(branch=branch):
                stage_fwknop(self.build, branch)
                self.prepare()
                generate(self.build, "gnupg2")
                values = evaluate(self.build)
                self.assertFalse({k: v for k, v in values.items() if k.startswith("PACKAGE_") and v in ("y", "m")})
                for selected in ("y", "m"):
                    values = evaluate(self.build, {"PACKAGE_gnupg2-utils": selected})
                    self.assertEqual(values.get("PACKAGE_gnupg2-utils"), selected)
                    self.assertEqual(values.get("PACKAGE_gnupg2"), selected)
                path = self.build / GNUPG2 / "Makefile"
                before, mtime = path.read_bytes(), path.stat().st_mtime_ns
                self.prepare()
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_unknown_or_missing_gnupg2_input_is_rejected_before_other_adaptations(self):
        stage_fwknop(self.build)
        path = self.build / GNUPG2 / "Makefile"
        original = path.read_bytes()
        for contents in (original + b"\n# unreviewed GnuPG2 drift\n", None):
            with self.subTest(missing=contents is None):
                if contents is None:
                    path.unlink()
                else:
                    path.write_bytes(contents)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "Kconfig"):
                    self.prepare()
                self.assertEqual(before, self.snapshot())
                path.write_bytes(original)

    def test_current_qt_linuxfb_drm_keeps_library_selection_without_parent_cycle(self):
        (self.build / QT / "Makefile").write_bytes((FIXTURE / "variants/master/video/frameworks/qt5/qt5base/Makefile").read_bytes())
        self.prepare()
        generate(self.build, "qt")
        for enabled in ("n", "y"):
            try:
                values = evaluate(self.build, {"PACKAGE_qt5base-plugin-platforms-linuxfb": "y",
                    "PACKAGE_qt5base-gui": "y", "BUILD_qt5base-gui_DRM": enabled,
                    "PACKAGE_video-support": "y", "aarch64": "y", "HAS_FPU": "y"})
            except Exception as error:
                self.fail("Reviewed Qt linuxfb/DRM metadata must parse: " + str(error).split("\n")[1])
            self.assertEqual(values.get("PACKAGE_qt5base-plugin-platforms-linuxfb"), "y")
            self.assertEqual(values.get("BUILD_qt5base-gui_DRM", "n"), enabled)
            self.assertEqual(values.get("PACKAGE_libdrm", "n"), enabled)

    def test_partial_existing_edit_is_rejected_without_writes(self):
        path = self.build / SQUEEZE / "Makefile"
        path.write_bytes(path.read_bytes().replace(b'\tif PACKAGE_squeezelite-custom\n',
                                                  b'\tmenu "Squeezelite custom options"\n'))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(before, self.snapshot())

    def test_second_replace_failure_rolls_back_first_file(self):
        before = self.snapshot()
        real_replace = os.replace
        calls = []
        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("injected second-file replacement failure")
            real_replace(source, destination)
        with mock.patch("os.replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second-file"):
                self.prepare()
        self.assertEqual(len(calls), 2)
        self.assertEqual(before, self.snapshot())

    def test_cli_reports_drift_and_keeps_all_inputs_unchanged(self):
        result = command([sys.executable, ADAPTER, self.build], ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = self.build / QT / "Makefile"
        path.write_bytes(path.read_bytes() + b"\nPKG_RELEASE:=99\n")
        before = self.snapshot()
        result = command([sys.executable, ADAPTER, self.build], ROOT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreviewed Kconfig feed input", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_absent_packages_are_optional_but_present_package_is_adapted(self):
        shutil.rmtree(self.build / QT)
        self.prepare()
        self.assertIn(b'\tmenu "Squeezelite custom options"\n',
                      (self.build / SQUEEZE / "Makefile").read_bytes())
        shutil.rmtree(self.build / SQUEEZE)
        before = self.snapshot()
        self.prepare()
        self.assertEqual(before, self.snapshot())

    def test_absent_squeezelite_does_not_block_qt_adaptation(self):
        shutil.rmtree(self.build / SQUEEZE)
        self.prepare()
        self.assertNotIn(b'default BUILD_qt5base-gui_OPENGL_NONE\n    depends on',
                         (self.build / QT / "Config.in").read_bytes())

    def test_real_hook_and_stage_propagate_failure_inside_if_without_errexit(self):
        # An if-condition suppresses Bash errexit inside functions. This checks
        # the real hook/stage return contract, with unrelated hooks isolated.
        script = r'''set -uo pipefail
source "$BASE_PATH/update.sh"
while read -r _ _ name; do
    case "$name" in
        fix_kconfig_recursive_dependency|stage_pre_install_source_fixes) ;;
        *) eval "$name() { :; }" ;;
    esac
done < <(declare -F)
python3() {
    case "$1" in
        */kconfig_compat.py) "$TEST_PYTHON" "$@" ;;
        *) : ;;
    esac
}
if "$TARGET_HOOK"; then
    touch "$BUILD_DIR/after-kconfig"
else
    exit 41
fi
'''
        bash = os.environ.get("BASH") or shutil.which("bash")
        self.assertTrue(bash, "Bash is required for the production-stage regression")
        recipe = self.build / QT / "Makefile"
        original = recipe.read_bytes()
        for hook in ("fix_kconfig_recursive_dependency", "stage_pre_install_source_fixes"):
            with self.subTest(hook=hook):
                environment = dict(os.environ, BASE_PATH=bash_path(ROOT / "wrt_core"),
                    BUILD_DIR=bash_path(self.build), TEST_PYTHON=Path(sys.executable).as_posix(),
                    TARGET_HOOK=hook)
                result = subprocess.run([bash, "--noprofile", "--norc", "-c", script],
                    cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                marker = self.build / "after-kconfig"
                self.assertTrue(marker.is_file())
                marker.unlink()
                self.assertIn(b'\tmenu "Squeezelite custom options"\n',
                              (self.build / SQUEEZE / "Makefile").read_bytes())
                recipe.write_bytes(original + b"\n# upstream drift\n")
                before = self.snapshot()
                result = subprocess.run([bash, "--noprofile", "--norc", "-c", script],
                    cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual(before, self.snapshot())
                recipe.write_bytes(original)

    def test_metadata_sed_failure_stops_hook_before_either_package_is_modified(self):
        script = r'''set -uo pipefail
source "$BASE_PATH/modules/target_fixes.sh"
python3() { "$TEST_PYTHON" "$@"; }
sed() { return 55; }
if fix_kconfig_recursive_dependency; then
    exit 0
else
    exit 41
fi
'''
        bash = os.environ.get("BASH") or shutil.which("bash")
        self.assertTrue(bash, "Bash is required for the production-stage regression")
        environment = dict(os.environ, BASE_PATH=bash_path(ROOT / "wrt_core"),
            BUILD_DIR=bash_path(self.build), TEST_PYTHON=Path(sys.executable).as_posix())
        before = self.snapshot()
        result = subprocess.run([bash, "--noprofile", "--norc", "-c", script], cwd=ROOT,
            env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
