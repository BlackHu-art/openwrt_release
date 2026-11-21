#!/usr/bin/env python3
"""Resolve the real iStoreX -> store -> tar -> xz meta-package dependency.

Package definitions, LuCI expansion, metadata generation and Kconfig evaluation
are real. Unrelated dependencies are independent leaves in this bounded model;
full target configuration was separately reproduced with the pinned core/feeds.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from test_kconfig_compat import command, evaluate, stage, write


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/istorex-selection'
SHARED = ROOT / 'tests/fixtures/kconfig-compat'
MANAGED = ROOT / 'wrt_core/managed/packages'
GROUP = ('luci-app-istorex', 'quickstart', 'luci-app-quickstart', 'luci-app-store',
         'taskd', 'luci-lib-taskd', 'luci-lib-xterm')
DOCKER = ('luci-app-dockerman', 'luci-i18n-dockerman-zh-cn', 'luci-lib-docker',
          'docker', 'dockerd', 'docker-compose', 'containerd', 'runc')


def generate(build):
    stage(build)
    for section in ('include', 'scripts'):
        shutil.copytree(FIXTURE / 'core' / section, build / section, dirs_exist_ok=True)
    (build / 'feeds/luci').mkdir(parents=True)
    shutil.copyfile(SHARED / 'variants/fwknop/master/luci/luci.mk', build / 'feeds/luci/luci.mk')
    shutil.copytree(FIXTURE / 'packages/utils', build / 'feeds/packages/utils')
    for name in GROUP:
        shutil.copytree(MANAGED / name, build / 'feeds/custom_feed' / name)
    packages = ['feeds/custom_feed/' + name for name in GROUP]
    packages += ['feeds/packages/utils/tar', 'feeds/packages/utils/xz']
    dumps = []
    for package in packages:
        relative = os.path.relpath(build, build / package).replace('\\', '/')
        result = command([os.environ.get('MAKE') or 'make', '--no-print-directory', '-s',
                          'DUMP=1', 'TOPDIR=' + relative, 'INCLUDE_DIR=' + relative + '/include',
                          '__pkg_source_makefile=' + package, 'dumpinfo'], build / package)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        dumps.append('Source-Makefile: ' + package + '/Makefile\n' +
                     result.stdout.replace((build / package).as_posix(), package))
    metadata = '\n'.join(dumps)
    defined = set(re.findall(r'^Package: (\S+)', metadata, re.M))
    provided = set(' '.join(re.findall(r'^Provides: (.*)', metadata, re.M)).split())
    leaves = set(DOCKER)
    for dependencies in re.findall(r'^Depends: (.*)', metadata, re.M):
        for dependency in dependencies.split():
            if not dependency.startswith('@'):
                name = dependency.lstrip('+').split(':')[-1]
                if name not in defined | provided:
                    leaves.add(name)
    for name in sorted(leaves):
        metadata += (f'\nSource-Makefile: package/leaves/{name}/Makefile\nPackage: {name}\n'
                     f'Category: Libraries\nTitle: {name}\nType: ipkg\nDescription: leaf\n@@\n')
    write(build / 'packageinfo', metadata)
    # Apply the same existing compatibility transformation as production.
    script = build / 'scripts/package-metadata.pl'
    write(script, script.read_text(encoding='utf-8').replace('<PACKAGE_$pkgname', '!=y'))
    result = command(['perl', 'scripts/package-metadata.pl', 'config', 'packageinfo'], build)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    modules = 'modules' if os.environ.get('KCONFIG_CONF') else 'option modules'
    prelude = ('mainmenu "iStoreX real metadata regression"\nconfig MODULES\n bool\n ' +
               modules + '\n default y\n')
    for name in ('ALL', 'ALL_NONSHARED', 'aarch64', 'arm', 'x86_64', 'USE_FS_ACL_ATTR'):
        prelude += f'config {name}\n bool "{name}"\n'
    write(build / 'Kconfig', prelude + result.stdout)


def requested(device):
    text = '\n'.join((ROOT / 'wrt_core/deconfig' / name).read_text(encoding='utf-8')
                     for name in (device + '.config', 'compile_base.config', 'fragments/proxy.config'))
    values = dict(re.findall(r'^CONFIG_([^=]+)=([ymn])$', text, re.M))
    # These two actual devices share the aarch64 Filogic target. Hardware
    # defaults are outside this package-metadata model, not inferred from LuCI.
    values['aarch64'] = 'y'
    return values


class IstorexSelection(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='istorex-selection-')
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name)
        generate(self.build)

    def test_original_ax_request_exposes_missing_xz_meta_package(self):
        selections = requested('jdcloud_ax6000_immwrt')
        self.assertEqual(selections['PACKAGE_luci-app-istorex'], 'y')
        selections.pop('PACKAGE_xz-utils', None)
        values = evaluate(self.build, selections)
        self.assertEqual(values.get('PACKAGE_TAR_XZ'), 'y')
        self.assertEqual(values.get('PACKAGE_xz-utils', 'n'), 'n')
        self.assertEqual(values.get('PACKAGE_luci-app-istorex', 'n'), 'n')
        config = (self.build / 'Kconfig').read_text(encoding='utf-8')
        self.assertIn('depends on !(PACKAGE_TAR_XZ) || PACKAGE_xz-utils', config)

    def test_current_ax_request_keeps_istorex_and_docker_exclusions(self):
        selections = requested('jdcloud_ax6000_immwrt')
        self.assertEqual(selections['PACKAGE_luci-app-istorex'], 'y')
        values = evaluate(self.build, selections)
        for package in (*GROUP, 'tar', 'xz', 'xz-utils'):
            self.assertEqual(values.get('PACKAGE_' + package), 'y', package)
        self.assertEqual(values.get('PACKAGE_TAR_XZ'), 'y')
        for package in DOCKER:
            self.assertEqual(selections.get('PACKAGE_' + package), 'n', package)
            self.assertEqual(values.get('PACKAGE_' + package, 'n'), 'n', package)

    def test_existing_rax_request_still_resolves_same_chain(self):
        values = evaluate(self.build, requested('cmcc_rax3000m_immwrt'))
        for package in ('luci-app-istorex', 'luci-app-store', 'tar', 'xz', 'xz-utils'):
            self.assertEqual(values.get('PACKAGE_' + package), 'y', package)

    def test_unselected_istorex_is_not_enabled_by_xz_meta_package(self):
        selections = requested('jdcloud_ax6000_immwrt')
        selections['PACKAGE_luci-app-istorex'] = 'n'
        values = evaluate(self.build, selections)
        self.assertEqual(values.get('PACKAGE_luci-app-istorex', 'n'), 'n')

    def test_upstream_recipe_framework_and_license_fixture_identities(self):
        manifest = json.loads((FIXTURE / 'sources.json').read_bytes())
        for name, expected in manifest['files'].items():
            data = (FIXTURE / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256'], name)
            blob = b'blob ' + str(len(data)).encode() + b'\0' + data
            self.assertEqual(hashlib.sha1(blob).hexdigest(), expected['git_blob'], name)


if __name__ == '__main__':
    unittest.main()
