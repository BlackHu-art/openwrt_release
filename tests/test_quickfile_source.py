#!/usr/bin/env python3
"""Prevent reintroducing the obsolete prebuilt QuickFile install rewrite."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_passwall2_tls as shell

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "tests/fixtures/quickfile/13f1a61/quickfile/Makefile"
VERIFIER = ROOT / "wrt_core/quickfile_verify.py"


class QuickFileSource(unittest.TestCase):
    def test_modern_recipe_accepts_target_rust_output_and_preserves_bytes(self):
        spec = importlib.util.spec_from_file_location("quickfile_verify", VERIFIER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        recipe = ORIGINAL.read_bytes()
        module.verify_recipe(recipe.decode("utf-8"))
        self.assertEqual(recipe, ORIGINAL.read_bytes())
        for bad in (
            recipe.replace(b"$(PKG_INSTALL_DIR)/bin/quickfile", b"$(PKG_BUILD_DIR)/quickfile-$(ARCH_PACKAGES)"),
            recipe.replace(b"PKG_BUILD_DEPENDS:=rust/host", b"PKG_BUILD_DEPENDS:="),
            recipe.replace(b"PKG_HASH:=055966", b"PKG_HASH:=unknown055966"),
        ):
            with self.subTest(recipe=bad), self.assertRaises(ValueError):
                module.verify_recipe(bad.decode("utf-8"))

    def test_real_updater_preserves_target_recipe_on_x86_and_arm64_and_rejects_old_source(self):
        for architecture in ("x86_64", "aarch64_cortex-a53"):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory(prefix="quickfile-source-") as tmp:
                root = Path(tmp)
                source = root / "upstream/quickfile"
                source.mkdir(parents=True)
                (source / "Makefile").write_bytes(ORIGINAL.read_bytes())
                env = dict(os.environ, BASE_PATH=shell.bash_path(ROOT / "wrt_core"),
                           BUILD_DIR=shell.bash_path(root / "build"),
                           TEST_SOURCE=shell.bash_path(source.parent),
                           TEST_PYTHON=Path(sys.executable).as_posix(), ARCH_PACKAGES=architecture)
                script = '''set -euo pipefail
source "$BASE_PATH/modules/package_source_updates.sh"
python3() { "$TEST_PYTHON" "$@"; }
git_retry() { mkdir -p "${!#}"; cp -R "$TEST_SOURCE/." "${!#}/"; }
mkdir -p "$BUILD_DIR/package/emortal/quickfile"
add_quickfile
cmp "$TEST_SOURCE/quickfile/Makefile" "$BUILD_DIR/package/emortal/quickfile/quickfile/Makefile"
printf 'existing source' > "$BUILD_DIR/package/emortal/quickfile/keep"
printf 'prebuilt unreviewed recipe' > "$TEST_SOURCE/quickfile/Makefile"
if add_quickfile; then echo 'unrecognized recipe accepted' >&2; exit 11; fi
test "$(cat "$BUILD_DIR/package/emortal/quickfile/keep")" = 'existing source'
'''
                result = subprocess.run([shell.bash_executable(), "--noprofile", "--norc", "-c", script],
                                        env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pre_install_stage_propagates_quickfile_failure(self):
        import re
        source = (ROOT / "wrt_core/update.sh").read_text(encoding="utf-8")
        stage = re.search(r"(?ms)^stage_pre_install_source_fixes\(\) \{\n(.*?)^\}", source).group(1)
        names = set(re.findall(r"^    ([a-z_][a-z_0-9]*)\b", stage, re.M))
        script = 'source "$BASE_PATH/update.sh"\n'
        script += "\n".join(name + "() { :; }" for name in names if name != "add_quickfile")
        script += "\nadd_quickfile() { return 29; }\nstage_pre_install_source_fixes\n"
        result = subprocess.run([shell.bash_executable(), "--noprofile", "--norc", "-c", script],
                                env=dict(os.environ, BASE_PATH=shell.bash_path(ROOT / "wrt_core")),
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
