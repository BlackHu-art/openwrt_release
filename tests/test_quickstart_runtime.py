#!/usr/bin/env python3
"""Run prepared Quickstart Lua and shell through the real managed build hook."""
import hashlib
import importlib.util
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from lupa.lua51 import LuaRuntime
from shell_test_helpers import bash_executable, bash_path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "wrt_core/managed"
RAW = SOURCES / "packages/luci-app-quickstart"
COMPAT = ROOT / "wrt_core/quickstart_compat.py"
FILES = ("luasrc/controller/istore_backend.lua", "luasrc/controller/quickstart.lua",
         "root/usr/libexec/quickstart/auto_setup.sh")
NIXIO = ROOT / "tests/fixtures/quickstart/nixio-util.lua"


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob("*") if p.is_file()}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def windows_translation_copy(source, destination, *args, **kwargs):
    """Only model Quickstart's translation link on unprivileged Windows.

    The real loader still verifies/copies the managed package. This OS boundary
    model is never used on Linux and does not prove Windows symlink capability.
    """
    destination = Path(destination)
    if source != "zh-cn" or destination.name != "zh_Hans" or destination.parent.name != "po":
        raise AssertionError("unexpected managed symlink: " + str(destination))
    shutil.copytree(destination.parent / source, destination)


def build_hook(build, *, install=False):
    environment = dict(os.environ, BASE_PATH=bash_path(ROOT / "wrt_core"),
                       BUILD_DIR=bash_path(build), TEST_PYTHON=Path(sys.executable).as_posix(),
                       TEST_HARNESS=Path(__file__).resolve().as_posix())
    script = '''set -euo pipefail
source "$BASE_PATH/update.sh"
python3() {
    case "$1" in
        */managed_plugins.py) "$TEST_PYTHON" "$TEST_HARNESS" --managed-loader-shim "$@" ;;
        *) "$TEST_PYTHON" "$@" ;;
    esac
}
git_retry() { echo 'unexpected network download' >&2; return 91; }
curl_retry() { echo 'unexpected network download' >&2; return 92; }
target="$BUILD_DIR/feeds/custom_feed"
'''
    if install:
        script += '''install_managed_package quickstart "$target/quickstart"
install_managed_package luci-app-quickstart "$target/luci-app-quickstart"
'''
    script += "fix_quickstart\n"
    return subprocess.run([bash_executable(), "--noprofile", "--norc", "-c", script],
                          env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90)


def lua_runtime(package):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().nixio_fixture = NIXIO.as_posix()
    lua.globals().backend_file = (package / FILES[0]).as_posix()
    lua.globals().controller_file = (package / FILES[1]).as_posix()
    lua.execute(r'''
forms, response, executions, filesystem_calls = {}, nil, {}, 0
local http = {
    formvalue = function(key) return forms[key] end,
    prepare_content = function() end,
    write_json = function(value) response = value end,
}
local fs = {
    readfile = function() filesystem_calls = filesystem_calls + 1; return "" end,
    unlink = function() filesystem_calls = filesystem_calls + 1 end,
}
local socket = {}; socket.__index = socket
local nixio = {meta_socket=socket, meta_file={}, const={buffersize=4096},
    uname=function() return {sysname="Linux", release="6.12"} end,
    bit={rshift=function(value, bits) return math.floor(value / 2^bits) end}}
local util = {shellquote=function(value) return "'" .. value:gsub("'", "'\\''") .. "'" end}
package.preload["luci.http"] = function() return http end
package.preload["luci.util"] = function() return util end
package.preload["luci.ltn12"] = function() return {sink={error=function(err)
    return function() return nil, err end end}} end
package.preload["nixio"] = function() return nixio end
package.preload["nixio.fs"] = function() return fs end
package.preload["nixio.util"] = function() return assert(loadfile(nixio_fixture))() end
_G.luci = {http=http, util=util}; _G.nixio = nixio
os.execute = function(command) executions[#executions+1] = command; return execution_result or 0 end
assert(loadfile(controller_file))()
quickstart = package.loaded["luci.controller.quickstart"]
assert(loadfile(backend_file))()
backend_loaded_nixio = package.loaded["nixio.util"] ~= nil
-- The parser tests need real recv/readall semantics even for the RED baseline.
-- Separately assert that production loads the extension itself.
require "nixio.util"
backend = package.loaded["luci.controller.istore_backend"].istore_backend
function upvalue(name)
    for i=1,100 do
        local key, value = debug.getupvalue(backend, i)
        if not key then break end
        if key == name then return value end
    end
    error("missing proxy helper " .. name)
end
function test_socket(wire, pos, step)
    local sock = setmetatable({wire=wire, pos=pos or 1, calls=0}, socket)
    function sock:read(n)
        assert(n > 0, "zero-length receive")
        self.calls = self.calls + 1
        assert(self.calls < 3000, "unbounded receive loop")
        local data = self.wire:sub(self.pos, self.pos + math.min(n, step or n) - 1)
        self.pos = self.pos + #data
        return data
    end
    sock.recv = sock.read
    return sock
end
''')
    return lua


class QuickstartRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="quickstart-runtime-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.build = Path(cls.temp.name) / "build"
        cls.build.mkdir()
        result = build_hook(cls.build, install=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.package = cls.build / "feeds/custom_feed/luci-app-quickstart"

    def setUp(self):
        self.lua = lua_runtime(self.package)

    def test_proxy_short_writes_use_loaded_nixio_sendall(self):
        self.assertEqual(hashlib.sha256(NIXIO.read_bytes()).hexdigest(),
                         "1e9a1693ac0b4cb3b4d3e6adaa77279da1dc247182cc6bf2d1f731b30dcfdb9b")
        self.lua.execute(r'''
local sock = test_socket("")
local sent, writes = "", 0
function sock:write(data, offset)
    writes = writes + 1
    local chunk = data:sub((offset or 0)+1, (offset or 0)+3)
    sent = sent .. chunk
    return #chunk
end
sock.send = sock.write
assert(upvalue("sink_socket")(sock)("whole request body"))
assert(sent == "whole request body", "short socket write truncated request: " .. sent)
assert(writes > 1, "short-write primitive did not run repeatedly")
assert(backend_loaded_nixio, "nixio.util was not explicitly loaded")
''')

    def test_proxy_write_failure_propagates(self):
        self.lua.execute(r'''
local sock = test_socket("")
function sock:write() return nil, 32, "broken pipe" end
sock.send = sock.write
local ok, code = upvalue("sink_socket")(sock)("request")
assert(ok == nil and code == 32, "socket write error was hidden")
''')

    def test_all_chunk_buffer_and_network_boundaries_preserve_body(self):
        self.lua.execute(r'''
local wire = "5\r\nhello\r\n5;extension=value\r\nworld\r\n0\r\n\r\n"
for split=0,#wire do
    for step=1,#wire do
        local source = upvalue("chunksource")(test_socket(wire, split+1, step), wire:sub(1,split))
        local output, ended = "", false
        for i=1,100 do
            local data, err = source()
            assert(not err, "chunk parse failed at " .. split .. "/" .. step)
            if not data then ended = true; break end
            output = output .. data
        end
        assert(ended and output == "helloworld", "corrupt chunk boundary " .. split .. "/" .. step)
    end
end
''')

    def test_empty_eof_and_short_body_or_crlf_are_errors(self):
        self.lua.execute(r'''
for _, wire in ipairs({"", "5", "5\r", "5\r\n", "5\r\nhell", "5\r\nhello", "5\r\nhello\r"}) do
    for split=0,#wire do
        local source=upvalue("chunksource")(test_socket(wire,split+1,1), wire:sub(1,split))
        local body, code=source()
        assert(body == nil and code ~= nil, "truncated chunk accepted at " .. split .. ":" .. #wire)
    end
end
local source=upvalue("chunksource")({recv=function() return nil, 104 end}, "")
local body, code=source()
assert(body == nil and code == 104, "receive error was hidden")
''')

    def test_malformed_headers_and_data_terminators_are_rejected(self):
        self.lua.execute(r'''
for _, wire in ipairs({"z\r\n", "1oops\r\nx\r\n", "-1\r\n", " 1\r\n", "1\r\nxzz", "1\r\nx\rX",
    string.rep("z",1024), "1;" .. string.rep("x",1024) .. "\r\nx\r\n"}) do
    for split=0,#wire do
        local source=upvalue("chunksource")(test_socket(wire,split+1,3), wire:sub(1,split))
        local body, code=source()
        assert(body == nil and code ~= nil, "invalid chunk accepted at " .. split .. ":" .. #wire)
    end
end
local header = "1;" .. string.rep("x",1018) .. "\r\n"
local source=upvalue("chunksource")(test_socket(header .. "x\r\n0\r\n\r\n",1,1), "")
assert(source()=="x", "valid header below the limit was rejected")
''')

    def test_invalid_controller_packages_have_no_shell_or_filesystem_effects(self):
        self.lua.execute(r'''
local invalid={"../other", "--help", "two packages", "pkg'", "pkg;id", "pkg\nnext", "pkg/other",
    "包名", string.rep("a",129), true, 1, {"aria2", "../other"}, {"aria2", {}}, {"aria2", false}}
for _, packages in ipairs(invalid) do
    forms, response, executions, filesystem_calls = {packages=packages}, nil, {}, 0
    quickstart.auto_setup()
    assert(response and response.success ~= 0 and response.scope == "params", "invalid package accepted")
    assert(#executions==0 and filesystem_calls==0, "invalid package caused side effects")
end
for _, packages in ipairs({"", {}, {""}}) do
    forms, response, executions, filesystem_calls = {packages=packages}, nil, {}, 0
    quickstart.auto_setup()
    assert(response and response.success ~= 0 and response.scope=="params")
    assert(#executions==0 and filesystem_calls==0)
end
forms, response, executions, filesystem_calls = {}, nil, {}, 0
quickstart.auto_setup()
assert(response.success~=0 and #executions==0 and filesystem_calls==0)
''')

    def test_valid_controller_packages_and_task_failure_status(self):
        self.lua.execute(r'''
for _, packages in ipairs({"aria2", {"qbittorrent", "foo+bar_1.2-3"}, string.rep("a",128)}) do
    forms, response, executions, filesystem_calls = {packages=packages}, nil, {}, 0
    quickstart.auto_setup()
    assert(response and response.success==0 and #executions==1, "valid package rejected")
    assert(executions[1]:match("^/etc/init.d/tasks task_add auto_setup "), "task wrapper missing")
end
forms, executions, execution_result = {packages="aria2"}, {}, 256
quickstart.auto_setup()
assert(response.success==1 and response.scope=="taskd" and response.error~="", "task failure hidden")
''')

    def test_existing_temperature_and_status_adapter_is_retained(self):
        self.lua.execute(r'''
local open = io.open
io.open=function(name)
    assert(name=="/sys/class/thermal/thermal_zone0/temp")
    return {read=function() return 42123 end, close=function() end}
end
assert(upvalue("get_cpu_temperature")()==42)
io.open=open
''')
        source = (self.package / FILES[0]).read_text(encoding="utf-8")
        self.assertIn('"/istore/system/status/"', source)
        self.assertEqual(source.count('cpuTemperature'), 2)

    def test_hook_is_idempotent_and_keeps_dependency_removal(self):
        before = snapshot(self.package)
        result = build_hook(self.build)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.package), before)
        recipe = (self.build / "feeds/custom_feed/quickstart/Makefile").read_text(encoding="utf-8")
        for dependency in ("+smartmontools", "+mdadm", "+parted", "+e2fsprogs"):
            self.assertNotIn(dependency, recipe)


class QuickstartShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="quickstart-shell-build-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.build = Path(cls.temp.name) / "build"
        cls.build.mkdir()
        result = build_hook(cls.build, install=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.prepared = (cls.build / "feeds/custom_feed/luci-app-quickstart" / FILES[2]).read_text(encoding="utf-8")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="quickstart-shell-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.logs, self.metadata = self.root / "log", self.root / "metadata"
        self.logs.mkdir(); self.metadata.mkdir()
        binary = self.root / "bin"; binary.mkdir()
        helper = self.root / "functions.sh"
        helper.write_text('printf "loaded\\n" >> "$FIXTURE_SIDE_EFFECTS"\n'
                          'config_load() { return "${FIXTURE_CONFIG_STATUS:-0}"; }\n'
                          'config_get() { eval "$1=\\\"$FIXTURE_MAIN\\\""; }\n', encoding="utf-8")
        installer = binary / "is-opkg"
        installer.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$FIXTURE_INSTALLED"\n'
                             'exit "${FIXTURE_INSTALL_STATUS:-0}"\n', encoding="utf-8")
        installer.chmod(0o755)
        self.script = self.root / "auto_setup.sh"
        self.script.write_text(self.prepared.replace("/var/log", bash_path(self.logs))
                               .replace("/lib/functions.sh", bash_path(helper))
                               .replace("/usr/libexec/istorea", bash_path(self.metadata)), encoding="utf-8")
        self.installed, self.configured = self.root / "installed", self.root / "configured"
        self.effects = self.root / "side-effects"
        self.environment = dict(os.environ, FIXTURE_MAIN=bash_path(self.root / "data"),
                                FIXTURE_INSTALLED=bash_path(self.installed),
                                FIXTURE_CONFIGURED=bash_path(self.configured),
                                FIXTURE_SIDE_EFFECTS=bash_path(self.effects),
                                FIXTURE_BIN=bash_path(binary), FIXTURE_SCRIPT=bash_path(self.script),
                                FIXTURE_ARGS=bash_path(self.root / "arguments"))

    def run_script(self, *arguments):
        # Native Windows -> MSYS argv conversion strips some quotes/newlines.
        # A NUL-delimited transport lets the actual shell receive exact inputs.
        (self.root / "arguments").write_bytes(b"".join(arg.encode("utf-8")+b"\0" for arg in arguments))
        return subprocess.run([bash_executable(), "--noprofile", "--norc", "-c",
                               'export PATH="$FIXTURE_BIN:$PATH"; '
                               'mapfile -d "" -t arguments < "$FIXTURE_ARGS"; '
                               'exec sh "$FIXTURE_SCRIPT" "${arguments[@]}"'], env=self.environment,
                              capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_invalid_arguments_rejected_before_any_side_effect(self):
        sentinels = {name: b"existing log\n" for name in
                     ("auto_setup.input", "auto_setup.success", "auto_setup.failed")}
        for name, data in sentinels.items():
            (self.logs / name).write_bytes(data)
        for arguments in ((), ("aria2", "../other"), ("--help",), ("two packages",), ("pkg'",),
                          ("",), ("a"*129,), ("pkg;touch side-effect",), ("pkg\nnext",)):
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(snapshot(self.logs), sentinels)
                self.assertFalse(self.installed.exists())
                self.assertFalse(self.effects.exists())
                self.assertFalse((self.root / "data").exists())

    def test_valid_packages_install_source_and_report_exact_arguments(self):
        packages = ("aria2", "foo+bar_1.2-3", "a" * 128)
        for name in packages:
            (self.metadata / (name + ".sh")).write_text(
                'printf "%s\\n" "' + name + '" >> "$FIXTURE_CONFIGURED"\n', encoding="utf-8")
        result = self.run_script(*packages)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.installed.read_text().splitlines(),
                         [value for name in packages for value in ("install", "app-meta-"+name)])
        self.assertEqual(self.configured.read_text().splitlines(), list(packages))
        self.assertEqual((self.logs / "auto_setup.success").read_text().splitlines(), list(packages))
        self.assertEqual((self.logs / "auto_setup.input").read_text().splitlines(), list(packages))
        self.assertEqual((self.logs / "auto_setup.failed").read_text(), "")

    def test_install_and_metadata_failures_propagate_and_report(self):
        for mode in ("installer", "metadata", "missing"):
            with self.subTest(mode=mode):
                metadata = self.metadata / "aria2.sh"
                metadata.unlink(missing_ok=True)
                self.installed.unlink(missing_ok=True)
                self.configured.unlink(missing_ok=True)
                self.environment["FIXTURE_INSTALL_STATUS"] = "17" if mode=="installer" else "0"
                if mode != "missing":
                    metadata.write_text('echo sourced >> "$FIXTURE_CONFIGURED"\nexit 23\n', encoding="utf-8")
                result = self.run_script("aria2")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.logs / "auto_setup.failed").read_text().splitlines(), ["aria2"])
                self.assertEqual((self.logs / "auto_setup.success").read_text(), "")
                self.assertEqual(self.configured.exists(), mode=="metadata")

    def test_configuration_failure_propagates_before_installer(self):
        self.environment["FIXTURE_CONFIG_STATUS"] = "19"
        result = self.run_script("aria2")
        self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
        self.assertFalse(self.installed.exists())


