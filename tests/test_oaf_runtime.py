#!/usr/bin/env python3
"""Execute reviewed OAF build-copy C functions against kernel boundary doubles."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
import c_test_env
from c_test_env import compile_c

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "wrt_core/managed/packages"
MODULE = ROOT / "wrt_core/oaf_runtime_compat.py"
HARNESS = ROOT / "tests/fixtures/oaf_runtime_harness.c"
INPUTS = ("oaf/src/fwx_main.c", "open-app-filter/src/main.c")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def function(source, name):
    """Extract the real complete function; fixtures replace only external APIs."""
    match = re.search(r"(?m)^.*\b" + re.escape(name) + r"\([^;\n]*\)\s*\{", source)
    if not match:
        raise AssertionError("Production function not found: " + name)
    start = source.index("{", match.start())
    return source[match.start():closing_brace(source, start) + 1]


def closing_brace(source, start):
    # The selected functions have no braces in string literals/comments. Keep
    # extraction balanced so an upstream branch change cannot silently truncate.
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("Unbalanced production function")


def nonlinear_wrapper(source, name):
    body = function(source, name)
    start = body.index("if (skb_is_nonlinear(skb)")
    opening = body.index("{", start)
    block = body[start:closing_brace(body, opening) + 1]
    return ("static int copy_" + name + "(struct sk_buff *skb, flow_info_t *output) {\n"
            "flow_info_t flow = *output; unsigned char malloc_data = 0;\n" + block +
            "\n*output = flow; return malloc_data ? 77 : 78;\n}\n")


class BuildCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oaf-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in INPUTS:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RAW / relative, target)
        self.module = load_module(MODULE, "oaf_runtime_compat") if MODULE.exists() else None

    def prepare(self):
        self.assertIsNotNone(self.module, "OAF runtime build-copy preparer is missing")
        return self.module.prepare(self.root / "oaf", self.root / "open-app-filter")

    def test_prepares_only_build_copies_and_is_idempotent(self):
        raw = {relative: (RAW / relative).read_bytes() for relative in INPUTS}
        before = snapshot(self.root)
        self.assertTrue(self.prepare()["changed"])
        prepared = snapshot(self.root)
        self.assertEqual(set(prepared), set(before))
        self.assertTrue(all(prepared[relative] != before[relative] for relative in INPUTS))
        self.assertFalse(self.prepare()["changed"])
        self.assertEqual(snapshot(self.root), prepared)
        self.assertEqual({relative: (RAW / relative).read_bytes() for relative in INPUTS}, raw)

    def test_check_only_validates_both_states_without_writing(self):
        self.assertIsNotNone(self.module, "OAF runtime build-copy preparer is missing")
        for prepared in (False, True):
            with self.subTest(prepared=prepared):
                if prepared:
                    self.prepare()
                before = snapshot(self.root)
                result = self.module.prepare(self.root / "oaf", self.root / "open-app-filter", check_only=True)
                self.assertFalse(result["changed"])
                self.assertEqual(result["needs_update"], not prepared)
                self.assertEqual(snapshot(self.root), before)
        relative = INPUTS[0]
        (self.root / relative).write_bytes(b"unknown C file\n")
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, "drift|partial"):
            self.module.prepare(self.root / "oaf", self.root / "open-app-filter", check_only=True)
        self.assertEqual(snapshot(self.root), before)

    def test_unknown_and_partial_states_fail_before_any_write(self):
        original = snapshot(self.root)
        self.prepare()
        prepared = snapshot(self.root)
        for relative in INPUTS:
            with self.subTest(relative=relative, state="partial"):
                for path, data in original.items():
                    (self.root / path).write_bytes(data)
                (self.root / relative).write_bytes(prepared[relative])
                before = snapshot(self.root)
                with self.assertRaisesRegex(ValueError, "drift|partial"):
                    self.prepare()
                self.assertEqual(snapshot(self.root), before)
            with self.subTest(relative=relative, state="unknown"):
                (self.root / relative).write_bytes(b"unreviewed source\n")
                before = snapshot(self.root)
                with self.assertRaisesRegex(ValueError, "drift|partial"):
                    self.prepare()
                self.assertEqual(snapshot(self.root), before)

    def test_publish_failure_restores_all_original_files(self):
        before = snapshot(self.root)
        self.assertIsNotNone(self.module, "OAF runtime build-copy preparer is missing")
        replace = self.module.os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second-file publication failure")
            return replace(source, destination)

        with mock.patch.object(self.module.os, "replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.prepare()
        self.assertEqual(snapshot(self.root), before)

    def test_staging_failure_leaves_no_modification_or_temporary_files(self):
        before = snapshot(self.root)
        self.assertIsNotNone(self.module, "OAF runtime build-copy preparer is missing")
        with mock.patch.object(self.module.tempfile, "NamedTemporaryFile", side_effect=OSError("staging failure")):
            with self.assertRaisesRegex(OSError, "staging failure"):
                self.prepare()
        self.assertEqual(snapshot(self.root), before)

    def test_managed_source_roots_are_rejected(self):
        self.assertIsNotNone(self.module, "OAF runtime build-copy preparer is missing")
        before = {relative: (RAW / relative).read_bytes() for relative in INPUTS}
        with self.assertRaisesRegex(ValueError, "build copy"):
            self.module.prepare(RAW / "oaf", RAW / "open-app-filter")
        self.assertEqual({relative: (RAW / relative).read_bytes() for relative in INPUTS}, before)

    def test_unreviewed_managed_bytes_or_patch_fail_before_target_changes(self):
        self.assertIsNotNone(self.module, "OAF runtime build-copy preparer is missing")
        before = snapshot(self.root)
        with tempfile.TemporaryDirectory(prefix="oaf-unreviewed-") as directory:
            baseline = Path(directory) / "packages"
            for relative in INPUTS:
                path = baseline / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(RAW / relative, path)
            (baseline / INPUTS[1]).write_bytes(b"unreviewed baseline\n")
            with mock.patch.object(self.module, "RAW", baseline):
                with self.assertRaisesRegex(ValueError, "managed source.*drift"):
                    self.prepare()
            patch = Path(directory) / "changed.patch"
            patch.write_bytes(self.module.PATCH.read_bytes() + b"\n")
            with mock.patch.object(self.module, "PATCH", patch):
                with self.assertRaisesRegex(ValueError, "patch.*drift"):
                    self.prepare()
        self.assertEqual(snapshot(self.root), before)

    def test_existing_default_off_and_acl_preparation_composes_in_either_order(self):
        compat = load_module(ROOT / "wrt_core/oaf_compat.py", "oaf_compat")
        for relative in compat.REVIEWED:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RAW / relative, target)
        for runtime_first in (False, True):
            with self.subTest(runtime_first=runtime_first):
                if runtime_first:
                    self.prepare()
                compat.prepare(self.root / "open-app-filter", self.root / "luci-app-oaf")
                policy = {path: (self.root / path).read_bytes() for path in (
                    "open-app-filter/files/fwx", "open-app-filter/files/appfilter.init",
                    "open-app-filter/files/99_disable_oaf", "open-app-filter/files/luci-app-oaf.json")}
                self.prepare()
                self.assertEqual({path: (self.root / path).read_bytes() for path in policy}, policy)
                self.assertFalse(compat.prepare(self.root / "open-app-filter", self.root / "luci-app-oaf")["changed"])
                for relative in INPUTS:
                    (self.root / relative).write_bytes((RAW / relative).read_bytes())


class RuntimeCFunctions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="oaf-runtime-c-")
        cls.root = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        for relative in INPUTS:
            target = cls.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RAW / relative, target)
        if os.environ.get("OAF_RUNTIME_BASELINE") != "1":
            if not MODULE.exists():
                raise AssertionError("OAF runtime build-copy preparer is missing")
            load_module(MODULE, "oaf_runtime_c").prepare(cls.root / "oaf", cls.root / "open-app-filter")
        source = (cls.root / INPUTS[0]).read_text(encoding="utf-8")
        backend = (cls.root / INPUTS[1]).read_text(encoding="utf-8")
        bypass = function(source, "fwx_hook_bypass_handle")
        start = bypass.index("spin_lock(&af_conn_lock);")
        end = bypass.index("conn->last_jiffies", start)
        lock_path = ("static int connection_allocation(void) { flow_info_t flow = {0}; af_conn_t *conn;\n" +
                     bypass[start:end] + "spin_unlock(&af_conn_lock); return 77; }\n")
        limit = re.search(r"(?m)^#define MAX_AF_SUPPORT_DATA_LEN \d+$", source).group()
        selected = "\n".join((limit, function(source, "read_skb"), function(source, "dpi_http_proto"),
                               lock_path, nonlinear_wrapper(source, "fwx_hook_bypass_handle"),
                               nonlinear_wrapper(source, "fwx_hook_gateway_handle"),
                               function(backend, "update_lan_ip")))
        harness = HARNESS.read_text(encoding="utf-8").replace("/* PRODUCTION_FUNCTIONS */", selected)
        cfile = cls.root / "harness.c"
        cfile.write_text(harness, encoding="utf-8")
        cls.exe = cls.root / ("harness.exe" if os.name == "nt" else "harness")
        compile_c(cfile, cls.exe)

    def check_case(self, name):
        result = subprocess.run([str(self.exe), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, name + ":\n" + result.stdout + result.stderr)

    def test_read_skb_copies_fragment_bytes_with_atomic_allocation(self):
        self.check_case("copy")

    def test_read_skb_rejects_invalid_ranges_without_allocation(self):
        self.check_case("range")

    def test_read_skb_frees_failed_copy_and_allocation(self):
        self.check_case("copy-failure")
        self.check_case("allocation-failure")

    def test_connection_allocation_failure_releases_the_real_lock_path(self):
        self.check_case("lock")

    def test_both_nonlinear_paths_bound_copy_and_dpi_length(self):
        self.check_case("nonlinear")

    def test_http_short_final_lines_and_null_data_are_safe(self):
        self.check_case("http-short")

    def test_http_valid_get_post_host_and_body_survive(self):
        self.check_case("http-valid")

    def test_update_lan_ip_uses_current_schema_and_preserves_fallback(self):
        self.check_case("lan")


class CompilerAvailability(unittest.TestCase):
    def test_payload_pointer_type_matches_production_header(self):
        # MSVC accepts arithmetic between differently signed character pointers;
        # GCC rejects it. Keep the kernel boundary model faithful on both hosts.
        header = (RAW / "oaf/src/fwx.h").read_text(encoding="utf-8")
        harness = HARNESS.read_text(encoding="utf-8")
        pattern = r"(?m)^\s*((?:unsigned\s+)?char\s*\*)\s*l4_data\s*;"
        actual = re.findall(pattern, header)
        modeled = re.findall(pattern, harness)
        self.assertEqual(len(actual), 1)
        self.assertEqual(len(modeled), 1)
        self.assertEqual(re.sub(r"\s+", "", modeled[0]), re.sub(r"\s+", "", actual[0]))

    def test_absent_compiler_is_a_failure_not_a_skip(self):
        with mock.patch.object(c_test_env.shutil, "which", return_value=None), \
                mock.patch.object(c_test_env, "msvc_environment_script", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "C compiler required"):
                compile_c(Path("unused.c"), Path("unused.exe"), {"PATH": ""})


if __name__ == "__main__":
    unittest.main()
