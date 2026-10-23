#!/usr/bin/env python3
"""Run real Aurora/Argon defaults on fresh and retained UCI configurations."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "wrt_core/managed/packages"
BASH = os.environ.get("BASH") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
HELPER = ROOT / "wrt_core/theme_compat.py"


def options(text):
    result, section, index = {}, None, 0
    for line in text.splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            continue
        if words[0] == "config":
            section = words[2] if len(words) > 2 else "cfg" + str(index)
            index += 1
        elif words[0] in ("option", "list"):
            key = (section, words[1])
            if words[0] == "list":
                result.setdefault(key, []).append(words[2])
            else:
                result[key] = words[2] if len(words) > 2 else ""
    return result


class ThemePreservation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="theme-preservation-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        shutil.copytree(RAW / "luci-app-aurora-config", self.package)
        if HELPER.exists() and os.environ.get("THEME_FIX_MODE") != "original":
            specification = importlib.util.spec_from_file_location("theme_compat", HELPER)
            self.helper = importlib.util.module_from_spec(specification)
            specification.loader.exec_module(self.helper)
            self.helper.prepare_aurora_config(self.package)
        self.runtime = self.root / "runtime"
        (self.runtime / "etc/config").mkdir(parents=True)
        shutil.copytree(self.package / "root/usr/share/aurora", self.runtime / "usr/share/aurora")

    def run_defaults(self, source, package="aurora"):
        source = source.replace("/etc/config/", (self.runtime / "etc/config").as_posix() + "/")
        source = source.replace("/usr/share/aurora/", (self.runtime / "usr/share/aurora").as_posix() + "/")
        source = source.replace("/etc/argon-config-migration", (self.runtime / "etc/argon-config-migration").as_posix())
        mock = (ROOT / "tests/fixtures/themes/uci.sh").read_text(encoding="utf-8")
        environment = os.environ.copy()
        environment.update(TEST_CONFIG_DIR=(self.runtime / "etc/config").as_posix(), PKG_UPGRADE="1")
        result = subprocess.run([BASH, "-s"], input=mock + "\nlogger() { :; }\n" + source, env=environment, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return (self.runtime / "etc/config" / package).read_text(encoding="utf-8")

    def aurora_source(self):
        return (self.package / "root/etc/uci-defaults/80_aurora").read_text(encoding="utf-8")

    def existing(self, schema):
        version = "" if schema is None else f" option config_version '{schema}'\n"
        return ("# user configuration retained by package/sysupgrade\nconfig aurora 'theme'\n" + version +
                " option struct_font_sans 'User Font'\n option logo_svg '/user-logo.png'\n option toolbar_enabled '0'\n"
                " option light_brand '#123456'\n option dark_brand '#fedcba'\n option unknown_setting 'keep-me'\n"
                " option light_canvas '#f0e0d0'\n option light_content '#201010'\n"
                "config toolbar_item\n option title 'User tool'\n option url '/custom'\n option enabled '0'\n"
                "config extension 'user_extension'\n option value 'retained'\n list items 'first'\n list items 'second'\n")

    def test_aurora_old_and_missing_schema_preserve_all_user_values_and_fill_defaults(self):
        config = self.runtime / "etc/config/aurora"
        for schema in ("1", "3", "6", None):
            with self.subTest(schema=schema):
                original = self.existing(schema)
                config.write_text(original, encoding="utf-8")
                result = self.run_defaults(self.aurora_source())
                actual = options(result)
                for key, value in options(original).items():
                    if key != ("theme", "config_version"):
                        self.assertEqual(actual.get(key), value, "initializer replaced a retained user value: " + str(key))
                self.assertEqual(actual[("theme", "config_version")], "7")
                self.assertEqual(actual[("theme", "light_bg")], "#f0e0d0")
                self.assertEqual(actual[("theme", "light_text")], "#201010")
                self.assertEqual(actual[("theme", "light_surface")], "#fff")
                after = config.read_bytes()
                self.run_defaults(self.aurora_source())
                self.assertEqual(config.read_bytes(), after, "repeat initialization changed retained configuration")

    def test_aurora_fresh_matches_template_and_repeated_init_preserves_it(self):
        result = self.run_defaults(self.aurora_source())
        actual = options(result)
        template = options((self.runtime / "usr/share/aurora/default.template").read_text(encoding="utf-8"))
        self.assertEqual({key: value for key, value in actual.items() if key != ("theme", "config_version")}, template)
        self.assertEqual(actual[("theme", "config_version")], "7")
        config = self.runtime / "etc/config/aurora"
        before = config.read_bytes()
        self.run_defaults(self.aurora_source())
        self.assertEqual(config.read_bytes(), before)

    def test_aurora_same_unknown_and_future_schema_remain_byte_identical(self):
        config = self.runtime / "etc/config/aurora"
        for schema in ("7", "8", "99", "future-custom"):
            with self.subTest(schema=schema):
                config.write_text(self.existing(schema), encoding="utf-8")
                before = config.read_bytes()
                self.run_defaults(self.aurora_source())
                self.assertEqual(config.read_bytes(), before)

    def test_aurora_renamed_structure_keeps_old_value_and_explicit_replacements_win(self):
        config = self.runtime / "etc/config/aurora"
        original = ("config aurora 'theme'\n option config_version '6'\n"
                    " option struct_container_max_width '64rem'\n"
                    " option light_canvas '#aaaaaa'\n option light_bg '#bbbbbb'\n"
                    " option light_content '#111111'\n option light_text '#222222'\n")
        config.write_text(original, encoding="utf-8")
        actual = options(self.run_defaults(self.aurora_source()))
        for key, value in options(original).items():
            if key != ("theme", "config_version"):
                self.assertEqual(actual.get(key), value)
        self.assertEqual(actual[("theme", "struct_content_width_centered")], "64rem")

    def test_preparation_is_idempotent_rejects_drift_and_never_mutates_managed_source(self):
        if not hasattr(self, "helper"):
            self.skipTest("source reproduction omits the build-copy preparation helper")
        initializer = self.package / "root/etc/uci-defaults/80_aurora"
        prepared = initializer.read_bytes()
        self.helper.prepare_aurora_config(self.package)
        self.assertEqual(initializer.read_bytes(), prepared)
        changed = prepared.replace(b"readonly SCHEMA_VERSION=\"7\"", b"readonly SCHEMA_VERSION=\"unreviewed\"")
        initializer.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "unreviewed or partial"):
            self.helper.prepare_aurora_config(self.package)
        self.assertEqual(initializer.read_bytes(), changed)
        raw = RAW / "luci-app-aurora-config/root/etc/uci-defaults/80_aurora"
        before = raw.read_bytes()
        with self.assertRaisesRegex(ValueError, "separate build copy"):
            self.helper.prepare_aurora_config(RAW / "luci-app-aurora-config")
        self.assertEqual(raw.read_bytes(), before)

    def test_argon_repository_defaults_fill_missing_only(self):
        source = (ROOT / "wrt_core/patches/990_set_argon_primary").read_text(encoding="utf-8")
        config = self.runtime / "etc/config/argon"
        for value in ("0", "0.8", ""):
            with self.subTest(value=value):
                config.write_text("config global 'settings'\n option primary '#123abc'\n option transparency '" + value + "'\n option unknown 'retained'\n", encoding="utf-8")
                result = options(self.run_defaults(source, "argon"))
                self.assertEqual(result[("settings", "primary")], "#123abc")
                self.assertEqual(result[("settings", "transparency")], value)
                self.assertEqual(result[("settings", "unknown")], "retained")
        config.write_text("config global 'settings'\n option primary '#112233'\n", encoding="utf-8")
        result = options(self.run_defaults(source, "argon"))
        self.assertEqual(result[("settings", "primary")], "#112233")
        self.assertEqual(result[("settings", "transparency")], "0.3")
        config.unlink()
        result = options(self.run_defaults(source, "argon"))
        self.assertIn("#6A89CC", result.values())
        self.assertIn("0.3", result.values())

    def test_argon_retained_package_defaults_then_repository_defaults_preserve_choices(self):
        config = self.runtime / "etc/config/argon"
        config.write_text("config global 'global'\n option primary '#aabbcc'\n option transparency '0'\n option online_wallpaper 'custom'\n option custom_logo '/user.svg'\n", encoding="utf-8")
        upstream = (RAW / "luci-theme-argon/root/etc/uci-defaults/30_luci-theme-argon").read_text(encoding="utf-8")
        self.run_defaults(upstream, "argon")
        self.run_defaults((ROOT / "wrt_core/patches/990_set_argon_primary").read_text(encoding="utf-8"), "argon")
        actual = options(config.read_text(encoding="utf-8"))
        self.assertEqual(actual[("global", "primary")], "#aabbcc")
        self.assertEqual(actual[("global", "transparency")], "0")
        self.assertEqual(actual[("global", "online_wallpaper")], "custom")
        self.assertEqual(actual[("global", "custom_logo")], "/user.svg")

    def test_argon_fresh_packaged_defaults_remain_present_through_both_initializers(self):
        config = self.runtime / "etc/config/argon"
        packaged = (RAW / "luci-theme-argon/root/etc/config/argon").read_text(encoding="utf-8")
        config.write_text(packaged, encoding="utf-8")
        original = options(packaged)
        self.run_defaults((RAW / "luci-theme-argon/root/etc/uci-defaults/30_luci-theme-argon").read_text(encoding="utf-8"), "argon")
        self.run_defaults((ROOT / "wrt_core/patches/990_set_argon_primary").read_text(encoding="utf-8"), "argon")
        actual = options(config.read_text(encoding="utf-8"))
        for key, value in original.items():
            self.assertEqual(actual.get(key), value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
