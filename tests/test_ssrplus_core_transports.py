#!/usr/bin/env python3
# Historical regressions plus the current v198.2 mKCP layer and loopback gate.
"""Run subscribed/selected SSR transports through the actual official Xray.

Only UCI and host OS boundaries are adapted. Never contact a router. The current
mKCP interoperability gate starts isolated listeners on loopback only.
"""
import base64
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import test_ssrplus_core_config as core
import test_ssrplus_subscription as subscription
import test_shared_xray_compat as shared
import test_ssrplus_firstboot as firstboot

ROOT = core.ROOT
BINARY = os.environ.get("XRAY_TEST_BINARY")
KCP_BINARIES = tuple(binary for binary in (BINARY, os.environ.get("FW876_XRAY_TEST_BINARY")) if binary)


def stale_transport_node(protocol, transport):
    """Valid protocol fixtures whose effective network ignores transport."""
    node = {"type": "v2ray", "v2ray_protocol": protocol, "server": "ss.example",
            "server_port": "443", "alias": "EffectiveNetwork", "transport": transport}
    if protocol == "wireguard":
        node.update(server_port="51820", private_key="AAIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eH2A=",
                    peer_pubkey="B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw=",
                    local_addresses=["10.0.0.2/32"], allowedips=["0.0.0.0/0"],
                    keepaliveperiod="25", kernelmode="1", mtu="1420")
    else:
        node.update(hy2_auth="FixtureAuth", tls="1", tls_host="tls.example")
    return node


