#!/usr/bin/env python3
"""Execute the real Passwall2 updater against isolated filesystem/network boundaries.

PASSWALL_FW876_UNPATCHED=1 runs the same contracts against upstream for RED evidence.
No downloaded code, router filesystem, package manager or network is executed.
"""
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "maintenance/plugins/passwall2/luci-app-passwall2"
PATCH = ROOT / "wrt_core/patches/passwall2-fw876-core-update.patch"
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
UPDATER = ROOT / "maintenance/plugins/ssrplus/upstream-v198.2/luci-app-ssr-plus/root/usr/share/shadowsocksr/update_components.sh"


def plain(value):
    if hasattr(value, "items"):
        return {key: plain(item) for key, item in value.items()}
    return value


class UpdaterSandbox:
    """Substitute only OS/network bindings; load the complete production Lua files."""

    def __init__(self, package, root, paths=None):
        self.root, self.paths, self.events = root, paths or {}, []
        self.package, self.aliases = package, {}
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.com = self.lua.execute((package / "luasrc/passwall2/com.lua").read_bytes())
        for name in ("xray", "sing-box", "geoview"):
            self.write("/usr/bin/" + name, "fw876-original" if name == "xray" else "old")
        for name, url in (("xray", "https://example.test/xray"),
                          ("passwall2", "https://example.test/luci.ipk")):
            self.write("/tmp/etc/passwall2_tmp/update_" + name + ".json", json.dumps({
                url: "sha256:" + hashlib.sha256(b"official-replacement").hexdigest()}))
        self.write("/tmp/candidate", "official-replacement")
        self.write("/tmp/passwall2_download.fixture1", "official-luci-package")
        self.write("/usr/share/passwall2/luci_update.sh", "official-installer")
        with zipfile.ZipFile(self.local("/tmp/candidate.zip"), "w") as archive:
            archive.writestr("xray", "official-replacement")
        self.g.py_com = self.com
        self.g.py_get = lambda config, section, option=None: (
            "en" if config == "luci" and option == "lang" else self.paths.get(option))
        self.g.py_read = self.read
        self.g.py_write = self.write
        self.g.py_access = lambda path, *args: self.local(path).exists()
        self.g.py_stat = self.stat
        self.g.py_mkdir = lambda path: self.local(path).mkdir(parents=True, exist_ok=True)
        self.g.py_realpath = lambda path: self.aliases.get(path, str(PurePosixPath(path))) if self.local(path).exists() else None
        self.g.py_exec = self.sys_exec
        self.g.py_call = self.sys_call
        self.g.py_spawn = self.spawn
        self.g.py_curl = self.curl
        self.g.py_parse = lambda data: self.lua.table_from(json.loads(data), recursive=True)
        self.g.py_stringify = lambda data: json.dumps(plain(data))
        self.g.py_sha256 = lambda command: (0, hashlib.sha256(
            self.local(shlex.split(command)[1]).read_bytes()).hexdigest() + "  file\n")
        self.lua.execute(r'''
module = function() end
local mt = getmetatable("")
mt.__mod = function(s, args) return string.format(s, unpack(type(args) == "table" and args or {args})) end
package.loaded["luci.passwall2.com"] = py_com
package.loaded.nixio = {uname=function() return {machine="x86_64"} end}
package.loaded["nixio.util"] = {}
package.loaded["nixio.fs"] = {access=py_access, stat=py_stat, readfile=py_read,
    writefile=py_write, mkdirr=py_mkdir, mkdir=py_mkdir, realpath=py_realpath,
    dirname=function(path) return path:match("^(.*)/[^/]*$") end,
    chmod=function() error("unexpected chmod") end}
package.loaded["luci.sys"] = {exec=py_exec, call=py_call}
package.loaded["luci.model.uci"] = {cursor=function() return {
    get=function(self, ...) return py_get(...) end} end}
package.loaded["luci.util"] = {exec=py_exec, shellquote=function(s) return "'" .. s .. "'" end,
    split=function(s) local out={}; for part in s:gmatch("[^%.%-]+") do out[#out+1]=part end; return out end}
package.loaded["luci.cbi.datatypes"] = {}
package.loaded["luci.jsonc"] = {parse=py_parse, stringify=py_stringify}
package.loaded["luci.i18n"] = {setlanguage=function() end,
    translate=function(s) return s end, translatef=string.format}
luci = {sys=package.loaded["luci.sys"], jsonc=package.loaded["luci.jsonc"]}
''')
        self.lua.execute((package / "luasrc/passwall2/api.lua").read_bytes())
        # Router process creation and HTTP are the only replaced API boundaries.
        self.g.exec, self.g.exec_call = self.spawn, self.g.py_sha256
        self.g.curl_auto, self.g.curl_direct = self.curl, self.curl

    def local(self, path):
        if not path or not str(path).startswith("/"):
            raise AssertionError("unexpected path: " + repr(path))
        result = (self.root / path.lstrip("/")).resolve()
        result.relative_to(self.root.resolve())
        return result

    def write(self, path, data):
        target = self.local(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
        return True

    def read(self, path):
        target = self.local(path)
        return target.read_text(encoding="utf-8") if target.is_file() else None

    def stat(self, path, field=None):
        target = self.local(path)
        if not target.exists():
            return None
        data = {"type": "dir" if target.is_dir() else "reg", "size": target.stat().st_size}
        return data.get(field) if field else self.lua.table_from(data)

    def sys_exec(self, command):
        self.events.append(("exec", command))
        if " version |" in command or " -version " in command:
            return "26.8.4"
        if command.startswith("echo -n $(df -k "):
            return "999999"
        if command.startswith("echo -n $(du -k "):
            return "1"
        if command.startswith("echo -n $(command -v "):
            return "/usr/bin/unzip"
        if command.startswith("opkg list-installed luci-app-passwall2 "):
            return "26.10.19"
        if command.startswith("mktemp -d -t "):
            self.local("/tmp/xray_extract.fixture").mkdir(parents=True, exist_ok=True)
            return "/tmp/xray_extract.fixture"
        raise AssertionError("unexpected command: " + command)

    def sys_call(self, command):
        self.events.append(("call", command))
        if command.startswith(("/bin/rm -", "df -k ")):
            return 0
        if command.startswith("busybox pgrep"):
            return 1
        if command.startswith(("command -v apk", "opkg list-installed", "apk info")):
            return 1
        if command.startswith("nohup "):
            return 0
        raise AssertionError("unexpected call: " + command)

    def spawn(self, executable, args, *rest):
        arguments = [args[i] for i in range(1, len(args) + 1)]
        self.events.append(("spawn", executable, arguments))
        operands = [arg for arg in arguments if not arg.startswith("-")]
        if executable == "/bin/rm":
            for path in operands:
                self.local(path).unlink(missing_ok=True)
        elif executable == "/bin/mv":
            self.local(operands[-1]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(self.local(operands[-2]), self.local(operands[-1]))
        elif executable == "/bin/cp":
            shutil.copyfile(self.local(operands[-2]), self.local(operands[-1]))
        elif executable == "/usr/bin/unzip":
            with zipfile.ZipFile(self.local(arguments[1])) as archive:
                archive.extract("xray", self.local(arguments[-1]))
        else:
            raise AssertionError("unexpected process: " + repr((executable, arguments)))
        return 0

    def curl(self, url, destination=None, *args):
        self.events.append(("network", url))
        if destination:
            self.write(destination, "official-replacement")
            return 0, ""
        name = "sing-box" if "sing-box" in url else "geoview" if "geoview" in url else "xray"
        asset = {"name": "linux-amd64-musl" if name == "sing-box" else "linux-amd64" if name == "geoview" else "Xray-linux-64.zip",
                 "browser_download_url": "https://example.test/" + name,
                 "digest": "sha256:" + hashlib.sha256(b"official-replacement").hexdigest()}
        return 0, json.dumps({"tag_name": "v99.0.0", "assets": [asset]})

    def render(self, source):
        """Execute LuCI template expressions/branches with translated literals."""
        code = ["local output = {}; local function emit(s) output[#output+1] = tostring(s) end"]
        offset = 0
        for match in re.finditer(r"<%([\s\S]*?)-?%>", source):
            code.append("emit(" + json.dumps(source[offset:match.start()], ensure_ascii=False) + ")")
            fragment = match[1].rstrip("-")
            if fragment.startswith("="):
                code.append("emit(" + fragment[1:] + ")")
            elif fragment.startswith(":"):
                code.append("emit(" + json.dumps(fragment[1:]) + ")")
            else:
                code.append(fragment)
            offset = match.end()
        code.append("emit(" + json.dumps(source[offset:], ensure_ascii=False) + "); return table.concat(output)")
        self.lua.execute('''self={map={api=_G},com=py_com}; token="fixture"; resource="/static"
translate=function(s) return s end; get_version=function() return "26.10.19" end
url=function(s) return "/admin/services/passwall2/" .. s end
package.loaded["luci.dispatcher"]={build_url=function(...) return "/" .. table.concat({...}, "/") end}
''')
        return self.lua.execute("\n".join(code))

    def request(self, action, component, **form):
        self.g.py_formvalue = form.get
        self.lua.execute('''package.loaded["luci.passwall2.api"] = _G
package.loaded["luci.http"] = {formvalue=py_formvalue,
    prepare_content=function() end, write=function(data) response=data end}
''')
        self.lua.execute((self.package / "luasrc/controller/passwall2.lua").read_bytes())
        self.g[action](component)
        return json.loads(self.g.response)


class PasswallFW876Updates(unittest.TestCase):
    maxDiff = 500
    @classmethod
    def setUpClass(cls):
        cls.prepared = tempfile.TemporaryDirectory(prefix="passwall-fw876-source-")
        cls.addClassCleanup(cls.prepared.cleanup)
        cls.package = Path(cls.prepared.name)
        manifest = json.loads((ROOT / "maintenance/plugins/manifests/passwall2.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            if item["path"] in ("luasrc/passwall2/api.lua", "luasrc/passwall2/com.lua",
                                "luasrc/controller/passwall2.lua", "luasrc/view/passwall2/app_update/app_version.htm"):
                if hashlib.sha256((SOURCE / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                    raise AssertionError("maintenance source drifted: " + item["path"])
        shutil.copytree(SOURCE, cls.package, dirs_exist_ok=True)
        if not os.environ.get("PASSWALL_FW876_UNPATCHED"):
            subprocess.run(["git", "apply", "--directory=" + cls.package.as_posix(),
                            "--unsafe-paths", str(PATCH)], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=20)

    def sandbox(self, **paths):
        temporary = tempfile.TemporaryDirectory(prefix="passwall-fw876-run-")
        self.addCleanup(temporary.cleanup)
        return UpdaterSandbox(self.package, Path(temporary.name), paths)

    def denied(self, sandbox, result):
        self.assertEqual(result["code"], 1, "managed update must be refused")
        self.assertTrue(result["error"], "refusal must explain the supported update route")
        self.assertEqual(sandbox.events, [], "refusal must precede network/process side effects")
        self.assertEqual(sandbox.read("/usr/bin/xray"), "fw876-original")

    def test_direct_xray_entrypoints_refuse_even_with_custom_binary_path(self):
        calls = (("to_check", ("x86_64", "xray")),
                 ("to_download", ("xray", "https://example.test/xray", 1, "fixture")),
                 ("to_download_progress", ("xray", "fixture", 1)),
                 ("to_extract", ("xray", "/tmp/candidate.zip", "zip")),
                 ("to_move", ("xray", "/tmp/candidate")))
        for path in ("/usr/bin/xray", "/tmp/custom-xray"):
            for name, args in calls:
                with self.subTest(path=path, entrypoint=name):
                    box = self.sandbox(xray_file=path)
                    self.denied(box, box.g[name](*args))

    def test_other_components_cannot_install_over_xray_configured_path(self):
        for name, option in (("sing-box", "sing_box_file"), ("geoview", "geoview_file")):
            for target in ("/usr/bin/xray", "/tmp/custom-xray"):
                with self.subTest(component=name, target=target):
                    box = self.sandbox(xray_file="/tmp/custom-xray", **{option: target})
                    self.denied(box, box.g.to_move(name, "/tmp/candidate"))

    def test_other_component_alias_cannot_install_over_shared_xray(self):
        box = self.sandbox(sing_box_file="/usr/bin/xray-alias")
        box.write("/usr/bin/xray-alias", "fixture-symlink")
        # nixio.fs.realpath is a router OS boundary; both existing aliases resolve
        # to the same target, without requiring Windows symlink privileges.
        box.aliases["/usr/bin/xray-alias"] = "/usr/bin/xray"
        self.denied(box, box.g.to_move("sing-box", "/tmp/candidate"))

    def test_http_routes_cannot_bypass_the_component_policy(self):
        for action, form in (("com_check", {}),
                             ("com_update", {"task": "move", "file": "/tmp/candidate"}),
                             ("com_update", {"task": "extract", "file": "/tmp/candidate.zip"}),
                             ("com_update", {"url": "https://example.test/xray", "id": "fixture"})):
            with self.subTest(action=action, form=form):
                box = self.sandbox()
                self.denied(box, box.request(action, "xray", **form))

    def test_other_components_retain_check_download_and_install(self):
        for name in ("sing-box", "geoview"):
            with self.subTest(component=name):
                box = self.sandbox()
                checked = box.g.to_check("x86_64", name)
                self.assertEqual(checked["code"], 0)
                self.assertTrue(checked["has_update"])
                downloaded = box.g.to_download(name, checked["data"]["browser_download_url"], 1, "fixture")
                self.assertEqual(downloaded["code"], 0)
                self.assertEqual(box.g.to_move(name, downloaded["file"])["code"], 0)
                self.assertEqual(box.read("/usr/bin/" + name), "official-replacement")
                self.assertEqual(box.read("/usr/bin/xray"), "fw876-original")

    def test_xray_version_and_configured_binary_path_remain_available(self):
        box = self.sandbox(xray_file="/tmp/custom-xray")
        box.write("/tmp/custom-xray", "fw876-original")
        self.assertEqual(box.g.get_app_path("xray"), "/tmp/custom-xray")
        self.assertEqual(box.g.get_app_version("xray"), "26.8.4")

    def test_ui_retains_versions_and_other_buttons_with_managed_update_link(self):
        box = self.sandbox()
        rendered = box.render((self.package / "luasrc/view/passwall2/app_update/app_version.htm").read_text(encoding="utf-8"))
        self.assertNotIn('data-update-app="xray"', rendered)
        self.assertNotIn('data-update-app="passwall2"', rendered)
        self.assertIn('key="xray"', rendered)
        self.assertIn('data-update-app="sing-box"', rendered)
        self.assertIn('data-update-app="geoview"', rendered)
        self.assertIn('/admin/services/shadowsocksr/component', html.unescape(rendered))
        self.assertIn("fw876", rendered)

    def test_luci_self_update_cannot_replace_managed_policy(self):
        for name, args in (("to_check_self", ()),
                           ("to_download", ("passwall2", "https://example.test/luci.ipk", 1, "fixture1")),
                           ("to_download_progress", ("passwall2", "fixture", 1)),
                           ("to_install_self", ("fixture", "1", ""))):
            with self.subTest(entrypoint=name):
                box = self.sandbox()
                self.denied(box, box.g[name](*args))


class SSRFwReleaseUpdateTests(unittest.TestCase):
    """Run the upstream fw876 asset resolver and failure paths, never install packages."""

    def run_updater(self, manager="opkg", scenario="success", action="get_xray_latest_info"):
        source = UPDATER.read_text(encoding="utf-8")
        source = source[:source.index('case "${1:-}" in')]
        with tempfile.TemporaryDirectory(prefix="fw876-updater-") as temporary:
            base = Path(temporary)
            runner, trace = base / "runner.sh", base / "trace"
            overrides = r'''
get_openwrt_arch() { printf 'x86_64'; }
detect_package_manager() { printf '%s' "$TEST_MANAGER"; }
get_component_mirror() { printf 'direct'; }
effective_url() {
    printf '%s\n' "$1" >> "$TEST_TRACE"
    [ "$1" = 'https://github.com/fw876/helloworld/releases/latest' ] || return 98
    [ "$TEST_SCENARIO" != metadata_failure ] || return 1
    printf 'https://github.com/fw876/helloworld/releases/tag/v198.2'
}
fetch_text() {
    printf '%s\n' "$1" >> "$TEST_TRACE"
    [ "$1" = 'https://github.com/fw876/helloworld/releases/expanded_assets/v198.2' ] || return 98
    [ "$TEST_SCENARIO" != no_asset ] || return 0
    printf '%s\n' '<a href="/XTLS/Xray-core/releases/download/v99.0.0/Xray-linux-64.zip">official</a>'
    printf '%s\n' '<a href="/fw876/helloworld/releases/download/v198.2/xray-core_26.10.21-r2_x86_64.ipk">ipk</a>'
    printf '%s\n' '<a href="/fw876/helloworld/releases/download/v198.2/xray-core-26.10.21-r2_x86_64.apk">apk</a>'
}
download_file() { printf 'UNEXPECTED DOWNLOAD %s\n' "$1" >> "$TEST_TRACE"; return 97; }
mainprogram_install_package() { printf 'UNEXPECTED INSTALL\n' >> "$TEST_TRACE"; return 97; }
"$TEST_ACTION"
'''
            runner.write_text(source + overrides, encoding="utf-8", newline="\n")
            env = dict(os.environ, TEST_MANAGER=manager, TEST_SCENARIO=scenario,
                       TEST_ACTION=action, TEST_TRACE=trace.as_posix(), MSYS_NO_PATHCONV="1")
            if os.name == "nt":
                env["TEST_TRACE"] = subprocess.check_output(
                    [BASH, "-c", 'cygpath -u "$1"', "path", str(trace)], text=True, timeout=20).strip()
            result = subprocess.run([BASH, str(runner)], env=env, text=True,
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            requests = trace.read_text().splitlines()
            expected = ["https://github.com/fw876/helloworld/releases/latest"]
            if scenario != "metadata_failure":
                expected.append("https://github.com/fw876/helloworld/releases/expanded_assets/v198.2")
            self.assertEqual(requests, expected, "must not fall back to XTLS or install after resolver failure")
            return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_each_package_manager_selects_fw876_package_only(self):
        for manager, asset in (("opkg", "xray-core_26.10.21-r2_x86_64.ipk"),
                               ("apk", "xray-core-26.10.21-r2_x86_64.apk")):
            with self.subTest(manager=manager):
                value = self.run_updater(manager)
                self.assertEqual(value["latest_version"], "26.10.21")
                self.assertEqual(value["download_url"], "https://github.com/fw876/helloworld/releases/download/v198.2/" + asset)

    def test_failed_fw_metadata_or_missing_asset_never_uses_xtls_fallback(self):
        for scenario in ("metadata_failure", "no_asset"):
            with self.subTest(scenario=scenario):
                value = self.run_updater(scenario=scenario, action="xray_upgrade")
                self.assertEqual(value["success"], "0")
                self.assertNotIn("download_url", value)


if __name__ == "__main__":
    unittest.main()
