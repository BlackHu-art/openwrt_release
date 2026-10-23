#!/usr/bin/env python3
"""Exercise current fw876 update policy with real shell, Lua and UI JavaScript.

External HTTP and package-manager operations use isolated files. Set
SSR_V198_UPDATES_UNPATCHED=1 to reproduce the upstream revision/policy failures.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from lupa.lua51 import LuaRuntime
from test_ssrplus_v198 import prepare_source

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "maintenance/plugins/ssrplus/upstream-v198.2/luci-app-ssr-plus"
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
NODE = shutil.which("node")
if os.name == "nt" and not NODE:
    NODE = str(Path(os.environ["LOCALAPPDATA"]) / "openwrt-release-test-deps/node-v22.23.4-win-x64/node.exe")


class SSRUpdatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="ssr-update-policy-source-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.package = Path(cls.temporary.name)
        shutil.copytree(UPSTREAM, cls.package, dirs_exist_ok=True)
        if not os.environ.get("SSR_V198_UPDATES_UNPATCHED"):
            result = prepare_source(cls.package)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)

    def run_updater(self, action="xray_info", manager="opkg", installed="26.10.21-2",
                    binary="26.10.21", latest="26.10.21-r3", package_state="install ok installed"):
        # The production code may restart a router service only after installation;
        # refuse router hosts rather than allowing this fixture to operate on one.
        if any(Path(path).exists() for path in ("/etc/init.d/shadowsocksr", "/etc/init.d/rpcd", "/etc/init.d/uhttpd")):
            raise AssertionError("updater tests require an isolated non-router host")
        source = (self.package / "root/usr/share/shadowsocksr/update_components.sh").read_text(encoding="utf-8")
        source = source[:source.index('case "${1:-}" in')]
        with tempfile.TemporaryDirectory(prefix="ssr-update-policy-run-") as temporary:
            base = Path(temporary)
            (base / "package-version").write_text(installed, encoding="utf-8")
            (base / "binary-version").write_text(binary, encoding="utf-8")
            core = base / "xray"
            core.write_text('#!/bin/sh\nprintf "Xray %s fw876 fixture\\n" "$(cat "$TEST_ROOT/binary-version")"\n', encoding="utf-8", newline="\n")
            core.chmod(0o755)
            source += r'''
XRAY_BINARY="$TEST_ROOT/xray"
detect_package_manager() { printf '%s' "$TEST_MANAGER"; }
get_openwrt_arch() { printf 'x86_64'; }
get_component_mirror() { printf 'direct'; }
effective_url() {
    printf 'request %s\n' "$1" >> "$TEST_ROOT/events"
    [ "$1" = 'https://github.com/fw876/helloworld/releases/latest' ] || return 98
    printf 'https://github.com/fw876/helloworld/releases/tag/v198.2'
}
fetch_text() {
    printf 'request %s\n' "$1" >> "$TEST_ROOT/events"
    [ "$1" = 'https://github.com/fw876/helloworld/releases/expanded_assets/v198.2' ] || return 98
    printf '<a href="/fw876/helloworld/releases/download/v198.2/xray-core_%s_x86_64.ipk">ipk</a>\n' "$TEST_LATEST"
    printf '<a href="/fw876/helloworld/releases/download/v198.2/xray-core-%s_x86_64.apk">apk</a>\n' "$TEST_LATEST"
    printf '%s\n' '<a href="/fw876/helloworld/releases/download/v198.2/luci-app-ssr-plus_999.3-r1_all.ipk">main</a>'
    printf '%s\n' '<a href="/fw876/helloworld/releases/download/v198.2/luci-app-ssr-plus-999.3-r1.apk">main</a>'
}
download_file() {
    printf 'download %s\n' "$1" >> "$TEST_ROOT/events"
    printf 'verified fixture package\n' > "$2"
}
mock_install() {
    printf 'install %s\n' "$1" >> "$TEST_ROOT/events"
    printf '%s' "$TEST_LATEST" > "$TEST_ROOT/package-version"
    printf '%s' "$TEST_LATEST" | sed 's/-r[0-9][0-9]*$//' > "$TEST_ROOT/binary-version"
}
opkg() {
    case "$1:$2" in
        status:xray-core) [ -s "$TEST_ROOT/package-version" ] || return 1; printf 'Package: xray-core\nVersion: %s\nStatus: %s\n' "$(cat "$TEST_ROOT/package-version")" "$TEST_PACKAGE_STATE";;
        status:luci-app-ssr-plus) printf 'Package: luci-app-ssr-plus\nVersion: 198.2-1\nStatus: install ok installed\n';;
        install:*) mock_install "$2";;
        *) printf 'unexpected opkg %s\n' "$*" >> "$TEST_ROOT/events"; return 98;;
    esac
}
apk() {
    case "$1:$2:$3" in
        list:-I:xray-core) [ -s "$TEST_ROOT/package-version" ] || return 1; printf 'xray-core-%s x86_64 {feeds/packages} (MPL-2.0) [installed]\n' "$(cat "$TEST_ROOT/package-version")";;
        info:-e:luci-app-ssr-plus|list:-I:luci-app-ssr-plus) printf 'luci-app-ssr-plus-198.2-r1\n';;
        add:--allow-untrusted:*) mock_install "$3";;
        *) printf 'unexpected apk %s\n' "$*" >> "$TEST_ROOT/events"; return 98;;
    esac
}
mktemp() {
    [ "$1" = '-d' ] || return 98
    case "$2" in /tmp/ssrplus-xray.*|/tmp/ssrplus-mainprogram.*) command mktemp -d "$TEST_ROOT/stage.XXXXXX";; *) return 98;; esac
}
"$TEST_ACTION"
'''
            runner = base / "runner.sh"
            runner.write_text(source, encoding="utf-8", newline="\n")
            root = base.as_posix()
            if os.name == "nt":
                root = subprocess.check_output([BASH, "-c", 'cygpath -u "$1"', "path", str(base)], text=True, timeout=20).strip()
            env = dict(os.environ, TEST_ROOT=root, TEST_ACTION=action, TEST_MANAGER=manager,
                       TEST_LATEST=latest, TEST_PACKAGE_STATE=package_state, MSYS_NO_PATHCONV="1")
            result = subprocess.run([BASH, str(runner)], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = (base / "events").read_text().splitlines() if (base / "events").exists() else []
            self.assertFalse(any(item.startswith("unexpected") for item in events), events)
            values = dict(line.split("=", 1) for line in result.stdout.splitlines())
            return values, events

    def test_same_core_revision_upgrade_is_available_and_installed(self):
        for manager, installed in (("opkg", "26.10.21-2"), ("apk", "26.10.21-r2")):
            with self.subTest(manager=manager):
                values, _ = self.run_updater(manager=manager, installed=installed)
                self.assertEqual(values["can_upgrade"], "1")
                self.assertEqual(values["current_version"], "26.10.21")
                self.assertEqual(values.get("current_package_version"), installed)
                self.assertEqual(values["latest_version"], "26.10.21-r3")
                values, events = self.run_updater("xray_upgrade", manager, installed)
                self.assertEqual(values["success"], "1")
                self.assertEqual(len([event for event in events if event.startswith("install ")]), 1)
                self.assertEqual(values.get("current_package_version"), "26.10.21-r3")

    def test_same_package_revision_skips_download_for_both_suffix_styles(self):
        for manager, installed in (("opkg", "26.10.21-3"), ("apk", "26.10.21-r3")):
            for action in ("xray_info", "xray_upgrade"):
                with self.subTest(manager=manager, action=action):
                    values, events = self.run_updater(action, manager, installed)
                    self.assertEqual(values.get("can_upgrade", "0"), "0")
                    self.assertFalse(any(event.startswith(("install ", "download ")) for event in events))

    def test_newer_and_older_core_versions_keep_correct_order(self):
        for latest, expected in (("26.10.22-r1", "1"), ("26.10.20-r99", "0"), ("26.10.21-r10", "1")):
            with self.subTest(latest=latest):
                values, _ = self.run_updater(latest=latest)
                self.assertEqual(values["can_upgrade"], expected)

    def test_missing_package_metadata_restores_management_without_downgrade(self):
        for binary, expected in (("26.10.21", "1"), ("26.10.20", "1"), ("26.10.22", "0")):
            with self.subTest(binary=binary):
                values, _ = self.run_updater(installed="", binary=binary)
                self.assertEqual(values["current_version"], binary)
                self.assertEqual(values.get("current_package_version"), "")
                self.assertEqual(values["can_upgrade"], expected)

    def test_opkg_removed_package_record_does_not_hide_untracked_binary(self):
        values, _ = self.run_updater(installed="26.10.21-3", package_state="deinstall ok config-files")
        self.assertEqual(values["current_package_version"], "")
        self.assertEqual(values["can_upgrade"], "1")

    def test_mainprogram_requests_never_fetch_or_install_unmanaged_package(self):
        for action in ("mainprogram_info", "mainprogram_local_info", "mainprogram_upgrade"):
            with self.subTest(action=action):
                values, events = self.run_updater(action)
                self.assertEqual(events, [])
                self.assertEqual(values["error"], "managed_update")
                self.assertEqual(values.get("can_upgrade", "0"), "0")
                if action == "mainprogram_upgrade":
                    self.assertEqual(values["success"], "0")
                else:
                    self.assertEqual(values["current_version"], "198.2-1")

    def test_mainprogram_http_request_is_refused_and_revision_metadata_survives(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        commands = []
        def execute(command):
            action = re.search(r"'(mainprogram_(?:upgrade|info)|xray_info)' 2>/dev/null$", command)[1]
            values, events = self.run_updater(action)
            commands.extend(events)
            return "\n".join(key + "=" + value for key, value in values.items())
        lua.globals().py_exec = execute
        lua.execute('''module=function() end
local empty={}; require=function(name)
    if name=="luci.i18n" then return {translate=function(s) return s end} end
    if name=="luci.model.uci" then return {cursor=function() return {} end} end
    return empty
end
component="mainprogram"
luci={http={formvalue=function(key) return key=="component" and component or "direct" end,
    prepare_content=function() end, write_json=function(data) response=data end},
    sys={exec=py_exec},util={shellquote=function(s) return "'"..s.."'" end}}
''')
        lua.execute((self.package / "luasrc/controller/shadowsocksr.lua").read_bytes())
        lua.globals().component_upgrade()
        self.assertFalse(lua.globals().response["success"])
        self.assertEqual(lua.globals().response["error"], "managed_update")
        self.assertEqual(commands, [])
        lua.globals().component = "xray"
        lua.globals().component_status()
        self.assertEqual(lua.globals().response["current_package_version"], "26.10.21-2")

    def test_ui_disables_mainprogram_upgrade_even_for_stale_status_and_keeps_xray(self):
        source = (self.package / "luasrc/view/shadowsocksr/component.htm").read_text(encoding="utf-8")
        script = re.search(r'<script[^>]*>([\s\S]*?)</script>', source)[1]
        script = re.sub(r'<%:([\s\S]*?)%>', lambda match: match[1], script)
        script = re.sub(r'<%=[\s\S]*?%>', '/fixture', script)
        harness = '''const vm=require('vm');
const elements={}; const requests=[];
const context={window:{setTimeout(){}},document:{getElementById(id){return elements[id]||(elements[id]={});}},
XHR:{get(...args){requests.push(args);}}};
vm.createContext(context); vm.runInContext(SOURCE,context);
elements['component-selector']={value:'mainprogram'};
context.renderComponentInfo({component:'mainprogram',current_version:'198.2-1',latest_version:'999',can_upgrade:true},true);
if (!elements['component-upgrade'].disabled) throw Error('mainprogram upgrade is enabled');
context.queryComponentInfo(elements['component-upgrade'],true);
if (requests.length) throw Error('mainprogram upgrade sent an HTTP request');
elements['component-selector'].value='xray';
context.renderComponentInfo({component:'xray',current_version:'26.10.21',current_package_version:'26.10.21-r2',latest_version:'26.10.21-r3',can_upgrade:true},true);
if (elements['component-upgrade'].disabled) throw Error('Xray upgrade is disabled');
if (!elements['component-status'].innerHTML.includes('26.10.21-r2')) throw Error('package revision is hidden');
context.queryComponentInfo(elements['component-upgrade'],true);
if (requests.length!==1 || requests[0][1].component!=='xray') throw Error('Xray update no longer reaches the backend');
'''.replace("SOURCE", json.dumps(script))
        result = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
