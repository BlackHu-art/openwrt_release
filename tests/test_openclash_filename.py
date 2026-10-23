#!/usr/bin/env python3
"""Execute filename checks from the complete stable OpenClash patch inputs.

Lua 5.1 runs the actual helper and controller; filesystem, HTTP, UCI and service
operations stop at recorded boundaries. Node runs the real editor and its form
handlers. No installed service, router, or user configuration is accessed.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from openclash_fixture import ROOT, make_package

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASH = os.environ.get("BASH") or shutil.which("bash")
if os.name == "nt" and not BASH:
    BASH = "C:/Program Files/Git/bin/bash.exe"
NODE = os.environ.get("NODE") or shutil.which("node")
if os.environ.get("OPENCLASH_REQUIRE_NODE") == "1" and not NODE:
    raise RuntimeError("Node is required by OPENCLASH_REQUIRE_NODE")
VALID = ["config.yaml", "a-b_1.conf", "Home Rules.yaml", "中文 配置.yaml", "a" * 200, "中" * 66]
INVALID = [None, "", " ", "   ", ".hidden", "..", "../outside", "a/b", "a\\b", "a'bad",
           'a"bad', "a;bad", "a`bad", "a$bad", "a\nbad", "a\tbad", "a\x00bad", "a" * 201, "中" * 67]
DIRECTORIES = ["/etc/openclash/config/", "/etc/openclash/proxy_provider/", "/etc/openclash/rule_provider/"]


LUA_BOUNDARIES = r'''
state = { form = {}, calls = {}, response = nil, status = nil, selected = nil }
function record(kind, ...)
    table.insert(state.calls, {kind, ...})
end
local uci = {}
function uci:get(package, section, key)
    if key == "config_path" then return state.selected end
    return nil
end
function uci:foreach(...) record("uci.foreach", ...) end
function uci:add(...) record("uci.add", ...); return "new_section" end
function uci:set(...) record("uci.set", ...) end
function uci:delete(...) record("uci.delete", ...) end
function uci:set_list(...) record("uci.set_list", ...) end
function uci:commit(...) record("uci.commit", ...) end
package.loaded["luci.model.uci"] = {cursor = function() return uci end}
package.loaded["luci.sys"] = {
    call = function(command) record("service", command); return 0 end,
    exec = function(command) record("exec", command); return "test-architecture" end
}
package.loaded["luci.http"] = {
    formvalue = function(name) return state.form[name] end,
    prepare_content = function() end,
    write_json = function(value) state.response = value end,
    status = function(code, message) state.status = code end
}
package.loaded["nixio.fs"] = {
    move = function(old, new) record("rename", old, new); return true end,
    basename = function(path) return path:match("([^/]+)$") end
}
for _, name in ipairs({"luci.ltn12", "nixio.util", "luci.jsonc", "luci.util", "luci.i18n",
                      "luci.dispatcher", "luci.cbi.datatypes", "luci.model.ipkg"}) do
    package.loaded[name] = {}
end
-- The controller's version-module load is a service-file boundary.
dofile = function(path) assert(path == "/usr/share/openclash/openclash_version.lua"); return {} end
function reset(form)
    state.form = form; state.calls = {}; state.response = nil; state.status = nil; state.selected = nil
    state.files = {}; state.existing_file = nil
end
'''


JAVASCRIPT = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const cases = JSON.parse(process.argv[2]);
const mode = process.argv[3];
let elements, requests, alerts;
function element() {
    const classes = new Set();
    const listeners = {};
    return {
        value: '', disabled: false, checked: false, dataset: {}, style: {}, textContent: '',
        classList: { add: c => classes.add(c), remove: c => classes.delete(c),
            contains: c => classes.has(c), toggle: (c, value) => value ? classes.add(c) : classes.delete(c) },
        addEventListener: (event, fn) => (listeners[event] ||= []).push(fn),
        fire: function(event) {
            const evt = {target: this, stopPropagation() {}};
            if (typeof this['on' + event] === 'function') this['on' + event](evt);
            for (const fn of listeners[event] || []) fn(evt);
        },
        querySelector: selector => get(selector), querySelectorAll: () => [],
        setAttribute() {}, getAttribute() { return ''; }, closest() { return null; },
        appendChild() {}, removeChild() {}
    };
}
function get(selector) { return elements[selector] ||= element(); }
function fresh() {
    elements = {}; requests = []; alerts = [];
    const document = {
        readyState: 'loading', addEventListener() {}, getElementById: () => null,
        createElement: () => element(), documentElement: element(), body: element()
    };
    const context = vm.createContext({
        document, TextEncoder, console, setTimeout: fn => fn(),
        ocRegisterEditorHotkeys() {}, ocAlert: value => alerts.push(value),
        FormData: class { append() {} delete() {} },
        fetch: (...args) => { requests.push(args); return new Promise(() => {}); },
        XMLHttpRequest: class {
            constructor() { this.upload = {}; }
            open(...args) { this.args = args; }
            send(body) { requests.push([this.args, body]); }
        }
    });
    context.window = context;
    vm.runInContext(source, context, {filename: 'config_edit.js'});
    return context.ConfigEditor;
}
if (mode === 'validator') {
    const editor = fresh();
    for (const [name, expected] of cases) {
        assert.equal(editor.isValidOverwriteModuleName(name), expected, JSON.stringify(name));
    }
    assert.equal(editor.isValidOverwriteModuleName('openclash_custom_overwrite.sh'), false);
} else {
    for (const [name, expected] of cases.filter(([n]) => n !== null)) {
        for (const flow of ['upload', 'subscribe', 'edit']) {
            const editor = fresh();
            get('#overwrite-subscribe-type').value = 'file';
            get('#overwrite-subscribe-filename').value = name;
            if (flow === 'edit') {
                editor.showOverwriteSubmodel('old.conf', {type: 'file'}, '/etc/openclash/overwrite/old.conf');
            } else {
                get('#overwrite-upload-mode-file').classList.add('active');
                editor.showAddOverwritemodel();
                if (flow === 'upload') {
                    get('#overwrite-upload-file-input').files = [{name, size: 5}];
                    get('#overwrite-upload-file-input').fire('change');
                } else {
                    get('#overwrite-upload-mode-subscribe').fire('click');
                }
            }
            const input = get(flow === 'upload' ? '#overwrite-upload-filename-input' : '#overwrite-subscribe-filename');
            input.value = name;
            input.fire('input');
            const button = get(flow === 'edit' ? '#overwrite-edit-submit' : '#overwrite-upload-submit');
            assert.equal(button.disabled, !expected, flow + ' button ' + JSON.stringify(name));
            // Exercise submission even if a caller bypasses the disabled UI state.
            button.disabled = false;
            button.onclick();
            assert.equal(requests.length, expected ? 1 : 0, flow + ' request ' + JSON.stringify(name));
            if (!expected) assert.ok(alerts.length, flow + ' explains invalid input');
        }
    }
}
console.log('editor filename ' + mode + ': PASS');
'''


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="openclash-filename-")
        self.addCleanup(self.temporary.cleanup)
        self.package = Path(self.temporary.name) / "package"
        make_package(self.package)
        self.run_command(["git", "init", "-q", str(self.package)])
        self.run_command(["git", "-C", str(self.package), "config", "core.autocrlf", "false"])
        if os.environ.get("PLUGIN_FIX_MODE") != "original":
            self.run_command([BASH, "--noprofile", "--norc", "-c",
                'BASE_PATH="$1"; source "$BASE_PATH/modules/plugin_compat.sh"; fix_openclash_compat "$2"',
                "test-filename-fixer", (ROOT / "wrt_core").as_posix(), self.package.as_posix()])

    def run_command(self, args):
        result = subprocess.run(args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result


@unittest.skipUnless(LuaRuntime, "lupa.lua51 is required")
class FilenameLuaTests(PackageTest):
    def setUp(self):
        super().setUp()
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(LUA_BOUNDARIES)
        self.lua.execute((self.package / "luasrc/openclash.lua").read_text(encoding="utf-8"))
        self.fs = self.lua.globals().package.loaded["luci.openclash"]
        # The public helper exposes filesystem operations; these are the IO boundary.
        self.lua.execute('''
            local fs = package.loaded["luci.openclash"]
            fs.writefile = function(path, data)
                record("write", path, data); state.files[path] = data; return true
            end
            fs.isfile = function(path)
                record("isfile", path); return state.files[path] ~= nil or state.existing_file == path
            end
        ''')
        self.lua.execute((self.package / "luasrc/controller/openclash.lua").read_text(encoding="utf-8"))
        self.controller = self.lua.globals().package.loaded["luci.controller.openclash"]
        self.reset({})

    def reset(self, form):
        self.lua.globals().reset(self.lua.table_from(form))
        self.state = self.lua.globals().state

    def calls(self, kind=None):
        calls = [tuple(value.values()) for value in self.state.calls.values()]
        return [call for call in calls if kind is None or call[0] == kind]

    def test_update_rejects_invalid_names_before_starting_service(self):
        for name in INVALID:
            with self.subTest(name=name):
                self.reset({"filename": name})
                self.controller.action_update_config()
                self.assertEqual(self.state.response.status, "error")
                self.assertEqual(self.calls(), [])

    def test_subscription_rejects_invalid_names_before_uci_or_service(self):
        for name in INVALID:
            with self.subTest(name=name):
                self.reset({"name": name, "address": "https://example.invalid/config"})
                self.controller.action_add_subscription()
                self.assertEqual(self.state.response.status, "error")
                self.assertEqual(self.calls(), [])

    def test_create_and_rename_reject_outside_paths_without_io(self):
        for directory in [None, "", "/tmp/", "/etc/", "/etc/openclash/", "/etc/openclash/config/../", "/etc/openclash/config//"]:
            for operation in ["create_file", "rename_file"]:
                with self.subTest(directory=directory, operation=operation):
                    self.reset({"filename": "safe.yaml", "filepath": directory, "file_path": directory,
                                "file_name": "old.yaml", "new_file_name": "safe.yaml"})
                    self.controller[operation]()
                    self.assertEqual(self.state.status, 400)
                    self.assertEqual(self.calls(), [])

    def test_create_and_rename_reject_invalid_old_and_new_names_without_io(self):
        for name in INVALID:
            for operation, field in [("create_file", "filename"), ("rename_file", "file_name"), ("rename_file", "new_file_name")]:
                with self.subTest(name=name, operation=operation, field=field):
                    form = {"filename": "safe.yaml", "filepath": DIRECTORIES[0], "file_path": DIRECTORIES[0],
                            "file_name": "old.yaml", "new_file_name": "safe.yaml"}
                    form[field] = name
                    self.reset(form)
                    self.controller[operation]()
                    self.assertEqual(self.state.status, 400)
                    self.assertEqual(self.calls(), [])

    def test_allowed_directories_accept_cjk_spaces_and_keep_config_reference_updates(self):
        old, new = "旧 配置.yaml", "新 配置.yaml"
        for directory in DIRECTORIES:
            with self.subTest(directory=directory):
                self.reset({"filename": new, "filepath": directory})
                self.controller.create_file()
                self.assertIsNone(self.state.status)
                self.assertEqual(self.calls("write"), [("write", directory + new, "")])
                self.reset({"file_name": old, "new_file_name": new, "file_path": directory})
                self.state.selected = directory + old
                self.state.existing_file = "/etc/openclash/" + old
                self.controller.rename_file()
                self.assertEqual(self.state.status, 200)
                renames = [("rename", directory + old, directory + new)]
                if directory == DIRECTORIES[0]:
                    renames.append(("rename", "/etc/openclash/" + old, "/etc/openclash/" + new))
                    self.assertIn(("uci.set", "openclash", "config", "config_path", directory + new), self.calls())
                    self.assertTrue(self.calls("uci.commit"))
                self.assertEqual(self.calls("rename"), renames)

    def test_shared_validator_handles_types_and_filesystem_byte_limit(self):
        for name in VALID + INVALID + [False, 12, self.lua.table()]:
            with self.subTest(name=name):
                self.assertEqual(bool(self.fs.is_safe_filename(name)), name in VALID)

    def test_update_and_subscription_accept_cjk_spaces(self):
        self.reset({"filename": "中文 配置.yaml", "no_restart": "1"})
        self.controller.action_update_config()
        self.assertEqual(self.state.response.status, "success")
        self.assertEqual(self.calls("service"), [("service", "/usr/share/openclash/openclash.sh '中文 配置.yaml' norestart >/dev/null 2>&1")])
        self.reset({"name": "中文 配置", "address": "https://example.invalid/config"})
        self.controller.action_add_subscription()
        self.assertEqual(self.state.response.status, "success")
        self.assertIn(("uci.set", "openclash", "new_section", "name", "中文 配置"), self.calls())
        self.assertEqual(self.calls("uci.commit"), [("uci.commit", "openclash")])

    def test_cbi_alias_validator_uses_shared_filename_rules_and_preserves_empty_optional_value(self):
        source = (self.package / "luasrc/model/cbi/openclash/config-subscribe-edit.lua").read_text(encoding="utf-8")
        name_block = source.split("---- name\n", 1)[1].split("---- address\n", 1)[0]
        self.lua.execute('''
            fs = package.loaded["luci.openclash"]
            translate = function(value) return value end
            font_red = ""; bold_on = ""; bold_off = ""; font_off = ""
            s = {option = function() return {validate = function(self, value) return value end} end}
        ''' + name_block)
        option = self.lua.globals().o
        for name in VALID + INVALID:
            with self.subTest(name=name):
                expected = name if name in VALID or name == "" else None
                self.assertEqual(option.validate(option, name), expected)


@unittest.skipUnless(NODE, "Node is required")
class FilenameEditorTests(PackageTest):
    def editor(self, mode):
        cases = [[name, True] for name in VALID] + [[name, False] for name in INVALID]
        self.run_command([NODE, "-e", JAVASCRIPT, str(self.package / "root/www/luci-static/resources/openclash/js/config_edit.js"),
                          json.dumps(cases, ensure_ascii=True), mode])

    def test_real_javascript_validator_matches_filename_cases(self):
        self.editor("validator")

    def test_upload_add_and_edit_forms_reject_before_sending_requests(self):
        self.editor("forms")


@unittest.skipUnless(BASH, "Bash is required")
class FilenameShellTests(PackageTest):
    def test_overwrite_and_cron_restart_keys_do_not_alias_distinct_names(self):
        source = (self.package / "root/etc/init.d/openclash").read_text(encoding="utf-8")
        assignments = [re.search(r"^\s*" + variable + r"=\$\(.*$", source, re.M).group().strip()
                       for variable in ["safe_name", "module_flag_name"]]
        names = ["a-b", "a_b", "中文", "配置", "中文 模块"]
        script = '\n'.join(assignments) + '\nprintf "%s:%s\\n" "$safe_name" "$module_flag_name"\n'
        keys = []
        for name in names:
            result = self.run_command([BASH, "--noprofile", "--norc", "-c", 'name="$1"; ' + script, "filename-key-test", name])
            expected = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
            self.assertEqual(result.stdout.strip(), expected + ":" + expected)
            keys.append(expected)
        self.assertEqual(len(set(keys)), len(names))


if __name__ == "__main__":
    unittest.main()