class QuickstartGuard(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="quickstart-guard-")
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name) / "build"
        self.package = self.build / "feeds/custom_feed/luci-app-quickstart"
        self.loader = load_module("quickstart_managed_loader", ROOT / "wrt_core/managed_plugins.py")
        if os.name == "nt":
            with mock.patch.object(os, "symlink", side_effect=windows_translation_copy):
                self.loader.stage_package(SOURCES, "luci-app-quickstart", self.package, self.build)
        else:
            self.loader.stage_package(SOURCES, "luci-app-quickstart", self.package, self.build)

    def adapter(self):
        self.assertTrue(COMPAT.is_file(), "Quickstart runtime adapter is not implemented")
        return load_module("quickstart_compat_test", COMPAT)

    def test_preparation_preserves_raw_sources_and_unrelated_package_bytes(self):
        before = snapshot(SOURCES)
        original = snapshot(self.package)
        self.adapter().prepare(self.package)
        prepared = snapshot(self.package)
        self.assertEqual(snapshot(SOURCES), before)
        self.assertEqual({name for name in original if original[name] != prepared[name]}, set(FILES))
        self.adapter().prepare(self.package)
        self.assertEqual(snapshot(self.package), prepared)

    def test_old_compat_template_is_accepted_and_preserved_then_derived(self):
        self.loader.stage_support(SOURCES, "compat/istore_backend.lua", self.package / FILES[0], self.build)
        self.adapter().prepare(self.package)
        lua_runtime(self.package).execute('assert(package.loaded["nixio.util"])')
        self.assertIn(b"cpuTemperature", (self.package / FILES[0]).read_bytes())

    def test_unknown_and_partially_prepared_states_rejected_without_writes(self):
        adapter = self.adapter()
        original = {name: (self.package / name).read_bytes() for name in FILES}
        adapter.prepare(self.package)
        prepared = {name: (self.package / name).read_bytes() for name in FILES}
        for name in FILES:
            for baseline in (original, prepared):
                for target, data in baseline.items():
                    (self.package / target).write_bytes(data)
                (self.package / name).write_bytes((prepared if baseline is original else original)[name])
                before = snapshot(self.package)
                with self.assertRaises(ValueError):
                    adapter.prepare(self.package)
                self.assertEqual(snapshot(self.package), before)
            for target, data in original.items():
                (self.package / target).write_bytes(data)
            (self.package / name).write_bytes(original[name] + b"\n-- unreviewed drift\n")
            before = snapshot(self.package)
            with self.assertRaises(ValueError):
                adapter.prepare(self.package)
            self.assertEqual(snapshot(self.package), before)

    def test_failed_publication_rolls_back_all_three_files(self):
        adapter = self.adapter()
        before = snapshot(self.package)
        replace, calls = adapter.os.replace, []
        def fail_second(source, destination):
            calls.append((source, destination))
            if len(calls) == 2:
                raise OSError("injected second replace failure")
            return replace(source, destination)
        with mock.patch.object(adapter.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                adapter.prepare(self.package)
        self.assertEqual(snapshot(self.package), before)
        self.assertFalse(list(self.package.rglob(".quickstart-*")))

    def test_hook_drift_failure_preserves_backend_and_dependency_recipe(self):
        self.loader.stage_package(SOURCES, "quickstart", self.package.parent / "quickstart", self.build)
        controller = self.package / FILES[1]
        controller.write_bytes(controller.read_bytes() + b"\n-- unreviewed change\n")
        before = snapshot(self.package.parent)
        result = build_hook(self.build)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("drift", result.stderr)
        self.assertEqual(snapshot(self.package.parent), before)

    def test_changed_reviewed_patch_or_raw_input_is_rejected_before_writes(self):
        adapter = self.adapter()
        before = snapshot(self.package)
        bad_patch = self.build / "changed.patch"
        bad_patch.write_bytes(adapter.PATCH.read_bytes() + b"\n# drift\n")
        with mock.patch.object(adapter, "PATCH", bad_patch):
            with self.assertRaises(ValueError):
                adapter.prepare(self.package)
        self.assertEqual(snapshot(self.package), before)
        changed_raw = self.build / "changed-raw"
        shutil.copytree(RAW, changed_raw)
        controller = changed_raw / FILES[1]
        controller.write_bytes(controller.read_bytes() + b"\n-- drift\n")
        with mock.patch.object(adapter, "RAW", changed_raw):
            with self.assertRaises(ValueError):
                adapter.prepare(self.package)
        self.assertEqual(snapshot(self.package), before)

    def test_managed_or_maintenance_source_cannot_be_a_destination(self):
        adapter = self.adapter()
        for destination in (RAW, ROOT / "maintenance/plugins/quickstart/luci-app-quickstart"):
            before = snapshot(destination)
            with self.assertRaises(ValueError):
                adapter.prepare(destination)
            self.assertEqual(snapshot(destination), before)

    def test_missing_input_and_redirected_payload_rejected_without_writes(self):
        adapter = self.adapter()
        path = self.package / FILES[1]
        data = path.read_bytes()
        path.unlink()
        before = snapshot(self.package)
        with self.assertRaises(ValueError):
            adapter.prepare(self.package)
        self.assertEqual(snapshot(self.package), before)
        path.write_bytes(data)
        symlink = Path.is_symlink
        # Windows does not grant symlink creation; Linux exercises a real link.
        if os.name == "nt":
            with mock.patch.object(Path, "is_symlink", lambda p: p == path or symlink(p)):
                with self.assertRaises(ValueError):
                    adapter.prepare(self.package)
        else:
            outside = self.build / "outside.lua"
            outside.write_bytes(data)
            path.unlink(); path.symlink_to(outside)
            with self.assertRaises(ValueError):
                adapter.prepare(self.package)
            self.assertEqual(outside.read_bytes(), data)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--managed-loader-shim"]:
        del sys.argv[1]
        script = sys.argv[1]
        del sys.argv[1]
        sys.argv[0] = script
        if os.name == "nt":
            with mock.patch.object(os, "symlink", side_effect=windows_translation_copy):
                runpy.run_path(script, run_name="__main__")
        else:
            runpy.run_path(script, run_name="__main__")
    else:
        unittest.main()
