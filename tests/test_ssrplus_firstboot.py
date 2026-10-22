#!/usr/bin/env python3
"""Run imported SSR initialization in a private filesystem; never access a router.

All ordered patches are applied to blob-checked upstream fixtures. Only fixed
system paths and unavailable UCI/service OS boundaries are substituted. Linux
executes real /bin/sh and flock; Windows uses Git sh and optional native flock.
"""
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from ssrplus_firstboot_uci import read_config
import test_ssrplus_subscription as subscriptions


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ssrplus/2abdc9aa"
SHELL = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("sh")


@unittest.skipUnless(SHELL, "a POSIX shell is required")
class FirstbootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = tempfile.TemporaryDirectory(prefix="ssrp-firstboot-source-")
        cls.addClassCleanup(cls.prepared.cleanup)
        package = Path(cls.prepared.name)
        for row in (ROOT / "wrt_core/compat/ssrplus/source-files.tsv").read_text().splitlines():
            blob, target, fixture = row.split()
            data = (ROOT / "tests/fixtures" / fixture).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != blob:
                raise AssertionError("upstream fixture changed: " + fixture)
            path = package / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in (ROOT / "wrt_core/compat/ssrplus/patches.list").read_text().splitlines():
            if os.environ.get("SSRP_FIRSTBOOT_UNPATCHED") and name == "ssrplus-firstboot.patch":
                continue
            result = subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(package),
                                     "apply", str(ROOT / "wrt_core/patches" / name)],
                                    capture_output=True, text=True, timeout=20)
            if result.returncode:
                raise AssertionError(name + ": " + result.stderr)
        cls.init_code = (package / "root/etc/init.d/shadowsocksr").read_text(encoding="utf-8")
        cls.defaults_code = (package / "root/etc/uci-defaults/luci-ssr-plus").read_text(encoding="utf-8")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssrp-firstboot-run-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.environment = os.environ.copy()
        self.environment["MSYS_NO_PATHCONV"] = "1"
        self.environment["TEST_ROOT"] = self.base.as_posix()
        self.environment["TEST_HOST_ROOT"] = str(self.base)
        self.environment["TEST_PYTHON"] = sys.executable
        if os.name == "nt":
            self.environment["TEST_ROOT"] = subprocess.check_output(
                [SHELL, "--noprofile", "--norc", "-c", 'cygpath -u "$1"', "path", str(self.base)],
                env=self.environment, text=True).strip()
            flock_dir = os.environ.get("SSRP_TEST_FLOCK_DIR", str(Path(tempfile.gettempdir()) /
                "codex-ssr-msys-flock-probe/usr/bin"))
            self.environment["PATH"] = flock_dir + os.pathsep + self.environment["PATH"]
        self.config = self.base / "fs/etc/config/shadowsocksr"
        self.template = self.base / "fs/usr/share/shadowsocksr/shadowsocksr.config"
        for directory in ("fs/etc/config", "fs/etc/ssrplus", "bin"):
            (self.base / directory).mkdir(parents=True)
        self.write("init.sh", self.relocate(self.init_code))
        self.write("defaults.sh", self.relocate(self.defaults_code), executable=True)
        self.write("fs/usr/share/shadowsocksr/ssrp-runtime.sh", self.relocate(
            (ROOT / "wrt_core/compat/ssrplus/runtime.sh").read_text(encoding="utf-8")))
        self.template.write_bytes((FIXTURE / "shadowsocksr.config").read_bytes())
        # Load the real init once per invocation; only its rc.common dispatch
        # entry point is represented by this shim. The hook calls it externally.
        self.write("fs/etc/init.d/shadowsocksr", '''#!/bin/sh
. "$TEST_ROOT/init.sh" || exit
. "$TEST_ROOT/boundary.sh" || exit
printf 'entry:%s\\n' "$*" >> "$TEST_ROOT/entries"
"$@"
''', executable=True)
        self.write("boundary.sh", r'''
PATH="$TEST_ROOT/bin:$PATH"
export PATH
forbidden() { printf '%s\n' "$*" >> "$TEST_ROOT/forbidden"; return 87; }
ssrp_stop() { forbidden stop; }
ssrp_start() { forbidden start; }
ssrp_dnsmasq() { forbidden dnsmasq; }
service_start() { forbidden core; }
nft() { forbidden nft; }; iptables() { forbidden iptables; }
ip() { forbidden ip; }; killall() { forbidden killall; }
curl() { forbidden curl; }; ssh() { forbidden ssh; }
''')
        # Only the unavailable UCI executable is substituted. Its migrations
        # mutate pending state and commit the actual file read by sed and Lua.
        self.write("uci-boundary.py", (ROOT / "tests/ssrplus_firstboot_uci.py").read_text(encoding="utf-8"))
        self.write("bin/uci", '#!/bin/sh\nexec "$TEST_PYTHON" "$TEST_HOST_ROOT/uci-boundary.py" "$@"\n',
                   executable=True)

    def write(self, relative, text, executable=False):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        if executable:
            path.chmod(0o755)
        return path

    def relocate(self, code):
        # One pass prevents replacing a /tmp inside an inserted host path.
        code = code.replace('${IPKG_INSTROOT:-}', '').replace('$IPKG_INSTROOT', '')
        return re.sub(r'/(?:etc|usr|var|tmp|proc|lib)/', lambda m: '$TEST_ROOT/fs' + m.group(), code)

    def shell(self, body, check=True):
        command = [SHELL]
        if os.name == "nt":
            command += ["--noprofile", "--norc"]
        result = subprocess.run(command + ["-c", '''
. "$TEST_ROOT/init.sh" || exit
. "$TEST_ROOT/boundary.sh" || exit
''' + body], env=self.environment, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def initialize(self, body="", check=True):
        return self.shell(body + "\ninitialize\n", check=check)

    def assert_clean(self):
        self.assertFalse((self.base / "forbidden").exists(), "initialization entered service lifecycle")
        self.assertFalse((self.base / "fs/var/etc").exists(), "initialization created runtime directory")
        self.assertEqual(list(self.config.parent.glob(".ssrplus-init.*")), [], "staging files leaked")
        self.assertEqual(list(self.config.parent.glob("ssrplus-init-*")), [], "staging files leaked")

    def entries(self):
        path = self.base / "entries"
        self.assertTrue(path.exists(), "defaults hook never invoked the initialization entry point")
        return path.read_text().splitlines()

    def assert_factory(self):
        self.assertEqual(self.config.read_bytes(), self.template.read_bytes())
        sections = re.findall(r"^config (\w+)", self.config.read_text(encoding="utf-8"), re.M)
        self.assertEqual(sections, ["global", "server_subscribe", "access_control", "socks5_proxy",
                                    "server_global", "global_xray_fragment"])
        self.shell('test "$(stat -c %a "$TEST_ROOT/fs/etc/config/shadowsocksr")" = 644')
        self.assert_clean()

    def test_initialize_is_an_exported_rc_common_command(self):
        self.shell('case " $EXTRA_COMMANDS " in *" initialize "*) :;; *) exit 70;; esac')

    def test_missing_config_initializes_factory_and_all_ui_sections(self):
        self.initialize()
        self.assert_factory()

    def test_empty_config_initializes_without_runtime_directories(self):
        # Create through the shell: on this Windows host a Python-created empty
        # file is incorrectly reported as size4096 by MSYS stat/[ -s ]. Merely
        # truncating it does not repair that metadata; a shell-created file does.
        self.shell('touch "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                   'test ! -s "$TEST_ROOT/fs/etc/config/shadowsocksr"')
        self.initialize()
        self.assert_factory()

    def test_nonempty_even_malformed_config_skips_missing_or_invalid_template(self):
        for existing in (b"config global\n option global_server 'my-node'\n", b"malformed user data\n"):
            for template in (None, b"invalid template\n"):
                with self.subTest(existing=existing, template=template):
                    self.config.write_bytes(existing)
                    before = self.config.stat()
                    if template is None:
                        self.template.unlink(missing_ok=True)
                    else:
                        self.template.write_bytes(template)
                    self.initialize()
                    self.assertEqual(self.config.read_bytes(), existing)
                    self.assertEqual(self.config.stat().st_mtime_ns, before.st_mtime_ns)
                    self.assertFalse((self.base / "uci-calls").exists(), "existing config should skip validation")
                    self.assert_clean()

    def test_repeated_initialization_preserves_user_changes_and_inode(self):
        self.initialize()
        self.config.write_bytes(b"config global\n option global_server 'mine'\n")
        before = self.config.stat()
        self.template.unlink()
        self.initialize()
        self.assertEqual(self.config.stat().st_ino, before.st_ino)
        self.assertEqual(self.config.read_bytes(), b"config global\n option global_server 'mine'\n")
        self.assert_clean()

    def test_concurrent_initialization_serializes_and_copies_once(self):
        result = self.shell('command -v flock', check=False)
        if result.returncode and os.name == "nt":
            self.skipTest("native flock unavailable on Windows; required on Linux")
        self.assertEqual(result.returncode, 0, "Linux CI must provide real flock")
        self.shell(r'''
cp() { echo copy >> "$TEST_ROOT/copies"; command sleep .1; command cp "$@"; }
initialize & first=$!
initialize & second=$!
wait "$first" || exit
wait "$second" || exit
test "$(wc -l < "$TEST_ROOT/copies")" = 1
''')
        self.assert_factory()

    def test_missing_empty_invalid_and_no_global_templates_fail_without_publishing(self):
        for data in (None, b"", b"INVALID UCI\n", b"config server_subscribe\n"):
            with self.subTest(data=data):
                if data is None:
                    self.template.unlink()
                else:
                    self.template.write_bytes(data)
                result = self.initialize(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.config.exists())
                self.assert_clean()

    def test_validation_reads_absolute_dot_free_staged_package(self):
        self.initialize()
        calls = self.base / "uci-validation-files"
        self.assertTrue(calls.exists(), "UCI validation used a named package instead of the staged file")
        candidates = calls.read_text().splitlines()
        self.assertEqual(len(candidates), 1)
        prefix = self.environment["TEST_ROOT"] + "/fs/etc/config/"
        self.assertTrue(candidates[0].startswith(prefix))
        self.assertRegex(candidates[0][len(prefix):], r"^ssrplus-init-[A-Za-z0-9]+/shadowsocksr$")
        self.assert_factory()

    def test_valid_template_ignores_invalid_runtime_override(self):
        self.write("fs/var/run/uci/shadowsocksr", "INVALID runtime override\n")
        self.initialize()
        self.assert_factory()

    def test_runtime_override_cannot_supply_missing_template_global(self):
        self.template.write_bytes(b"config server_subscribe\n")
        self.write("fs/var/run/uci/shadowsocksr", "config global\n")
        result = self.initialize(check=False)
        self.assertNotEqual(result.returncode, 0, "runtime override masked an invalid factory template")
        self.assertFalse(self.config.exists())
        self.assert_clean()

    def test_saved_delta_cannot_supply_missing_template_global(self):
        self.template.write_bytes(b"config server_subscribe\n")
        self.write("fs/tmp/.uci/shadowsocksr", "shadowsocksr.stale='global'\n")
        result = self.initialize(check=False)
        self.assertNotEqual(result.returncode, 0, "saved delta masked an invalid factory template")
        self.assertFalse(self.config.exists())
        self.assert_clean()

    def test_copy_chmod_uci_and_rename_failures_preserve_empty_destination(self):
        for command in ("cp", "chmod", "mv", "mktemp", "mkdir", "uci"):
            with self.subTest(command=command):
                self.shell('rm -f "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                           'touch "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                           'test ! -s "$TEST_ROOT/fs/etc/config/shadowsocksr"')
                before = self.config.stat()
                # mkdir is used by the existing lock owner too; direct function
                # isolates the installation's own checked mkdir boundary.
                body = f'{command}() {{ return 73; }}\n'
                result = self.shell(body + "ssrp_initialize_config\n", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.config.read_bytes(), b"")
                self.assertEqual(self.config.stat().st_ino, before.st_ino)
                self.assert_clean()

    def config_sections(self):
        return read_config(self.config)

    def first_section(self, section_type):
        return next(values for values in self.config_sections().values() if values[".type"] == section_type)

    def test_real_defaults_hook_fresh_missing_and_empty_keep_auto_core_values(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                self.config.unlink(missing_ok=True)
                if empty:
                    self.shell('touch "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                               'test ! -s "$TEST_ROOT/fs/etc/config/shadowsocksr"')
                self.shell('"$TEST_ROOT/defaults.sh"')
                values = self.first_section("server_subscribe")
                self.assertNotIn("ss_type", values)
                self.assertNotIn("xray_hy2_type", values)
                self.assert_factory()
        self.assertEqual(self.entries(), ["entry:initialize", "entry:initialize"])

    def subscriber_from_hook(self, cores, query=""):
        self.shell('"$TEST_ROOT/defaults.sh"')
        case = subscriptions.SubscriptionRegressions()
        case.setUp()
        self.addCleanup(case.doCleanups)
        # This is the actual post-hook file, not a template or hand-picked core
        # preference. Keep every configuration value produced by the real hook.
        case.sections = {("global" if values[".type"] == "global" else sid):
                         {key: value for key, value in values.items() if key != ".anonymous"}
                         for sid, values in self.config_sections().items()}
        subscribe = next(values for values in case.sections.values() if values[".type"] == "server_subscribe")
        subscribe.update(subscribe_url=[subscriptions.URL_A], filter_words="", proxy="0")
        case.installed_cores = set(cores)
        link = "ss://YWVzLTEyOC1nY206c2VjcmV0@subscription.example:443" + query + "#Order"
        case.downloads[subscriptions.URL_A] = base64.b64encode(link.encode()).decode()
        self.assertEqual(case.run_subscriber(), 0, case.logs)
        return next(node for node in case.server_nodes().values() if node.get("server") == "subscription.example")

    @unittest.skipUnless(subscriptions.LuaRuntime, "lupa.lua51 required for real subscriber")
    def test_hook_values_select_available_libev_for_plain_ss(self):
        node = self.subscriber_from_hook({"ss-redir"})
        self.assertEqual(node["type"], "ss-libev")
        self.assertEqual(node["encrypt_method_ss"], "aes-128-gcm")
        self.assertEqual(node["password"], "secret")

    @unittest.skipUnless(subscriptions.LuaRuntime, "lupa.lua51 required for real subscriber")
    def test_hook_values_preserve_ss_websocket_transport_with_rust_and_xray(self):
        node = self.subscriber_from_hook({"sslocal", "xray"},
                                         "?type=ws&host=front.example&path=%2Fproxy")
        self.assertEqual(node["type"], "v2ray")
        self.assertEqual(node["v2ray_protocol"], "shadowsocks")
        self.assertEqual(node["transport"], "ws")
        self.assertEqual(node["ws_host"], "front.example")
        self.assertEqual(node["ws_path"], "/proxy")
        self.assertEqual(node["encrypt_method_ss"], "aes-128-gcm")
        self.assertEqual(node["password"], "secret")

    def test_real_defaults_hook_failure_stops_before_sed_and_can_retry(self):
        self.template.unlink()
        self.write("bin/sed", '#!/bin/sh\necho sed >> "$TEST_ROOT/later"\n', executable=True)
        result = self.shell('"$TEST_ROOT/defaults.sh"', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSR Plus: configuration initialization failed", result.stderr)
        self.assertEqual(self.entries(), ["entry:initialize"])
        self.assertFalse((self.base / "later").exists())
        self.assertEqual(self.config.read_bytes(), b"")
        self.assert_clean()
        (self.base / "bin/sed").unlink()
        self.template.write_bytes((FIXTURE / "shadowsocksr.config").read_bytes())
        self.shell('"$TEST_ROOT/defaults.sh"')
        self.assert_factory()
        self.assertEqual(self.entries(), ["entry:initialize", "entry:initialize"])

    def test_repeated_defaults_and_initialize_preserve_retained_transports_and_rules_without_template(self):
        self.config.write_text("""config global
 option global_server 'user_node'
 option udp_relay_server 'native_ss_node'
 option netflix_server 'httpupgrade_node'
 option netflix_enable '1'
config socks5_proxy
 option enabled '1'
 option server 'native_libev_node'
 option local_port '1080'
config server_subscribe
 option ss_type 'v2ray'
 option xray_hy2_type 'v2ray'
 option user_agent 'company-client'
 option auto_update_week_time '3'
 list subscribe_url 'https://subscription.company.example/company'
config servers 'user_node'
 option type 'v2ray'
 option v2ray_protocol 'shadowsocks'
 option server 'company.example'
 option transport 'ws'
 option tls '1'
 option tls_host 'tls.company.example'
 option ws_host 'front.company.example'
 option ws_path '/custom%2F+path'
config servers 'httpupgrade_node'
 option type 'v2ray'
 option v2ray_protocol 'vless'
 option server 'upgrade.company.example'
 option transport 'httpupgrade'
 option tls '1'
 option tls_host 'upgrade-tls.company.example'
 option httpupgrade_host 'upgrade-front.company.example'
 option httpupgrade_path '/upgrade%2F+path'
config servers 'http_node'
 option type 'v2ray'
 option v2ray_protocol 'vless'
 option server 'http.company.example'
 option transport 'raw'
 option tcp_guise 'http'
 option http_host 'http-front.company.example'
 option http_path '/http%2F+path'
 option tcp_host 'legacy-front.company.example'
 option tcp_path '/legacy%2F+path'
config servers 'grpc_node'
 option type 'v2ray'
 option v2ray_protocol 'trojan'
 option server 'grpc.company.example'
 option transport 'grpc'
 option tls '1'
 option serviceName 'company%2F+service'
 option enable_finalmask '1'
 option finalmask 'eyJ0Y3AiOltdfQ=='
 option finalmaskg 'eyJ1ZHAiOltdfQ=='
config servers 'native_ss_node'
 option type 'ss-rust'
 option server 'native.company.example'
 option encrypt_method_ss 'aes-128-gcm'
 option password '~~~+@:%2F%252F'
config servers 'native_libev_node'
 option type 'ss-libev'
 option server 'native-libev.company.example'
 option encrypt_method_ss 'aes-128-gcm'
 option password '%2F%252F'
config access_control
 list wan_fw_ips '192.0.2.0/24'
 list wan_bp_ips '198.51.100.17'
 option company_domain 'intranet.company.example'
config global_xray_fragment
 option fragment '1'
 option noise '1'
""", encoding="utf-8")
        original = self.config_sections()
        rules = {"white.list": b"intranet.company.example\n192.0.2.0/24\n",
                 "black.list": b"proxy.company.example\n198.51.100.17\n"}
        for name, data in rules.items():
            (self.base / "fs/etc/ssrplus" / name).write_bytes(data)
        self.template.unlink()
        for _ in range(2):
            self.shell('"$TEST_ROOT/defaults.sh"')
            self.assertEqual(self.config_sections(), original)
            before_bytes, before_stat = self.config.read_bytes(), self.config.stat()
            self.initialize()
            self.assertEqual(self.config.read_bytes(), before_bytes)
            self.assertEqual(self.config.stat().st_mtime_ns, before_stat.st_mtime_ns)
            self.assertEqual(self.config.stat().st_ino, before_stat.st_ino)
            for name, data in rules.items():
                self.assertEqual((self.base / "fs/etc/ssrplus" / name).read_bytes(), data)
        self.assertEqual(self.entries(), ["entry:initialize", "entry:initialize"])
        self.assert_clean()

    def test_real_defaults_hook_keeps_original_legacy_migrations_and_sed_conversions(self):
        self.config.write_text("""config global
 option global_server 'legacy_node'
config server_subscribe
 option auto_update_time '4'
config servers 'legacy_node'
 option type 'vmess'
 option encrypt_method_v2ray_ss 'aes-128-gcm'
 option xtls '1'
 option vless_flow 'obsolete'
 option fingerprint 'disable'
 option server 'legacy.company.example'
config servers 'legacy_vless'
 option type 'vless'
 option server 'vless.company.example'
config access_control
 list wan_fw_ips '192.0.2.0/24'
""", encoding="utf-8")
        self.template.unlink()
        self.shell('"$TEST_ROOT/defaults.sh"')
        subscribe = self.first_section("server_subscribe")
        self.assertNotIn("auto_update_time", subscribe)
        self.assertEqual({key: value for key, value in subscribe.items() if not key.startswith(".")},
                         {"auto_update_week_time": "*", "auto_update_day_time": "2",
                          "auto_update_min_time": "0",
                          "user_agent": "v2rayN/9.99", "xray_hy2_type": "hysteria2"})
        sections = self.config_sections()
        self.assertEqual(sections["legacy_node"], {".type": "servers", ".anonymous": False,
                         "type": "v2ray", "v2ray_protocol": "vmess", "encrypt_method_ss": "aes-128-gcm",
                         "tls": "1", "server": "legacy.company.example"})
        self.assertEqual(sections["legacy_vless"]["type"], "v2ray")
        self.assertEqual(sections["legacy_vless"]["v2ray_protocol"], "vless")
        self.assertEqual(self.first_section("global_xray_fragment")["fragment"], "0")
        self.assertEqual(self.first_section("global_xray_fragment")["noise"], "0")
        self.assertEqual(self.first_section("access_control")["wan_fw_ips"], ["192.0.2.0/24"])
        self.assertEqual(self.first_section("global")["global_server"], "legacy_node")
        self.assert_clean()

    def test_retained_empty_auto_and_custom_preferences_are_not_missing_options(self):
        for preference in ("", "auto", "ss-rust", "ss-libev", "v2ray", "company-core"):
            with self.subTest(preference=preference):
                self.config.write_text("config global\n option global_server 'nil'\n"
                                       "config server_subscribe\n option ss_type '" + preference + "'\n"
                                       " option xray_hy2_type '" + preference + "'\n", encoding="utf-8")
                self.shell('"$TEST_ROOT/defaults.sh"')
                subscribe = self.first_section("server_subscribe")
                self.assertEqual(subscribe["ss_type"], preference)
                self.assertEqual(subscribe["xray_hy2_type"], preference)
                self.assertEqual(len([value for value in self.config_sections().values()
                                      if value[".type"] == "global_xray_fragment"]), 1)
        self.assert_clean()

    def test_retained_missing_ss_preference_remains_absent_after_repeated_hooks(self):
        self.config.write_text("config global\n option global_server 'user_node'\n"
                               "config server_subscribe\n option user_agent 'company-client'\n"
                               "config servers 'user_node'\n option type 'ss-rust'\n"
                               " option server 'company.example'\n", encoding="utf-8")
        for _ in range(2):
            self.shell('"$TEST_ROOT/defaults.sh"')
            self.assertNotIn("ss_type", self.first_section("server_subscribe"))
            self.assertEqual(self.first_section("server_subscribe")["user_agent"], "company-client")
            self.assertEqual(self.first_section("global")["global_server"], "user_node")
        self.assert_clean()

    @unittest.skipUnless(subscriptions.LuaRuntime, "lupa.lua51 required for real subscriber")
    def test_retained_missing_preference_selects_libev_and_xray_from_actual_hook(self):
        for query, expected in (("", "ss-libev"), ("?type=ws&host=front.example&path=%2Fa%252Fb%2Bc+d", "v2ray")):
            with self.subTest(query=query):
                self.config.write_text("config global\n option global_server 'nil'\n"
                                       "config server_subscribe\n option user_agent 'company-client'\n", encoding="utf-8")
                self.shell('"$TEST_ROOT/defaults.sh"')
                node = self.subscriber_from_hook({"ss-redir", "sslocal", "xray"} if query else {"ss-redir"}, query)
                self.assertEqual(node["type"], expected)
                self.assertNotIn("ss_type", self.first_section("server_subscribe"))
                if query:
                    self.assertEqual(node["ws_host"], "front.example")
                    self.assertEqual(node["ws_path"], "/a%2Fb+c d")

    def test_real_defaults_hook_does_not_factory_replace_malformed_nonempty_configuration(self):
        original = b"user-owned malformed configuration\n"
        self.config.write_bytes(original)
        self.template.unlink()
        self.shell('"$TEST_ROOT/defaults.sh"')
        self.assertEqual(self.config.read_bytes(), original)
        self.assert_clean()

    def test_explicit_reset_keeps_stop_failure_protection(self):
        original = b"config global\n option global_server 'user_node'\n"
        self.config.write_bytes(original)
        result = self.shell("reset", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual((self.base / "forbidden").read_text().splitlines(), ["stop"])


if __name__ == "__main__":
    unittest.main()
