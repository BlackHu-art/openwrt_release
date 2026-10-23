"""UCI/HTTP/OS boundaries for the full current fw876 subscription program."""
import base64
import copy
import hashlib
import json
import re
import shlex

from test_ssrplus_subscription import neturl_source
from test_ssrplus_v198 import LuaRuntime, lua_to_python, prepared_source

URL = "https://fixture.invalid/subscription"


class SubscriptionHarness:
    def __init__(self):
        self.sections = {
            "global": {".type": "global", "global_server": "nil"},
            "subscribe": {".type": "server_subscribe", "subscribe_url": [URL],
                          "proxy": "1", "filter_words": "", "enable_mihomo": "0"},
            "manual": {".type": "servers", "alias": "Manual", "server": "manual.invalid", "server_port": "443"},
        }
        self.persisted = copy.deepcopy(self.sections)
        self.files, self.logs, self.commands = {}, [], []
        self.payload = ""
        self.cores = {"xray", "sslocal"}

    def execute(self, command):
        self.commands.append(command)
        if command.startswith("type -t -p "):
            for binary in re.findall(r"type -t -p ([\w-]+)", command):
                if binary in self.cores:
                    return "/usr/bin/" + binary + "\n"
            return ""
        if command.startswith("curl "):
            if shlex.split(command)[-1] != URL:
                raise AssertionError("unexpected download URL")
            return self.payload
        if command.startswith("echo "):
            data = " ".join(shlex.split(command.split(" | ", 1)[0])[1:]) + "\n"
            return hashlib.md5(data.encode()).hexdigest() + "\n"
        match = re.fullmatch(r'md5sum "([^"]+)" 2>/dev/null \| cut -d " " -f1', command)
        if match:
            return hashlib.md5(self.files[match[1]].encode()).hexdigest() + "\n"
        raise AssertionError("unexpected subscription command: " + command)

    def call(self, command):
        if not re.fullmatch(r"/etc/init.d/shadowsocksr (start|stop|restart) > /dev/null 2>&1 &", command):
            raise AssertionError("unexpected subscription process call: " + command)
        self.commands.append(command)
        return 0

    def run(self, uris):
        # The caller's input models already committed UCI before invocation.
        self.persisted = copy.deepcopy(self.sections)
        self.payload = base64.b64encode("\n".join(uris).encode()).decode()
        lua = LuaRuntime(unpack_returned_tuples=True)
        g = lua.globals()
        def value(item):
            return lua.table_from(item, recursive=True) if isinstance(item, (dict, list)) else item
        def parse(text):
            try:
                return value(json.loads(text))
            except ValueError:
                return None
        def decode(text):
            try:
                return base64.b64decode(text + "=" * (-len(text) % 4), validate=True).decode()
            except (ValueError, UnicodeDecodeError):
                return None
        def write(path, text):
            self.files[path] = text
            return True
        def commit(state):
            self.persisted = copy.deepcopy(lua_to_python(state))
            return True
        g.sections = value(copy.deepcopy(self.sections))
        g.py_exec, g.py_call = self.execute, self.call
        g.py_parse, g.py_decode = parse, decode
        g.py_stringify = lambda item: json.dumps(lua_to_python(item), sort_keys=True, separators=(",", ":"))
        g.py_encode = lambda text: base64.b64encode(text.encode()).decode()
        g.py_read = lambda path: self.files.get(path)
        g.py_write = write
        g.py_access = lambda path: path in self.files
        g.py_remove = lambda path: self.files.pop(path, None) is not None
        g.py_dir = lambda: value([path[5:] for path in self.files if path.startswith("/tmp/")])
        g.py_log, g.py_commit = self.logs.append, commit
        g.py_neturl_source = neturl_source()
        lua.execute('''
local next_id = 0
local cursor = {}
function cursor:get_first(config, kind, option, default)
    for sid, section in pairs(sections) do
        if section[".type"] == kind then
            if not option then return sid end
            if section[option] == nil then return default end
            return section[option]
        end
    end
    return default
end
function cursor:get(config, sid, option)
    local section = sections[sid]
    if section then return section[option or ".type"] end
end
function cursor:foreach(config, kind, callback)
    local ids = {}
    for sid, section in pairs(sections) do if section[".type"] == kind then ids[#ids+1] = sid end end
    table.sort(ids)
    for _, sid in ipairs(ids) do
        local copy = {}; for k,v in pairs(sections[sid]) do copy[k]=v end
        copy[".name"] = sid; callback(copy)
    end
end
function cursor:section(config, kind, sid)
    next_id = next_id + 1
    sid = sid or string.format("cfg%06x", next_id)
    sections[sid] = {[".type"]=kind}; return sid
end
cursor.add = cursor.section
function cursor:tset(config, sid, values) for k,v in pairs(values) do sections[sid][k]=v end; return true end
function cursor:set(config, sid, key, value) sections[sid][key]=value; return true end
function cursor:delete(config, sid, key)
    if key then sections[sid][key]=nil else sections[sid]=nil end; return true
end
function cursor:commit(config) return py_commit(sections) end
luci = {sys={exec=function(c) return py_exec(c) end, call=function(c) return py_call(c) end},
        jsonc={parse=function(s) return py_parse(s) end, stringify=function(s) return py_stringify(s) end},
        model={uci={cursor=function() return cursor end}}}
nixio = {bin={b64decode=function(s) return py_decode(s) end, b64encode=function(s) return py_encode(s) end},
         fs={access=function(p) return py_access(p) end, readfile=function(p) return py_read(p) end,
             writefile=function(p,s) return py_write(p,s) end, remove=function(p) return py_remove(p) end,
             dir=function() local files=py_dir(); local i=0; return function() i=i+1; return files[i] end end}}
package.preload["luci.sys"] = function() return luci.sys end
package.preload["luci.jsonc"] = function() return luci.jsonc end
package.preload["luci.model.uci"] = function() return luci.model.uci end
package.preload["nixio"] = function() return nixio end
package.preload["luci.util"] = function() return {} end
package.preload["url"] = function() return assert(loadstring(py_neturl_source, "@lua-neturl/url.lua"))() end
print = function(text) py_log(text) end
''')
        source = prepared_source()["root/usr/share/shadowsocksr/subscribe.lua"].decode("utf-8")
        lua.execute(source.split("\n", 1)[1])
        self.sections = lua_to_python(g.sections)
        if any("发生错误" in line or "stack traceback" in line for line in self.logs):
            raise AssertionError("v198.2 subscription failed: " + "\n".join(self.logs))
        return {sid: node for sid, node in self.persisted.items() if node.get("grouphashkey")}


def new_subscription_node(uri):
    harness = SubscriptionHarness()
    nodes = harness.run([uri])
    if len(nodes) != 1:
        raise AssertionError("expected one subscribed node: " + "\n".join(harness.logs))
    return next(iter(nodes.values()))