@unittest.skipUnless(subscription.LuaRuntime, "lupa.lua51 is required")
class CoreTransportRegressions(unittest.TestCase):
    def setUp(self):
        self.subscriber = subscription.SubscriptionRegressions()
        self.subscriber.setUp()
        self.addCleanup(self.subscriber.doCleanups)
        self.subscriber.installed_cores = core.CORE_BINARIES
        self.subscriber.sections["subscribe"].update(ss_type="v2ray", xray_tj_type="v2ray",
                                                      xray_hy2_type="v2ray")

    def subscribe(self, links):
        self.subscriber.downloads[subscription.URL_A] = base64.b64encode("\n".join(links).encode()).decode()
        self.subscriber.files.pop("/tmp/sub_md5_" + subscription.group_hash(subscription.URL_A), None)
        self.assertEqual(self.subscriber.run_subscriber(), 0, self.subscriber.logs)
        return {sid: node for sid, node in self.subscriber.persisted.items()
                if node.get("grouphashkey") == subscription.group_hash(subscription.URL_A)}

    def check_real_core(self, config):
        if BINARY:
            with tempfile.TemporaryDirectory(prefix="ssr-xray-transport-") as temporary:
                result = shared.check_core_config(BINARY, config, Path(temporary) / "config.json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(BINARY, "XRAY_TEST_BINARY is required for effective-network validation")
    def test_wireguard_and_hysteria2_ignore_retained_legacy_transport_fields(self):
        for protocol in ("wireguard", "hysteria2"):
            for transport in ("h2", "quic"):
                with self.subTest(protocol=protocol, retained_transport=transport):
                    node = stale_transport_node(protocol, transport)
                    before = copy.deepcopy(node)
                    try:
                        config = core.generate_core_config(node)
                    except Exception as error:
                        self.fail("valid effective network was rejected: " + str(error))
                    outbound = config["outbounds"][0]
                    self.assertEqual(outbound["protocol"], "wireguard" if protocol == "wireguard" else "hysteria")
                    if protocol == "wireguard":
                        self.assertNotIn("streamSettings", outbound)
                    else:
                        self.assertEqual(outbound["streamSettings"]["network"], "hysteria")
                    self.check_real_core(config)
                    self.assertEqual(node, before, "effective-network validation rewrote the saved node")

    def test_vless_vmess_and_trojan_still_reject_effective_legacy_transports(self):
        for protocol in ("vless", "vmess", "trojan"):
            for transport in ("h2", "http", "quic"):
                with self.subTest(protocol=protocol, transport=transport):
                    node = {"type": "v2ray", "v2ray_protocol": protocol, "transport": transport,
                            "server": "ss.example", "server_port": "443", "vmess_id": core.USERS["vless"],
                            "password": "FixtureSecret", "security": "auto", "alter_id": "0"}
                    before = copy.deepcopy(node)
                    with self.assertRaisesRegex(Exception, "unsupported.*transport"):
                        core.generate_core_config(node)
                    self.assertEqual(node, before)

    def test_gecko_preserves_packet_sizes_auth_and_quic_parameters(self):
        for size, expected in (("", "512-1200"), ("&minPacketSize=600&maxPacketSize=1300", "600-1300")):
            with self.subTest(size=size):
                uri = ("hy2://fixture-secret@ss.example:443?sni=tls.example&obfs=gecko&obfs-password=ObfsSecret" +
                       size + "&upmbps=12&downmbps=34&mport=2000-3000#Gecko")
                node = next(iter(self.subscribe([uri]).values()))
                before = copy.deepcopy(node)
                config = core.generate_core_config(node)
                stream = config["outbounds"][0]["streamSettings"]
                self.assertEqual(stream["finalmask"]["udp"], [{"type": "salamander", "settings": {
                    "password": "ObfsSecret", "packetSize": expected}}])
                self.assertEqual(stream["hysteriaSettings"]["auth"], "fixture-secret")
                self.assertEqual(stream["finalmask"]["quicParams"]["brutalUp"], "12mbps")
                self.assertEqual(stream["finalmask"]["quicParams"]["brutalDown"], "34mbps")
                self.assertEqual(stream["finalmask"]["quicParams"]["udpHop"]["ports"], "2000-3000")
                self.assertEqual(node, before)
                self.check_real_core(config)

    def test_legacy_transports_keep_nodes_and_selections_but_refuse_generation(self):
        for transport in ("h2", "http", "quic"):
            with self.subTest(transport=transport):
                nodes = self.subscribe([core.link("vless", "type=" + transport + "&security=none")])
                sid = next(iter(nodes))
                self.subscriber.sections["global"].update(global_server=sid, udp_relay_server=sid,
                    netflix_server=sid, netflix_enable="1")
                self.subscriber.sections["socks"] = {".type": "socks5_proxy", "server": sid, "enabled": "1"}
                before = copy.deepcopy(self.subscriber.sections)
                self.assertEqual(self.subscriber.run_subscriber(), 0, self.subscriber.logs)
                self.assertEqual(self.subscriber.persisted, before)
                with self.assertRaisesRegex(Exception, "unsupported.*transport"):
                    core.generate_core_config(before[sid], section_name=sid, uci_sections=before)

    @unittest.skipUnless(BINARY, "XRAY_TEST_BINARY is required for the selected-node real core gate")
    def test_reparse_preserves_distinct_selected_nodes_for_every_real_core_role(self):
        links = [core.link("vless", "type=kcp&security=none").replace("#Transport", "#Main"),
                 core.link("trojan", "type=kcp&security=none&headerType=dns&host=Dns.Example&seed=Seed").replace("#Transport", "#UDP"),
                 "hy2://Auth@ss.example:443?sni=tls.example&obfs=gecko&obfs-password=Secret&minPacketSize=600&maxPacketSize=1300#SOCKS",
                 "hy2://Auth@ss.example:443?sni=tls.example&obfs=salamander&obfs-password=Secret#Netflix"]
        ids = {node["alias"]: sid for sid, node in self.subscribe(links).items()}
        subscriber = self.subscriber
        subscriber.sections["global"].update(global_server=ids["Main"], udp_relay_server=ids["UDP"],
                                             netflix_server=ids["Netflix"], netflix_enable="1")
        subscriber.sections["socks"] = {".type": "socks5_proxy", "server": ids["SOCKS"], "enabled": "1"}
        before = copy.deepcopy(subscriber.sections)
        observed = []
        subscriber.service_callback = lambda: observed.append(copy.deepcopy(subscriber.persisted))
        subscriber.files.pop("/tmp/sub_md5_" + subscription.group_hash(subscription.URL_A))
        self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
        self.assertEqual(observed, [before])
        for owner, option, alias, args in (("global", "global_server", "Main", ["tcp", "1234", "0"]),
            ("global", "udp_relay_server", "UDP", ["udp", "1235", "0"]),
            ("global", "netflix_server", "Netflix", ["tcp", "1236", "0"]),
            ("socks", "server", "SOCKS", ["tcp", "0", "1080"])):
            with self.subTest(role=option):
                sid = observed[0][owner][option]
                self.assertEqual(sid, ids[alias])
                config = core.generate_core_config(observed[0][sid], runtime_args=args,
                    section_name=sid, uci_sections=observed[0])
                self.check_real_core(config)

    def test_failed_group_retains_unsupported_selected_nodes_while_valid_group_updates(self):
        sid, node = next(iter(self.subscribe([core.link("vless", "type=h2&security=none")]).items()))
        subscriber = self.subscriber
        subscriber.sections["subscribe"]["subscribe_url"] = [subscription.URL_A, subscription.URL_B]
        subscriber.sections["global"].update(global_server=sid, udp_relay_server=sid, netflix_server=sid)
        subscriber.sections["socks"] = {".type": "socks5_proxy", "server": sid, "enabled": "1"}
        before = copy.deepcopy(subscriber.sections)
        subscriber.http_codes[subscription.URL_A] = 503
        self.assertNotEqual(subscriber.run_subscriber(), 0, subscriber.logs)
        for section in (sid, "global", "socks", "manual"):
            self.assertEqual(subscriber.persisted[section], before[section])
        self.assertTrue(any(value.get("server") == "new-b.example" for value in subscriber.persisted.values()))

    def test_r11_gecko_reparse_preserves_selected_sid_and_existing_explicit_sizes(self):
        for supplied_sizes in ("", "&minPacketSize=600&maxPacketSize=1300"):
            with self.subTest(query=supplied_sizes):
                subscriber = self.subscriber
                repaired = subscriber.source
                subscriber.source = subscription.subscription_source(("ssrplus-core-transport.patch",))
                sid, old_node = next(iter(self.subscribe([
                    "hy2://Auth@ss.example:443?sni=tls.example&obfs=gecko&obfs-password=Secret" + supplied_sizes + "#Gecko"
                ]).items()))
                subscriber.sections[sid].update(obfs_MinPacketSize="600", obfs_MaxPacketSize="1300")
                # Native UCI serializes scalar numbers as strings on disk.
                subscriber.sections[sid]["server_port"] = str(subscriber.sections[sid]["server_port"])
                subscriber.sections["global"].update(global_server=sid, udp_relay_server=sid,
                    netflix_server=sid, netflix_enable="1")
                subscriber.sections["socks"] = {".type": "socks5_proxy", "server": sid, "enabled": "1"}
                subscriber.source = repaired
                subscriber.files.pop("/tmp/sub_md5_" + subscription.group_hash(subscription.URL_A))
                self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                self.assertIn(sid, subscriber.persisted)
                for owner, option in (("global", "global_server"), ("global", "udp_relay_server"),
                                      ("global", "netflix_server"), ("socks", "server")):
                    self.assertEqual(subscriber.persisted[owner][option], sid)
                node = subscriber.persisted[sid]
                self.assertEqual(node["obfs_MinPacketSize"], "600")
                self.assertEqual(node["obfs_MaxPacketSize"], "1300")
                config = core.generate_core_config(node, section_name=sid, uci_sections=subscriber.persisted)
                self.assertEqual(config["outbounds"][0]["streamSettings"]["finalmask"]["udp"][0]["settings"]["packetSize"], "600-1300")
                self.check_real_core(config)


@unittest.skipUnless(subscription.LuaRuntime, "lupa.lua51 is required")
class CurrentKcpTransportRegressions(unittest.TestCase):
    """Exercise the prepared production v198.2 generator, not the 190 fixture."""

    def node(self, header=None, seed=None):
        node = shared.ssr_node("vless", "kcp")
        node.update(tls="0", server="127.0.0.1", kcp_domain="Dns.Example")
        if header is not None:
            node["kcp_guise"] = header
        if seed is not None:
            node["seed"] = seed
        return node

    def test_kcp_security_is_inner_and_every_header_is_outer(self):
        for header in (None, "none", "dns", "srtp", "utp", "wechat-video", "dtls", "wireguard"):
            for seed in (None, "", "MiXeD+%2F"):
                with self.subTest(header=header, seed=seed):
                    node = self.node(header, seed)
                    before = copy.deepcopy(node)
                    config = shared.generate_ssr_config(node)
                    masks = config["outbounds"][0]["streamSettings"]["finalmask"]["udp"]
                    expected = [{"type": "mkcp-legacy", **({"settings": {"value": seed}} if seed else {})}]
                    if header not in (None, "none"):
                        settings = {"header": "wechat" if header == "wechat-video" else header}
                        if header == "dns":
                            settings["value"] = "Dns.Example"
                        expected.append({"type": "mkcp-legacy", "settings": settings})
                    self.assertEqual(masks, expected)
                    self.assertEqual(node, before, "generation changed the saved node")
                    if BINARY:
                        with tempfile.TemporaryDirectory(prefix="ssr-current-kcp-") as directory:
                            result = shared.check_core_config(BINARY, config, Path(directory) / "config.json")
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_custom_finalmask_replaces_automatic_kcp_layers(self):
        custom = {"udp": [{"type": "mkcp-legacy", "settings": {"value": "CustomSeed"}},
                          {"type": "mkcp-legacy", "settings": {"header": "srtp"}}]}
        node = self.node("dns", "AutomaticSeed")
        node["finalmask"] = base64.b64encode(json.dumps(custom).encode()).decode()
        config = shared.generate_ssr_config(node)
        self.assertEqual(config["outbounds"][0]["streamSettings"]["finalmask"], custom)


class LoopbackEcho(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        while True:
            try:
                payload = self.request.recv(65536)
            except (socket.timeout, ConnectionError):
                return
            if not payload:
                return
            try:
                self.request.sendall(payload)
            except ConnectionError:
                return


@contextmanager
def loopback_xray(binary, config):
    """Feed config through the same native stdin boundary as the parser gate."""
    process = subprocess.Popen([binary, "run", "-config", "stdin:", "-format", "json"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    lines, started = [], threading.Event()

    def read_output():
        for line in process.stdout:
            lines.append(line)
            if "started" in line:
                started.set()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        process.stdin.write(json.dumps(config))
        process.stdin.close()
        if not started.wait(5):
            raise AssertionError("loopback Xray did not start:\n" + "".join(lines))
        yield lines
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()


@unittest.skipUnless(KCP_BINARIES and subscription.LuaRuntime,
                     "XRAY_TEST_BINARY or FW876_XRAY_TEST_BINARY and lupa.lua51 are required")
class CurrentKcpLoopbackInteroperability(unittest.TestCase):
    """A real TCP payload crosses VLESS/mKCP, not just `run -test`."""

    def exchange(self, binary, *, reverse_client_masks=False, timeout=5):
        with socketserver.ThreadingTCPServer(("127.0.0.1", 0), LoopbackEcho) as echo:
            echo.daemon_threads = True
            echo_thread = threading.Thread(target=echo.serve_forever, daemon=True)
            echo_thread.start()
            try:
                # Reserve ephemeral ports until both configs have been assembled.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp, \
                        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
                    udp.bind(("127.0.0.1", 0))
                    tcp.bind(("127.0.0.1", 0))
                    server_port, client_port = udp.getsockname()[1], tcp.getsockname()[1]
                    node = shared.ssr_node("vless", "kcp")
                    node.update(tls="0", server="127.0.0.1", server_port=str(server_port),
                                kcp_guise="srtp", seed="LoopbackSeed+%2F")
                    client = shared.generate_ssr_config(node, runtime_args=["tcp", "0", str(client_port)])
                    # Keep the complete generated outbound and route its inbound
                    # directly to a loopback echo service without external DNS.
                    client["log"] = {"loglevel": "warning"}
                    client.pop("dns", None)
                    client.pop("routing", None)
                    client["inbounds"] = [{"listen": "127.0.0.1", "port": client_port,
                        "protocol": "dokodemo-door", "settings": {
                            "address": "127.0.0.1", "port": echo.server_address[1], "network": "tcp"}}]
                    if reverse_client_masks:
                        client["outbounds"][0]["streamSettings"]["finalmask"]["udp"].reverse()
                    # Independently authored peer encodes the upstream wire
                    # contract: seed/security inside, SRTP header outside.
                    server = {"log": {"loglevel": "warning"}, "inbounds": [{
                        "listen": "127.0.0.1", "port": server_port, "protocol": "vless",
                        "settings": {"clients": [{"id": shared.UUID}], "decryption": "none"},
                        "streamSettings": {"network": "kcp", "security": "none", "kcpSettings": {},
                            "finalmask": {"udp": [
                                {"type": "mkcp-legacy", "settings": {"value": "LoopbackSeed+%2F"}},
                                {"type": "mkcp-legacy", "settings": {"header": "srtp"}}]}}}],
                        # Xray 26.10.21 blocks private targets after VLESS by
                        # default; allow only this isolated echo endpoint.
                        "outbounds": [{"protocol": "freedom", "settings": {"finalRules": [{
                            "action": "allow", "ip": ["127.0.0.1/32"], "network": "tcp",
                            "port": echo.server_address[1]}]}}]}
                with loopback_xray(binary, server) as server_logs, loopback_xray(binary, client) as client_logs:
                    # Confirm the locally bound client is accepting before using
                    # the one connection whose exact payload must reach the peer.
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            connection = socket.create_connection(("127.0.0.1", client_port), timeout=1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                self.fail("loopback client listener unavailable:\n" + "".join(client_logs))
                            time.sleep(0.02)
                    with connection:
                        connection.settimeout(timeout)
                        payload = b"ssr-v198-mkcp-wire-contract\x00" + bytes(range(256)) * 16
                        connection.sendall(payload)
                        received = bytearray()
                        while len(received) < len(payload):
                            part = connection.recv(len(payload) - len(received))
                            if not part:
                                break
                            received.extend(part)
                        self.assertEqual(bytes(received), payload,
                                         "\n" + "".join(server_logs + client_logs))
            finally:
                echo.shutdown()
                echo_thread.join(timeout=5)

    def test_generated_srtp_and_seed_cross_real_mkcp_client_server(self):
        for binary in KCP_BINARIES:
            with self.subTest(binary=binary):
                try:
                    self.exchange(binary)
                except (socket.timeout, ConnectionError) as error:
                    self.fail("generated mKCP client could not exchange the loopback payload: " + str(error))

    def test_reversing_the_generated_layers_breaks_peer_interoperability(self):
        for binary in KCP_BINARIES:
            with self.subTest(binary=binary), self.assertRaises((socket.timeout, ConnectionError)):
                self.exchange(binary, reverse_client_masks=True, timeout=2)


class SelectedTransportStartupRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        firstboot.FirstbootTests.setUpClass()
        cls.addClassCleanup(firstboot.FirstbootTests.doClassCleanups)
        cls.init_code = firstboot.FirstbootTests.init_code

    def test_posix_shell_boundary_for_both_startup_scenarios(self):
        # Simulate Linux selection on Windows without changing pathlib's host.
        # Validate the real callers' argv, then execute every original assertion
        # through the available native shell instead of faking its result.
        native_run, native_shell = subprocess.run, firstboot.SHELL
        native_prefix = [native_shell] + (["--noprofile", "--norc"] if os.name == "nt" else [])
        observed = []

        def run_posix_boundary(command, **kwargs):
            observed.append(command)
            self.assertEqual(command[:2], ["/usr/bin/sh", "-c"],
                             "POSIX sh received Bash-only startup options")
            self.assertEqual(len(command), 3)
            return native_run(native_prefix + command[1:], **kwargs)

        with mock.patch(__name__ + ".os", SimpleNamespace(name="posix", environ=os.environ)), \
             mock.patch.object(firstboot, "SHELL", "/usr/bin/sh"), \
             mock.patch.object(subprocess, "run", side_effect=run_posix_boundary):
            for scenario, expected_calls in (
                    (self.test_effective_network_allows_each_selected_role_and_dispatch_without_rewriting_nodes, 16),
                    (self.test_start_and_restart_reject_every_selected_legacy_role_before_replacement, 24)):
                before = len(observed)
                scenario()
                self.assertEqual(len(observed) - before, expected_calls)

    def test_effective_network_allows_each_selected_role_and_dispatch_without_rewriting_nodes(self):
        shell_command = [firstboot.SHELL]
        if os.name == "nt":
            shell_command += ["--noprofile", "--norc"]
        for protocol in ("wireguard", "hysteria2"):
            for transport in ("h2", "quic"):
                for role, code in (("global_server", "1"), ("udp_relay_server", "2"),
                                   ("netflix_server", "3"), ("socks", "4")):
                    with self.subTest(protocol=protocol, retained_transport=transport, role=role):
                        with tempfile.TemporaryDirectory(prefix="ssr-effective-network-") as temporary:
                            base = Path(temporary)
                            init = base / "init.sh"
                            init.write_text(self.init_code.replace(
                                '${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh',
                                (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh").as_posix()), encoding="utf-8")
                            retained = base / "retained-node.json"
                            retained.write_text(json.dumps(stale_transport_node(protocol, transport)), encoding="utf-8")
                            before = retained.read_bytes()
                            environment = dict(os.environ, TEST_ROOT=base.as_posix(), TEST_INIT=init.as_posix(),
                                TEST_PROTOCOL=protocol, TEST_TRANSPORT=transport, TEST_ROLE=role,
                                TEST_ROLE_CODE=code, MSYS_NO_PATHCONV="1")
                            result = subprocess.run(shell_command + ["-c", r'''
. "$TEST_INIT" || exit
switch_server=
TMP_PATH="$TEST_ROOT"
mode=tcp
tcp_config_file="$TMP_PATH/tcp-ssr-selected.json"
udp_config_file=$tcp_config_file
shunt_config_file=$tcp_config_file
local_config_file=$tcp_config_file
echolog() { printf '%s\n' "$*" >&2; }
uci_get_by_type() {
    case "$1.$2" in
        global.global_server) [ "$TEST_ROLE" = global_server ] && echo candidate || echo valid ;;
        global.udp_relay_server) [ "$TEST_ROLE" = udp_relay_server ] && echo candidate || echo nil ;;
        global.netflix_server) [ "$TEST_ROLE" = netflix_server ] && echo candidate || echo nil ;;
        global.netflix_enable|socks5_proxy.enabled) echo 1 ;;
        socks5_proxy.server) [ "$TEST_ROLE" = socks ] && echo candidate || echo nil ;;
        *) echo "${3:-}" ;;
    esac
}
uci_get_by_name() {
    case "$1.$2" in
        candidate.type|valid.type) echo v2ray ;;
        candidate.v2ray_protocol) echo "$TEST_PROTOCOL" ;;
        candidate.transport) echo "$TEST_TRANSPORT" ;;
        valid.v2ray_protocol) echo vless ;;
        valid.transport) echo raw ;;
        *) echo "${3:-}" ;;
    esac
}
lua() { printf '{}\n'; }
ssrp_check_selected_xray_transports || exit
gen_config_file candidate v2ray "$TEST_ROLE_CODE" 1234 1080
'''], env=environment, capture_output=True, text=True, timeout=20)
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            self.assertEqual((base / "tcp-ssr-selected.json").read_text().strip(), "{}")
                            self.assertEqual(retained.read_bytes(), before)

    def test_start_and_restart_reject_every_selected_legacy_role_before_replacement(self):
        shell_command = [firstboot.SHELL]
        if os.name == "nt":
            shell_command += ["--noprofile", "--norc"]
        for command in ("start", "restart"):
            for role in ("global_server", "udp_relay_server", "netflix_server", "socks"):
                for transport in ("h2", "http", "quic"):
                    with self.subTest(command=command, role=role, transport=transport):
                        with tempfile.TemporaryDirectory(prefix="ssr-unsupported-startup-") as temporary:
                            base = Path(temporary)
                            init = base / "init.sh"
                            runtime = (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh").as_posix()
                            init.write_text(self.init_code.replace(
                                '${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh', runtime),
                                encoding="utf-8")
                            retained = base / "retained-config"
                            retained.write_bytes(b"selected node and user parameters\n")
                            environment = os.environ.copy()
                            environment.update(TEST_ROOT=base.as_posix(), TEST_INIT=init.as_posix(),
                                TEST_ROLE=role, TEST_TRANSPORT=transport, TEST_COMMAND=command,
                                MSYS_NO_PATHCONV="1")
                            result = subprocess.run(shell_command + ["-c", r'''
. "$TEST_INIT" || exit
switch_server=
LOCK_FILE="$TEST_ROOT/lifecycle.lock"
flock() { return 0; }
echolog() { printf '%s\n' "$*" >&2; }
ssrp_has_processes() { return 1; }
ssrp_dns_begin() { printf 'unexpected-dns-stage\n' >&2; return 81; }
ssrp_dns_abort() { :; }
ssrp_stop() { printf 'stop\n' >> "$TEST_ROOT/events"; }
ssrp_start() { printf 'start\n' >> "$TEST_ROOT/events"; }
uci_get_by_type() {
    case "$1.$2" in
        global.global_server) [ "$TEST_ROLE" = global_server ] && echo unsupported || echo valid ;;
        global.udp_relay_server) [ "$TEST_ROLE" = udp_relay_server ] && echo unsupported || echo nil ;;
        global.netflix_server) [ "$TEST_ROLE" = netflix_server ] && echo unsupported || echo nil ;;
        global.netflix_enable) echo 1 ;;
        socks5_proxy.enabled) echo 1 ;;
        socks5_proxy.server) [ "$TEST_ROLE" = socks ] && echo unsupported || echo nil ;;
        *) echo "${3:-}" ;;
    esac
}
uci_get_by_name() {
    case "$1.$2" in
        unsupported.type|valid.type) echo v2ray ;;
        unsupported.transport) echo "$TEST_TRANSPORT" ;;
        valid.transport) echo raw ;;
        *) echo "${3:-}" ;;
    esac
}
"$TEST_COMMAND"
'''], env=environment, capture_output=True, text=True, timeout=20)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertRegex(result.stderr, "unsupported.*transport")
                            self.assertFalse((base / "events").exists(), "failed preflight replaced the old service")
                            self.assertEqual(retained.read_bytes(), b"selected node and user parameters\n")


if __name__ == "__main__":
    unittest.main()
