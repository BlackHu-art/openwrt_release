#!/usr/bin/env python3
"""Contracts that prevent required plugin validation from silently disappearing."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ValidationGates(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / '.github/workflows/test_ssrplus.yml').read_text(encoding='utf-8'))
        self.job = self.workflow['jobs']['regression']

    def test_workflow_provisions_required_runtimes_before_regression(self):
        steps = self.job['steps']
        regression = next(i for i, step in enumerate(steps) if 'bash tests/run_all.sh' in step.get('run', ''))
        provision = steps[:regression]
        ruby = [s for s in provision if s.get('uses', '').startswith('ruby/setup-ruby@')]
        node = [s for s in provision if s.get('uses', '').startswith('actions/setup-node@')]
        self.assertEqual(len(ruby), 1, 'Ruby 3.4 must be provisioned before tests')
        self.assertEqual(str(ruby[0]['with']['ruby-version']), '3.4')
        self.assertEqual(len(node), 1, 'Node must be provisioned before tests')
        self.assertEqual(str(node[0]['with']['node-version']), '22')
        scripts = '\n'.join(s.get('run', '') for s in provision)
        self.assertIn('python tests/fetch_xray_test_core.py --output', scripts)
        self.assertIn('XRAY_TEST_BINARY=', scripts)
        self.assertIn('python tests/fetch_fw876_xray.py --output', scripts)
        self.assertIn('FW876_XRAY_TEST_BINARY=', scripts)
        self.assertIn('GITHUB_ENV', scripts)
        self.assertIn('python tests/fetch_mihomo_test_cores.py --generation old --output', scripts)
        self.assertIn('python tests/fetch_mihomo_test_cores.py --generation new --output', scripts)
        self.assertIn('MIHOMO_OLD_TEST_BIN=', scripts)
        self.assertIn('MIHOMO_NEW_TEST_BIN=', scripts)
        environment = dict(self.job.get('env', {}), **steps[regression].get('env', {}))
        for required in ('REQUIRE_XRAY_TEST_CORE', 'REQUIRE_FW876_XRAY_TEST_CORE', 'REQUIRE_SIMPLE_OBFS_DOWNLOAD', 'OPENCLASH_REQUIRE_RUBY34', 'OPENCLASH_REQUIRE_NODE', 'OPENCLASH_REQUIRE_MIHOMO'):
            self.assertEqual(str(environment.get(required)), '1', required + ' must be enforced')

    def test_plugin_repair_inputs_trigger_validation(self):
        triggers = self.workflow.get('on', self.workflow.get(True, {}))
        required = {
            'wrt_core/patches/openclash-*.patch', 'wrt_core/patches/adguardhome-*.patch',
            'wrt_core/compat/adguardhome/**', 'wrt_core/patches/passwall2-singbox-*.patch',
            'wrt_core/patches/passwall2-fw876-*.patch',
            'wrt_core/patches/xray-core-*.patch', 'wrt_core/compat/proxy-cores/**',
            'maintenance/plugins/passwall2/**',
            'maintenance/plugins/manifests/**', 'wrt_core/patches/homeproxy-*.patch',
            'wrt_core/managed/**', 'wrt_core/managed_plugins.py',
            'wrt_core/simple_obfs_compat.py', 'wrt_core/download_compat.py',
            'wrt_core/quickfile_verify.py', 'wrt_core/check_selected_plugins.py', 'wrt_core/deconfig/**', 'wrt_core/oaf_compat.py', 'wrt_core/theme_compat.py',
            'wrt_core/patches/990_set_argon_primary',
        }
        for event in ('push', 'pull_request'):
            self.assertFalse(required - set(triggers[event]['paths']), (event, required - set(triggers[event]['paths'])))

    def test_required_tools_cannot_be_silently_skipped(self):
        probes = (
            ('test_shared_xray_compat', 'REQUIRE_XRAY_TEST_CORE', 'XRAY_TEST_BINARY', 'Xray'),
            ('test_fw876_xray_compat', 'REQUIRE_FW876_XRAY_TEST_CORE', 'FW876_XRAY_TEST_BINARY', 'fw876 Xray'),
            ('test_simple_obfs_download', 'REQUIRE_SIMPLE_OBFS_DOWNLOAD', 'SIMPLE_OBFS_DOWNLOAD_UNUSED', 'simple-obfs'),
            ('test_openclash_tun_stack', 'OPENCLASH_REQUIRE_MIHOMO', 'MIHOMO_OLD_TEST_BIN', 'Mihomo'),
            ('test_openclash_backports', 'OPENCLASH_REQUIRE_NODE', 'NODE', 'Node'),
            ('test_openclash_filename', 'OPENCLASH_REQUIRE_NODE', 'NODE', 'Node'),
        )
        for module, required, binary, label in probes:
            with self.subTest(module=module):
                environment = dict(os.environ, **{required: '1'})
                environment.pop(binary, None)
                # Model a missing external runtime without changing the host PATH.
                code = 'import shutil; shutil.which=lambda name: None; import ' + module
                result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT / 'tests',
                                        env=environment, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, 'missing required ' + label + ' was silently accepted')
                self.assertIn(label, result.stderr)

    def test_required_ruby_cannot_be_silently_skipped(self):
        environment = dict(os.environ, OPENCLASH_REQUIRE_RUBY34='1')
        environment.pop('RUBY', None)
        environment.pop('OPENCLASH_REQUIRE_NODE', None)
        code = (
            'import shutil; shutil.which=lambda name: None; '
            'from test_openclash_backports import OpenClashBackports; '
            'OpenClashBackports("test_ruby_guard_accepts_literals_and_rejects_unsafe_calls")'
            '.test_ruby_guard_accepts_literals_and_rejects_unsafe_calls()'
        )
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT / 'tests',
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Ruby is required', result.stderr)


if __name__ == '__main__':
    unittest.main()
