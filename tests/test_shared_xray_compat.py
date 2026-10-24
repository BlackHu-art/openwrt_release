#!/usr/bin/env python3
"""Check the shared Xray core against complete, real plugin generators.

Only router-facing UCI, filesystem and command boundaries are substituted.
Set XRAY_TEST_BINARY to an explicitly downloaded core to run config validation;
the test never downloads binaries, starts a service, or binds a listener.
"""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from fetch_xray_test_core import VERSION as TARGET_VERSION
import test_ssrplus_v198 as ssr_core


ROOT = Path(__file__).resolve().parents[1]
UUID = "12345678-1234-1234-1234-123456789abc"
# Valid public key from `xray x25519 -i` with an all-zero 32-byte test input.
# This public fixture is only parsed by `run -test`; no handshake is performed.
REALITY_PUBLIC_KEY = "L-V9o0fNYkMVKNqsX7spBzD_9oSvxM_C7ZCZX1jLO3Q"
TRANSPORTS = ("raw", "ws", "httpupgrade", "grpc")

if os.environ.get("REQUIRE_XRAY_TEST_CORE") == "1" and not os.environ.get("XRAY_TEST_BINARY"):
    raise RuntimeError("Xray is required by REQUIRE_XRAY_TEST_CORE; set XRAY_TEST_BINARY")

if os.environ.get("XRAY_TEST_BINARY") and not ssr_core.LuaRuntime:
    raise RuntimeError("XRAY_TEST_BINARY requires lupa.lua51; refusing to skip the real core gate")


