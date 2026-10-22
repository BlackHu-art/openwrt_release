#!/usr/bin/env python3
"""Run the complete pinned subscribe.lua in Lua 5.1 with UCI/OS boundaries.

No network, router, host UCI configuration, or service is touched. The UCI
double models native cursor contexts and commit journals separately. The LuCI
RPC cursor is forbidden so it cannot silently stand in for a native cursor.
Lifecycle calls observe committed configuration. Lupa is never auto-installed.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qsl, quote_plus, urlsplit

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[1]
URL_A = "https://fixture.invalid/a"
URL_B = "https://fixture.invalid/b"


def group_hash(url):
    # Upstream urlEncode escapes dots too, before shell echo adds its newline.
    encoded = quote_plus(url).replace(".", "%2E")
    return hashlib.md5((encoded + "\n").encode()).hexdigest()


def subscription(host="new.example", alias="New"):
    link = "ss://YWVzLTEyOC1nY206c2VjcmV0@" + host + ":443#" + alias
    return base64.b64encode(link.encode()).decode()


class ScriptExit(Exception):
    def __init__(self, code):
        self.code = int(code)


@unittest.skipUnless(LuaRuntime, "optional lupa.lua51 is required for the real subscription script")
class SubscriptionRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssr-subscription-")
        self.addCleanup(self.temp.cleanup)
        package = Path(self.temp.name)
        target = package / "root/usr/share/shadowsocksr/subscribe.lua"
        target.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tests/fixtures/ssrplus/2abdc9aa/subscribe.lua", target)
        patch = ROOT / "wrt_core/patches/ssrplus-subscription.patch"
        if patch.exists():
            for arguments in (("init", "-q"), ("apply", str(patch))):
                result = subprocess.run(["git", "-C", str(package), *arguments],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.source = target.read_text(encoding="utf-8").split("\n", 1)[1]
        self.sections = {
            "global": {".type": "global", "global_server": "old_a"},
            "subscribe": {".type": "server_subscribe", "subscribe_url": [URL_A],
                          "proxy": "0", "filter_words": "Filtered", "ss_type": "ss-rust"},
            "old_a": {".type": "servers", "server": "old-a.example", "server_port": "443",
                      "alias": "Old A", "hashkey": "old-a-hash", "grouphashkey": group_hash(URL_A)},
            "old_b": {".type": "servers", "server": "old-b.example", "server_port": "443",
                      "alias": "Old B", "hashkey": "old-b-hash", "grouphashkey": group_hash(URL_B)},
            "manual": {".type": "servers", "server": "manual.example", "server_port": "443",
                       "alias": "Manual"},
        }
        self.persisted = copy.deepcopy(self.sections)
        self.files = {}
        self.downloads = {URL_A: subscription(), URL_B: subscription("new-b.example", "New B")}
        self.http_codes = {}
        self.logs, self.commands, self.events = [], [], []
        self.commit_failure = False
        self.commit_statuses = []
        self.restart_status = 0
        self.restart_statuses = []
        self.service_callback = None
        self.lock_available = True
        self.lock_open_failure = False
        self.shared_changes = {}
        self.scratch = []
        self.fail_add = False
        self.identifier = 0
        self.installed_cores = {"sslocal"}

    def to_python(self, value):
        if hasattr(value, "items"):
            values = {key: self.to_python(item) for key, item in value.items()}
            if values and set(values) == set(range(1, len(values) + 1)):
                return [values[index] for index in range(1, len(values) + 1)]
            return values
        return value

    def server_nodes(self):
        return {key: value for key, value in self.sections.items() if value[".type"] == "servers"}

    def shell_exec(self, command):
        self.commands.append(command)
        if command.startswith("type -t -p "):
            for binary in re.findall(r"type -t -p ([\w-]+)", command):
                if binary in self.installed_cores:
                    return "/usr/bin/" + binary + "\n"
            return ""
        if command == "mktemp -d /tmp/ssr-subscribe.XXXXXX":
            path = f"/tmp/ssr-subscribe.T{len(self.scratch) + 1:05d}"
            self.scratch.append(path)
            self.files[path] = "private directory"
            return path + "\n"
        if command.startswith("curl "):
            url = shlex.split(command)[-1]
            self.events.append(("download", url))
            return self.downloads.get(url, "") + str(self.http_codes.get(url, 200))
        if command.startswith("echo "):
            value = " ".join(shlex.split(command.split(" | ", 1)[0])[1:]) + "\n"
            return hashlib.md5(value.encode()).hexdigest() + "\n"
        match = re.fullmatch(r'md5sum "([^\"]+)" 2>/dev/null \| cut -d " " -f1', command)
        if match:
            return hashlib.md5(self.files[match[1]].encode()).hexdigest() + "\n"
        raise AssertionError("unexpected luci.sys.exec: " + command)

    def shell_call(self, command):
        self.commands.append(command)
        match = re.fullmatch(r"/etc/init.d/shadowsocksr (stop|start|restart)(.*)", command)
        self.assertIsNotNone(match, "unexpected service command: " + command)
        selected = self.persisted["global"]["global_server"]
        self.events.append(("service", match[1], selected, selected in self.persisted, command))
        if self.service_callback:
            callback, self.service_callback = self.service_callback, None
            callback()
        return self.restart_statuses.pop(0) if self.restart_statuses else self.restart_status

    def run_subscriber(self):
        self.persisted = copy.deepcopy(self.sections)
        lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua = lua
        g = lua.globals()
        cursor_states = {}
        cursor_savedirs = {}

        def lua_value(value):
            if isinstance(value, (dict, list)):
                return lua.table_from(value, recursive=True)
            return value

        def new_cursor(_confdir=None, savedir=None):
            identifier = len(cursor_states) + 1
            cursor_states[identifier] = copy.deepcopy(self.persisted)
            cursor_savedirs[identifier] = savedir
            self.sections = cursor_states[identifier]
            self.events.append(("cursor", identifier, savedir))
            return identifier

        def get_first(cursor, _config, section_type, key=None, default=None):
            for sid, values in cursor_states[cursor].items():
                if values[".type"] == section_type:
                    return lua_value(values.get(key, default)) if key else sid
            return default

        def get(cursor, _config, sid, key=None):
            values = cursor_states[cursor].get(sid)
            return values.get(key) if values and key else (values[".type"] if values else None)

        def get_all(cursor, _config, sid):
            values = cursor_states[cursor].get(sid)
            return lua_value(dict(values, **{".name": sid})) if values else None

        def foreach(cursor, _config, section_type, callback):
            for sid, values in list(copy.deepcopy(cursor_states[cursor]).items()):
                if values[".type"] == section_type:
                    callback(lua_value(dict(values, **{".name": sid})))

        def delete(cursor, _config, sid, key=None):
            self.events.append(("delete", sid, key))
            if key:
                cursor_states[cursor][sid].pop(key, None)
            else:
                cursor_states[cursor].pop(sid, None)
            return True

        def tset(cursor, _config, sid, values):
            cursor_states[cursor][sid].update(self.to_python(values))
            return True

        def set_value(cursor, _config, sid, key, value=None):
            if value is None:
                cursor_states[cursor].setdefault(sid, {})[".type"] = key
                return True
            cursor_states[cursor][sid][key] = self.to_python(value)
            self.events.append(("set", sid, key, value))
            return True

        def section(cursor, _config, section_type, sid=None, values=None):
            if self.fail_add:
                return None
            self.identifier += 1
            sid = sid or f"cfg{self.identifier:06x}"
            cursor_states[cursor][sid] = {".type": section_type}
            if values is not None:
                cursor_states[cursor][sid].update(self.to_python(values))
            return sid

        def commit(cursor, _config):
            state = cursor_states[cursor]
            self.events.append(("commit", state["global"].get("global_server")))
            success = self.commit_statuses.pop(0) if self.commit_statuses else not self.commit_failure
            if not success:
                path = (cursor_savedirs[cursor] or "/tmp/.uci") + "/shadowsocksr"
                self.files[path] = "failed commit left its saved UCI delta"
                return False, "injected UCI commit failure"
            self.sections = state
            self.persisted = copy.deepcopy(state)
            return True

        def revert(cursor, _config):
            self.events.append(("revert",))
            cursor_states[cursor] = copy.deepcopy(self.persisted)
            self.sections = cursor_states[cursor]
            return True

        def unload(cursor, _config):
            self.events.append(("unload", cursor))
            cursor_states[cursor] = copy.deepcopy(self.persisted)
            self.sections = cursor_states[cursor]
            return True

        def json_parse(value):
            try:
                return lua_value(json.loads(value))
            except (TypeError, ValueError):
                return None  # luci.jsonc.parse returns nil for malformed JSON.

        def decode(value):
            try:
                value = value.rstrip("=")
                return base64.b64decode(value + "=" * (-len(value) % 4), validate=True).decode()
            except (ValueError, UnicodeDecodeError):
                return None

        def write(path, value):
            self.files[path] = value
            self.events.append(("write", path, value))
            return True

        def exit_script(code=0):
            raise ScriptExit(code)

        def parse_url(value):
            # URL is an unavailable module boundary, not subscriber logic.
            # Preserve ordinary URL components and decoded query parameters.
            parsed = urlsplit(value)
            return lua_value({"scheme": parsed.scheme, "host": parsed.hostname,
                              "port": parsed.port, "user": parsed.username,
                              "password": parsed.password, "fragment": parsed.fragment,
                              "query": dict(parse_qsl(parsed.query, keep_blank_values=True))})

        g.py_exec, g.py_call = self.shell_exec, self.shell_call
        g.py_url_parse = parse_url
        g.py_json_parse = json_parse
        g.py_json_stringify = lambda value: json.dumps(self.to_python(value), sort_keys=True, separators=(",", ":"))
        g.py_b64decode, g.py_b64encode = decode, lambda value: base64.b64encode(value.encode()).decode()
        g.py_write, g.py_read = write, lambda path: self.files.get(path)
        g.py_access, g.py_remove = lambda path: path in self.files, lambda path: self.files.pop(path, None) is not None
        g.py_exit = exit_script
        g.py_log = lambda value: self.logs.append(value)
        g.py_new_cursor = new_cursor
        g.py_lock_open = lambda path, mode: (self.events.append(("lock-open", path, mode)) or
                                            not self.lock_open_failure)
        g.py_lock = lambda mode: (self.events.append(("lock", mode)) or self.lock_available)
        g.py_lock_close = lambda: (self.events.append(("lock-close",)) or True)
        for key, callback in {"get_first": get_first, "get": get, "foreach": foreach, "delete": delete,
                              "tset": tset, "set": set_value, "section": section, "add": section,
                              "get_all": get_all, "commit": commit, "revert": revert, "unload": unload}.items():
            g["py_" + key] = callback
        g.py_changes = lambda cursor, _config: lua_value({"shadowsocksr": self.shared_changes} if self.shared_changes else {})
        lua.execute(r'''
luci = {sys={exec=function(c) return py_exec(c) end, call=function(c) return py_call(c) end},
        jsonc={parse=function(s) return py_json_parse(s) end,
               stringify=function(s) return py_json_stringify(s) end}, model={}}
luci.sys.init = {stop=function(name) return py_call("/etc/init.d/" .. name .. " stop") end,
                 start=function(name) return py_call("/etc/init.d/" .. name .. " start") end}
nixio = {bin={b64decode=function(s) return py_b64decode(s) end,
              b64encode=function(s) return py_b64encode(s) end},
         open=function(path, mode)
             if not py_lock_open(path, mode) then return nil end
             return {lock=function(self, flag) return py_lock(flag) end,
                     close=function(self) return py_lock_close() end}
         end,
         fs={access=function(p) return py_access(p) end, readfile=function(p) return py_read(p) end,
             writefile=function(p,s) return py_write(p,s) end, remove=function(p) return py_remove(p) end}}
local native_uci = {cursor=function(confdir, savedir)
    local cursor = {_id=py_new_cursor(confdir, savedir)}
    for _, method in ipairs({"get", "get_all", "foreach", "delete", "set", "add", "commit", "revert", "unload", "changes"}) do
        cursor[method] = function(self, ...) return _G["py_" .. method](self._id, ...) end
    end
    return cursor
end
}
luci.model.uci = {cursor=function() error("subscription must not use the shared LuCI RPC cursor") end}
package.preload["uci"] = function() return native_uci end
for _, module in ipairs({"luci.sys", "luci.jsonc", "luci.model.uci", "nixio"}) do
    package.preload[module] = function() return module == "nixio" and nixio or
        (module == "luci.sys" and luci.sys or (module == "luci.jsonc" and luci.jsonc or luci.model.uci)) end
end
package.preload["luci.util"] = function() return {} end
package.preload["url"] = function() return {parse=function(s) return py_url_parse(s) end} end
os.exit = function(code) py_exit(code or 0) end
print = function(value) py_log(value) end
''')
        try:
            lua.execute(self.source)
            return 0
        except ScriptExit as result:
            return result.code

    def test_removed_global_selection_is_committed_before_one_checked_restart(self):
        self.assertEqual(self.run_subscriber(), 0)
        services = [event for event in self.events if event[0] == "service"]
        self.assertEqual([event[1] for event in services], ["restart"])
        self.assertTrue(services[0][3], "restart observed a selected server absent from committed UCI")
        self.assertFalse(services[0][4].rstrip().endswith("&"))
        self.assertEqual(len([event for event in self.events if event[0] == "commit"]), 1)
        self.assertNotEqual(self.persisted["global"]["global_server"], "old_a")
        self.assertTrue(any(node.get("server") == "new.example" for node in self.server_nodes().values()))
        marker_write = next(index for index, event in enumerate(self.events)
                            if event[:2] == ("write", "/tmp/sub_md5_" + group_hash(URL_A)))
        service_index = next(index for index, event in enumerate(self.events) if event[0] == "service")
        commit_index = next(index for index, event in enumerate(self.events) if event[0] == "commit")
        self.assertLess(commit_index, service_index)
        self.assertLess(service_index, marker_write)

    def test_proxy_mode_also_uses_one_synchronous_restart(self):
        self.sections["subscribe"]["proxy"] = "1"
        self.assertEqual(self.run_subscriber(), 0)
        self.assertEqual([event[1] for event in self.events if event[0] == "service"], ["restart"])
        self.assertFalse(any(command.rstrip().endswith("&") for command in self.commands
                             if "/etc/init.d/" in command))

    def test_failed_group_survives_another_groups_success(self):
        self.sections["subscribe"]["subscribe_url"] = [URL_A, URL_B]
        self.http_codes[URL_B] = 503
        old_b = copy.deepcopy(self.sections["old_b"])
        manual = copy.deepcopy(self.sections["manual"])
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections["old_b"], old_b)
        self.assertEqual(self.sections["manual"], manual)
        self.assertNotIn("old_a", self.sections)
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_B), self.files)

    def test_http_200_error_page_is_rejected_and_identical_response_retries(self):
        self.downloads[URL_A] = "<html><body>temporary subscription failure</body></html>"
        old = copy.deepcopy(self.sections)
        for _ in range(2):
            self.assertNotEqual(self.run_subscriber(), 0)
            self.assertEqual(self.sections, old)
            self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)
        self.assertEqual(len([event for event in self.events if event == ("download", URL_A)]), 2)
        self.assertFalse(any(event[0] in ("commit", "service") for event in self.events))

    def test_fully_filtered_candidate_keeps_old_group_and_no_md5(self):
        self.downloads[URL_A] = subscription(alias="Filtered")
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections, old)
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)

    def test_empty_http_200_body_preserves_old_nodes_without_service_action(self):
        self.downloads[URL_A] = ""
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections, old)
        self.assertFalse(any(event[0] in ("commit", "service") for event in self.events))

    def test_empty_json_candidate_cannot_delete_old_nodes(self):
        self.downloads[URL_A] = '{"servers": []}'
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections, old)
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)

    def test_failed_group_retries_after_other_groups_success_without_losing_nodes(self):
        self.sections["subscribe"]["subscribe_url"] = [URL_A, URL_B]
        self.downloads[URL_B] = "<html>server error</html>"
        self.assertNotEqual(self.run_subscriber(), 0)
        old_b = copy.deepcopy(self.sections["old_b"])
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections["old_b"], old_b)
        self.assertEqual(sum(node.get("server") == "new.example" for node in self.server_nodes().values()), 1)
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_B), self.files)
        self.downloads[URL_B] = subscription("new-b.example", "New B")
        self.assertEqual(self.run_subscriber(), 0)
        self.assertNotIn("old_b", self.sections)
        self.assertEqual(sum(node.get("server") == "new.example" for node in self.server_nodes().values()), 1)
        self.assertEqual(sum(node.get("server") == "new-b.example" for node in self.server_nodes().values()), 1)

    def test_existing_manual_global_selection_is_retained_with_one_restart(self):
        self.sections["global"]["global_server"] = "manual"
        self.assertEqual(self.run_subscriber(), 0)
        services = [event for event in self.events if event[0] == "service"]
        self.assertEqual([(event[1], event[2], event[3]) for event in services], [("restart", "manual", True)])
        self.assertFalse(services[0][4].rstrip().endswith("&"))

    def test_malformed_group_does_not_abort_another_valid_group(self):
        self.sections["subscribe"]["subscribe_url"] = [URL_B, URL_A]
        self.downloads[URL_B] = "ssd://" + base64.b64encode(b"not-json").decode()
        old_b = copy.deepcopy(self.sections["old_b"])
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections["old_b"], old_b)
        self.assertNotIn("old_a", self.sections)
        self.assertIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)

    def test_failed_commit_preserves_markers_and_does_not_restart(self):
        self.commit_failure = True
        marker = "/tmp/sub_md5_" + group_hash(URL_A)
        self.files[marker] = "previous-successful-content"
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertEqual(self.sections, old)
        self.assertEqual(self.files[marker], "previous-successful-content")
        self.assertFalse(any(event[0] == "service" for event in self.events))

    def test_failed_node_creation_cannot_commit_deletion_or_advance_md5(self):
        self.fail_add = True
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertEqual(self.sections, old)
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)
        self.assertFalse(any(event[0] == "service" for event in self.events))

    def test_restart_failure_is_reported_and_unchanged_response_retries(self):
        self.restart_statuses = [1, 0]
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)
        self.restart_status = 0
        self.assertEqual(self.run_subscriber(), 0)
        services = [event for event in self.events if event[0] == "service"]
        self.assertEqual([event[1] for event in services], ["restart", "restart", "restart"])
        self.assertIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)

    def test_ordinary_restart_failure_restores_old_choice_and_nodes_before_recovery(self):
        self.restart_statuses = [1, 0]
        self.files["/tmp/sub_md5_" + group_hash(URL_A)] = "old-successful-md5"
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertEqual(self.sections, old)
        self.assertEqual(self.files["/tmp/sub_md5_" + group_hash(URL_A)], "old-successful-md5")
        services = [event for event in self.events if event[0] == "service"]
        self.assertEqual(len(services), 2)
        self.assertEqual(services[-1][1:4], ("restart", "old_a", True))
        self.assertFalse(any(event[4].rstrip().endswith("&") for event in services))
        self.assertEqual([event[1] for event in self.events if event[0] == "commit"], ["old_b", "old_a"])

    def test_recovery_restart_failure_keeps_restored_config_and_reports_degraded_service(self):
        self.restart_statuses = [1, 1]
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertTrue(any("recovery restart failed" in log for log in self.logs))
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)

    def test_rollback_commit_failure_is_reported_without_false_recovery_restart(self):
        self.restart_statuses = [1]
        self.commit_statuses = [True, False]
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertNotEqual(self.persisted, old)
        self.assertEqual(len([event for event in self.events if event[0] == "service"]), 1)
        self.assertTrue(any("rollback commit failed" in log for log in self.logs))
        self.assertNotIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)
        self.assertEqual(self.run_subscriber(), 0)
        self.assertIn("/tmp/sub_md5_" + group_hash(URL_A), self.files)

    def test_rollback_preserves_concurrent_manual_nodes_and_unrelated_global_options(self):
        self.restart_statuses = [1, 0]
        old_a = copy.deepcopy(self.sections["old_a"])

        def concurrent_manual_changes():
            self.persisted["manual"]["alias"] = "Edited concurrently"
            self.persisted["global"]["unrelated_company_option"] = "keep"
            self.persisted["new_manual"] = {".type": "servers", "server": "another.example", "alias": "Added concurrently"}

        self.service_callback = concurrent_manual_changes
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted.get("old_a"), old_a)
        self.assertEqual(self.persisted["global"]["global_server"], "old_a")
        self.assertEqual(self.persisted["global"]["unrelated_company_option"], "keep")
        self.assertEqual(self.persisted["manual"]["alias"], "Edited concurrently")
        self.assertEqual(self.persisted["new_manual"]["alias"], "Added concurrently")

    def test_concurrent_global_selection_conflict_is_reported_without_clobber(self):
        self.restart_statuses = [1]
        self.service_callback = lambda: self.persisted["global"].update(global_server="manual")
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted["global"]["global_server"], "manual")
        self.assertEqual(len([event for event in self.events if event[0] == "commit"]), 1)
        self.assertEqual(len([event for event in self.events if event[0] == "service"]), 1)
        self.assertTrue(any("rollback conflict" in log for log in self.logs))

    def test_concurrent_edit_to_new_subscription_node_is_not_deleted_on_rollback(self):
        self.restart_statuses = [1]

        def edit_new_node():
            for section in self.persisted.values():
                if section.get("server") == "new.example":
                    section["alias"] = "User changed after commit"

        self.service_callback = edit_new_node
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertTrue(any(section.get("alias") == "User changed after commit" for section in self.persisted.values()))
        self.assertTrue(any("rollback conflict" in log for log in self.logs))
        self.assertEqual(len([event for event in self.events if event[0] == "commit"]), 1)

    def test_deleted_node_id_recreated_by_user_is_reported_as_rollback_conflict(self):
        self.restart_statuses = [1]

        def recreate_deleted_id():
            self.persisted["old_a"] = {".type": "servers", "server": "user-replacement.example", "alias": "User replacement"}

        self.service_callback = recreate_deleted_id
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted["old_a"]["server"], "user-replacement.example")
        self.assertTrue(any("rollback conflict" in log for log in self.logs))
        self.assertEqual(len([event for event in self.events if event[0] == "commit"]), 1)

    def test_deleted_node_snapshot_restores_opaque_options_and_uci_lists(self):
        self.sections["old_a"]["user_option"] = "retained"
        self.sections["old_a"]["routes"] = ["192.0.2.0/24", "198.51.100.0/24"]
        self.restart_statuses = [1, 0]
        old_a = copy.deepcopy(self.sections["old_a"])
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted.get("old_a"), old_a)

    def test_failed_group_and_its_concurrent_manual_edit_survive_rollback(self):
        self.sections["subscribe"]["subscribe_url"] = [URL_A, URL_B]
        self.http_codes[URL_B] = 503
        self.restart_statuses = [1, 0]
        old_a = copy.deepcopy(self.sections["old_a"])
        self.service_callback = lambda: self.persisted["old_b"].update(alias="Edited failed group")
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted.get("old_a"), old_a)
        self.assertEqual(self.persisted["old_b"]["alias"], "Edited failed group")

    def test_existing_node_rolls_back_only_written_fields_and_keeps_new_unrelated_option(self):
        self.assertEqual(self.run_subscriber(), 0)
        sid = next(sid for sid, section in self.sections.items() if section.get("server") == "new.example")
        self.sections[sid]["local_port"] = 5678
        self.files.pop("/tmp/sub_md5_" + group_hash(URL_A))
        self.restart_statuses = [1, 0]
        self.service_callback = lambda: self.persisted[sid].update(user_note="concurrent annotation")
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted[sid]["local_port"], 5678)
        self.assertEqual(self.persisted[sid]["user_note"], "concurrent annotation")

    def test_busy_subscription_writer_guard_rejects_before_reading_or_mutating_config(self):
        self.lock_available = False
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertFalse(any(event[0] in ("cursor", "download", "commit", "service") for event in self.events))
        self.assertIn(("lock-close",), self.events)

    def test_lock_open_failure_rejects_before_any_subscription_work(self):
        self.lock_open_failure = True
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertFalse(any(event[0] in ("cursor", "download", "commit", "service") for event in self.events))

    def test_subscription_guard_closes_after_success_and_ordinary_rollback(self):
        self.assertEqual(self.run_subscriber(), 0)
        self.assertIn(("lock", "tlock"), self.events)
        self.assertEqual(self.events.count(("lock-close",)), 1)
        self.files.pop("/tmp/sub_md5_" + group_hash(URL_A))
        self.restart_statuses = [1, 0]
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.events.count(("lock-close",)), 2)

    def test_failed_commit_journal_uses_owned_savedir_and_is_cleaned(self):
        self.commit_failure = True
        self.files["/tmp/.uci/network"] = "other client's pending network edits"
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertNotIn("/tmp/.uci/shadowsocksr", self.files)
        self.assertEqual(self.files["/tmp/.uci/network"], "other client's pending network edits")
        self.assertTrue(self.scratch)
        self.assertFalse(any(path.startswith("/tmp/ssr-subscribe.") for path in self.files))

    def test_existing_shared_pending_changes_are_not_committed_by_subscription(self):
        self.shared_changes = {"manual": {"alias": "Uncommitted user edit"}}
        old = copy.deepcopy(self.sections)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted, old)
        self.assertFalse(any(event[0] in ("download", "commit", "service") for event in self.events))
        self.assertTrue(any("shared UCI changes" in log for log in self.logs))

    def test_shared_pending_edits_during_activation_block_recovery_without_consuming_them(self):
        self.restart_statuses = [1]
        pending = {"manual": {"alias": "Pending concurrent edit"}}
        self.service_callback = lambda: setattr(self, "shared_changes", pending)
        self.assertNotEqual(self.run_subscriber(), 0)
        self.assertEqual(self.shared_changes, pending)
        self.assertTrue(any("rollback conflict" in log for log in self.logs))
        self.assertEqual(len([event for event in self.events if event[0] == "commit"]), 1)

    def test_unchanged_valid_group_keeps_nodes_and_does_not_restart(self):
        self.files["/tmp/sub_md5_" + group_hash(URL_A)] = hashlib.md5(self.downloads[URL_A].encode()).hexdigest()
        old = copy.deepcopy(self.sections)
        self.assertEqual(self.run_subscriber(), 0)
        self.assertEqual(self.sections, old)
        self.assertFalse(any(event[0] in ("commit", "service") for event in self.events))

    def test_manual_section_with_only_one_legacy_hash_is_preserved(self):
        self.sections["manual"]["hashkey"] = "manual-note"
        manual = copy.deepcopy(self.sections["manual"])
        self.assertEqual(self.run_subscriber(), 0)
        self.assertIn("manual", self.sections)
        self.assertEqual(self.sections["manual"], manual)

    def test_disabled_global_remains_disabled_without_service_action(self):
        self.sections["global"]["global_server"] = "nil"
        self.assertEqual(self.run_subscriber(), 0)
        self.assertEqual(self.persisted["global"]["global_server"], "nil")
        self.assertFalse(any(event[0] == "service" for event in self.events))


if __name__ == "__main__":
    unittest.main()
