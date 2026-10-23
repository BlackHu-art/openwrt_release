#!/usr/bin/env python3
"""Current SSR/Passwall2 generators against the authenticated fw876 Linux core.

The official Windows core is a separate standard-protocol check. It cannot stand
in for this gate even though both executables print version 26.10.21.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from fetch_fw876_xray import EXECUTABLE_SHA256, VERSION
import test_shared_xray_compat as shared


if os.environ.get('REQUIRE_FW876_XRAY_TEST_CORE') == '1' and not os.environ.get('FW876_XRAY_TEST_BINARY'):
    raise RuntimeError('fw876 Xray is required; set FW876_XRAY_TEST_BINARY to the pinned Linux core')
if os.environ.get('FW876_XRAY_TEST_BINARY') and shared.ssr_core.LuaRuntime is None:
    raise RuntimeError('fw876 Xray validation requires lupa.lua51; refusing to skip')


def private_configs():
    cases = {}
    for protocol in ('anytls', 'shadowsocksr', 'tuic', 'snell', 'naive'):
        node = shared.ssr_node(protocol)
        node.update(snell_psk='fixture-secret', snell_version='4',
                    tuic_uuid=shared.UUID, tuic_passwd='fixture-secret', xray_tuic_version='5',
                    username='fixture-user', ssr_method='aes-128-cfb',
                    ssr_protocol='origin', ssr_obfs='plain')
        cases['ssrplus/fw-' + protocol] = shared.generate_ssr_config(node)
    node = shared.ssr_node('shadowsocks')
    node.update(tls='0', xray_shadowtls='1', xray_shadowtls_version='3',
                xray_shadowtls_password='fixture-secret', xray_shadowtls_sni='tls.example')
    cases['ssrplus/fw-shadowtls'] = shared.generate_ssr_config(node)
    return cases


class Fw876GeneratorContracts(unittest.TestCase):
    def test_real_ssr_generator_emits_each_private_protocol(self):
        for name, config in private_configs().items():
            with self.subTest(name=name):
                outbound = config['outbounds'][0]
                if name.endswith('shadowtls'):
                    self.assertEqual(outbound['streamSettings']['security'], 'shadowtls')
                    self.assertEqual(outbound['streamSettings']['shadowtlsSettings']['password'], 'fixture-secret')
                else:
                    protocol = name.removeprefix('ssrplus/fw-')
                    self.assertEqual(outbound['protocol'], protocol)
                    self.assertEqual(outbound['settings']['address'], '192.0.2.1')
                    self.assertEqual(outbound['settings']['port'], 443)

    @unittest.skipUnless(os.environ.get('FW876_XRAY_TEST_BINARY'),
                         'fw876 Linux executable is exercised by the required Linux CI gate')
    def test_pinned_fw_core_accepts_current_shared_and_private_configs(self):
        binary = Path(os.environ['FW876_XRAY_TEST_BINARY']).resolve()
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), EXECUTABLE_SHA256,
                         'same version text is insufficient: expected the exact fw876 executable')
        version = subprocess.run([str(binary), 'version'], capture_output=True, text=True, timeout=15)
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertIn('Xray ' + VERSION.split('-')[0], version.stdout)
        with tempfile.TemporaryDirectory(prefix='fw876-core-config-') as directory:
            cases = {**shared.generated_configs(), **private_configs()}
            self.assertTrue(any(name.startswith('passwall2/') for name in cases))
            self.assertTrue(any(name.startswith('ssrplus/fw-') for name in cases))
            for index, (name, config) in enumerate(cases.items()):
                with self.subTest(name=name):
                    result = shared.check_core_config(str(binary), config, Path(directory) / f'{index}.json')
                    self.assertEqual(result.returncode, 0, name + '\n' + result.stdout + result.stderr)
            invalid = {'outbounds': [{'protocol': 'invalid-validation-control'}]}
            result = shared.check_core_config(str(binary), invalid, Path(directory) / 'invalid.json')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unknown config id: invalid-validation-control', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