def check_core_config(binary, config, path):
    payload = json.dumps(config)
    if os.name == "nt":
        # The native Windows core can see different temporary-file bytes from
        # Python on managed desktops. Feed the complete generated JSON through
        # Xray's official stdin loader; Linux keeps testing file loading.
        command = [binary, "run", "-test", "-config", "stdin:", "-format", "json"]
        return subprocess.run(command, input=payload, capture_output=True, text=True,
                              encoding="utf-8", timeout=20)
    path.write_text(payload, encoding="utf-8")
    return subprocess.run([binary, "run", "-test", "-config", str(path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=20)


def ssr_node(protocol, transport="raw"):
    """UCI fields consumed by the real v198.2 generator; no legacy generator."""
    return {"type": "v2ray", "v2ray_protocol": protocol, "server": "192.0.2.1",
            "server_port": "443", "vmess_id": UUID, "alter_id": "0", "security": "auto",
            "password": "fixture-secret", "encrypt_method_ss": "aes-128-gcm",
            "transport": transport, "tls": "1", "tls_host": "tls.example", "insecure": "0",
            "ws_host": "cdn.example", "ws_path": "/fixture", "httpupgrade_host": "cdn.example",
            "httpupgrade_path": "/fixture", "serviceName": "fixture-service", "grpc_mode": "gun"}


def generate_ssr_config(node, **kwargs):
    return ssr_core.generate_xray_config(node, xray_version=TARGET_VERSION, **kwargs)


@lru_cache(maxsize=1)
def generated_configs():
    """Return named actual outputs; no post-generation compatibility rewriting."""
    cases = {}
    for protocol in ("shadowsocks", "vless", "trojan"):
        for transport in TRANSPORTS:
            cases["/".join(("ssrplus", protocol, transport, "tls"))] = generate_ssr_config(
                ssr_node(protocol, transport))
    cases["ssrplus/vmess/ws/tls"] = generate_ssr_config(ssr_node("vmess", "ws"))
    reality = ssr_node("vless")
    reality.update(reality="1", tls="0", reality_publickey=REALITY_PUBLIC_KEY,
                   reality_shortid="0123456789abcdef", tls_fingerprint="chrome",
                   tls_flow="xtls-rprx-vision")
    cases["ssrplus/vless/raw/reality"] = generate_ssr_config(reality)
    node = ssr_node("vless")
    for mode in ("tcp", "udp", "tcp,udp"):
        cases["ssrplus/transparent-" + mode] = generate_ssr_config(
            node, runtime_args=[mode, "12347", "0"])
    cases["ssrplus/socks-only"] = generate_ssr_config(node, runtime_args=["tcp", "0", "12345"])
    cases["ssrplus/node-dns"] = generate_ssr_config(node, global_options={
        "pdnsd_enable": "7", "tunnel_forward": "223.5.5.5:53", "filter_aaaa": "0"})
    for guise in ("none", "srtp", "dns"):
        mkcp = ssr_node("vless", "kcp")
        mkcp.update(tls="0", kcp_guise=guise, seed="fixture-seed", kcp_domain="mask.example")
        cases["ssrplus/vless/mkcp/" + guise] = generate_ssr_config(mkcp)
    for obfs in ("salamander", "gecko"):
        hy2 = ssr_node("hysteria2")
        hy2.update(hy2_auth="fixture-auth", flag_obfs="1", obfs_type=obfs,
                   salamander="fixture-obfs", obfs_MinPacketSize="600", obfs_MaxPacketSize="1100")
        cases["ssrplus/hysteria2/" + obfs] = generate_ssr_config(hy2)
    return cases


@unittest.skipUnless(ssr_core.LuaRuntime, "optional lupa.lua51 is required")
class SharedXrayGeneratorContracts(unittest.TestCase):
    def test_current_ssr_mkcp_emits_supported_mask_names(self):
        for guise in ("none", "srtp", "dns"):
            masks = generated_configs()["ssrplus/vless/mkcp/" + guise]["outbounds"][0]["streamSettings"]["finalmask"]["udp"]
            self.assertTrue(masks)
            self.assertTrue(all(mask["type"] == "mkcp-legacy" for mask in masks), masks)

    def test_transport_parameters_reach_the_final_config(self):
        cases = generated_configs()
        mask = cases["ssrplus/vless/mkcp/dns"]["outbounds"][0]["streamSettings"]["finalmask"]
        self.assertIn({"type": "mkcp-legacy", "settings": {"value": "fixture-seed"}}, mask["udp"])
        for obfs in ("salamander", "gecko"):
            with self.subTest(obfs=obfs):
                mask = cases["ssrplus/hysteria2/" + obfs]["outbounds"][0]["streamSettings"]["finalmask"]["udp"][0]
                self.assertEqual(mask["type"], "salamander")
                self.assertEqual(mask["settings"]["password"], "fixture-obfs")

    def test_all_configs_exercise_the_real_ssr_generator(self):
        cases = generated_configs()
        expected = {"/".join(("ssrplus", protocol, transport, "tls"))
                    for protocol in ("shadowsocks", "vless", "trojan") for transport in TRANSPORTS}
        expected.update({"ssrplus/vmess/ws/tls", "ssrplus/vless/raw/reality", "ssrplus/node-dns",
                         "ssrplus/socks-only", "ssrplus/transparent-tcp", "ssrplus/transparent-udp",
                         "ssrplus/transparent-tcp,udp"})
        expected.update("ssrplus/vless/mkcp/" + guise for guise in ("none", "srtp", "dns"))
        expected.update("ssrplus/hysteria2/" + obfs for obfs in ("salamander", "gecko"))
        self.assertEqual(set(cases), expected)
        for label, config in cases.items():
            with self.subTest(config=label):
                self.assertTrue(config["inbounds"])
                self.assertTrue(config["outbounds"])

    def test_transparent_and_dns_cases_exercise_the_named_paths(self):
        cases = generated_configs()
        for mode in ("tcp", "udp", "tcp,udp"):
            with self.subTest(mode=mode):
                config = cases["ssrplus/transparent-" + mode]
                self.assertTrue(any(inbound["protocol"] in ("dokodemo-door", "tunnel")
                                    for inbound in config["inbounds"]))
        self.assertTrue(cases["ssrplus/node-dns"]["dns"]["servers"])
        socks = cases["ssrplus/socks-only"]["inbounds"]
        self.assertTrue(any(inbound["protocol"] == "socks" for inbound in socks))

    def test_vmess_and_reality_cases_exercise_the_named_protocols(self):
        cases = generated_configs()
        vmess = cases["ssrplus/vmess/ws/tls"]["outbounds"][0]
        self.assertEqual(vmess["protocol"], "vmess")
        self.assertEqual(vmess["streamSettings"]["security"], "tls")
        self.assertEqual(vmess["streamSettings"]["tlsSettings"]["serverName"], "tls.example")
        reality = cases["ssrplus/vless/raw/reality"]["outbounds"][0]
        self.assertEqual(reality["protocol"], "vless")
        self.assertEqual(reality["streamSettings"]["security"], "reality")
        self.assertEqual(reality["streamSettings"]["realitySettings"]["publicKey"], REALITY_PUBLIC_KEY)
        self.assertEqual(reality["streamSettings"]["realitySettings"]["shortId"], "0123456789abcdef")

    @unittest.skipUnless(os.environ.get("XRAY_TEST_BINARY"), "set XRAY_TEST_BINARY for real core config checks")
    def test_official_shared_core_rejects_invalid_protocol(self):
        binary = str(Path(os.environ["XRAY_TEST_BINARY"]).resolve())
        with tempfile.TemporaryDirectory(prefix="shared-xray-invalid-") as temporary:
            path = Path(temporary) / "invalid.json"
            result = check_core_config(binary, {"outbounds": [{"protocol": "invalid-validation-control"}]}, path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown config id: invalid-validation-control", result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get("XRAY_TEST_BINARY"), "set XRAY_TEST_BINARY for real core config checks")
    def test_official_shared_core_accepts_all_generated_configs(self):
        binary = str(Path(os.environ["XRAY_TEST_BINARY"]).resolve())
        version = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertRegex(version.stdout, r"^Xray " + re.escape(TARGET_VERSION) + r"\b")
        with tempfile.TemporaryDirectory(prefix="shared-xray-config-") as temporary:
            for index, (label, config) in enumerate(generated_configs().items()):
                with self.subTest(config=label):
                    path = Path(temporary) / (str(index) + ".json")
                    result = check_core_config(binary, config, path)
                    self.assertEqual(result.returncode, 0, label + "\n" + result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
