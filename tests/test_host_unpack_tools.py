#!/usr/bin/env python3
"""Execute pinned host-tool dependencies and unpack rules around early prepare."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from shell_test_helpers import bash_executable, bash_path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/download-toplevel'
SOURCE = FIXTURES / 'ec9ef10e'
BASH = bash_executable()


def archive(path, prefix, contents):
    with tarfile.open(path, 'w:gz') as packed:
        data = contents.encode()
        item = tarfile.TarInfo(prefix + '/payload.txt')
        item.size, item.mode = len(data), 0o644
        packed.addfile(item, io.BytesIO(data))


class HostUnpackToolOrdering(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='host-unpack-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(SOURCE / 'include', self.root / 'include')
        shutil.copytree(SOURCE / 'tools', self.root / 'tools')
        shutil.copy(SOURCE / 'download.mk', self.root / 'include/toplevel.mk')
        (self.root / 'dl').mkdir()
        archive(self.root / 'dl/miniupnpd-fixture.tar.gz', 'miniupnpd-fixture', 'prepared miniupnpd payload')
        archive(self.root / 'dl/libdeflate-1.22.tar.gz', 'libdeflate-1.22', 'bootstrap gzip payload')
        (self.root / '.config').write_text('CONFIG_PACKAGE_miniupnpd-nftables=y\n')
        # The compiler boundary installs a wrapper invoking real system gzip
        # under the host unpacker's name. Tool selection/dependencies, the libdeflate
        # recipe's bootstrap override and both source unpack pipelines are real.
        (self.root / 'rules.mk').write_text('''TOPDIR:=$(CURDIR)
INCLUDE_DIR:=$(TOPDIR)/include
STAGING_DIR_HOST:=$(TOPDIR)/staging_dir/host
DL_DIR:=$(TOPDIR)/dl
HOST_BUILD_DIR:=$(TOPDIR)/host-build/libdeflate-1.22
TAR:=tar
TAR_OPTIONS:=-xf -
SH_FUNC=set -o pipefail;
ext=$(word $(words $(subst ., ,$(1))),$(subst ., ,$(1)))
''')
        (self.root / 'include/host-build.mk').write_text('include $(INCLUDE_DIR)/unpack.mk\n')
        (self.root / 'producer.mk').write_text('''TOPDIR:=$(CURDIR)
include tools/libdeflate/Makefile
.PHONY: bootstrap-unpack
bootstrap-unpack:
\t@mkdir -p "$(HOST_BUILD_DIR)/.."
\t$(HOST_UNPACK)
\t@test "$$(cat "$(HOST_BUILD_DIR)/payload.txt")" = 'bootstrap gzip payload'
\t@printf 'bootstrap-unpack\\n' >> calls
''')
        (self.root / 'Makefile').write_text('''.DEFAULT_GOAL := world
SHELL:=$(TEST_BASH)
TOPDIR:=$(CURDIR)
STAGING_DIR_HOST:=$(CURDIR)/staging_dir/host
DL_DIR:=$(CURDIR)/dl
BUILD_DIR:=$(CURDIR)/build
PKG_SOURCE:=miniupnpd-fixture.tar.gz
PKG_BUILD_DIR:=$(BUILD_DIR)/miniupnpd-fixture
TAR:=tar
TAR_OPTIONS:=-xf -
SH_FUNC=set -o pipefail;
ext=$(word $(words $(subst ., ,$(1))),$(subst ., ,$(1)))
SUBMAKE="$(MAKE)" --no-print-directory -f stages.mk
HOST_OS:=Linux
# Retain the pinned tools/Makefile dependency assignments and instantiate only
# their native target edges; recursive compiler dispatch is the isolated seam.
define subdir
$(foreach tool,$(tools-y),$(eval tools/$(tool)/compile: $($(curdir)/$(tool)/compile) $($(curdir)/)))
endef
include tools/Makefile
include include/unpack.mk
.PHONY: world FORCE prereq tools/flock/compile tools/libdeflate/compile tools/zstd/compile package/feeds/packages/miniupnpd/prepare
world:
\t@printf 'compile\\n' >> calls
FORCE:
prereq:
\t@mkdir -p "$(STAGING_DIR_HOST)/bin"
\t@if [ ! -x "$(STAGING_DIR_HOST)/bin/gzip" ]; then printf '#!/bin/sh\\nexec "%s" "$$@"\\n' "$(TEST_GZIP)" > "$(STAGING_DIR_HOST)/bin/gzip"; chmod +x "$(STAGING_DIR_HOST)/bin/gzip"; printf 'bootstrap-gzip\\n' >> calls; fi
tools/flock/compile:
\t@touch "$(STAGING_DIR_HOST)/bin/flock"
\t@printf 'tools/flock/compile\\n' >> calls
tools/libdeflate/compile:
\t@printf 'tools/libdeflate/compile\\n' >> calls
\t@if [ -n "$(HOST_FAIL)" ]; then exit $(HOST_FAIL); fi
\t@$(MAKE) --no-print-directory -f producer.mk SHELL="$(TEST_BASH)" bootstrap-unpack
\t@if [ "$(HOST_STALE)" != 1 ]; then cp "$(STAGING_DIR_HOST)/bin/gzip" "$(STAGING_DIR_HOST)/bin/libdeflate-gzip"; chmod +x "$(STAGING_DIR_HOST)/bin/libdeflate-gzip"; fi
tools/zstd/compile:
\t@touch "$(STAGING_DIR_HOST)/bin/zstd"
\t@printf 'tools/zstd/compile\\n' >> calls
package/feeds/packages/miniupnpd/prepare:
\t@mkdir -p "$(PKG_BUILD_DIR)/.."
\t$(PKG_UNPACK)
\t@test "$$(cat "$(PKG_BUILD_DIR)/payload.txt")" = 'prepared miniupnpd payload'
\t@printf 'miniupnpd-prepare\\n' >> calls
include include/toplevel.mk
''')
        (self.root / 'stages.mk').write_text('''%/download:
\t@printf '%s\\n' '$@' >> calls
''')
        result = subprocess.run([BASH, '-c', 'command -v bash; command -v gzip'], text=True, capture_output=True, check=True)
        self.make_bash, self.gzip = result.stdout.strip().splitlines()

    def run_build(self, **variables):
        environment = dict(os.environ, TEST_BASH=self.make_bash, TEST_GZIP=self.gzip,
            CORE_PATH=bash_path(ROOT / 'wrt_core'), TEST_TREE=bash_path(self.root), **variables)
        script = '''set -euo pipefail
cd "$TEST_TREE"
source "$CORE_PATH/modules/build_steps.sh"
nproc() { echo 2; }
verify_ssrplus_built_artifacts() { :; }
build_firmware
'''
        return subprocess.run([BASH, '--noprofile', '--norc', '-c', script], env=environment,
                              capture_output=True, text=True, timeout=45)

    def calls(self):
        path = self.root / 'calls'
        return path.read_text().splitlines() if path.exists() else []

    def test_cold_flock_only_core_installs_required_unpacker_before_package(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(self.calls().index('target/download'), self.calls().index('tools/libdeflate/compile'))
        self.assertLess(self.calls().index('tools/libdeflate/compile'), self.calls().index('miniupnpd-prepare'))
        self.assertLess(self.calls().index('miniupnpd-prepare'), self.calls().index('compile'))
        self.assertIn('bootstrap-gzip', self.calls())
        self.assertIn('bootstrap-unpack', self.calls())
        self.assertNotIn('tools/zstd/compile', self.calls())
        self.assertTrue((self.root / 'logs/miniupnpd-host-tools.log').is_file())

    def test_warm_unpacker_does_not_invoke_or_log_an_extra_build(self):
        tools = self.root / 'staging_dir/host/bin'
        tools.mkdir(parents=True)
        executable = tools / 'libdeflate-gzip'
        executable.write_text('#!/bin/sh\nexec "' + self.gzip + '" "$@"\n')
        executable.chmod(0o755)
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('tools/libdeflate/compile', self.calls())
        self.assertFalse((self.root / 'logs/miniupnpd-host-tools.log').exists())
        self.assertIn('miniupnpd-prepare', self.calls())

    def test_nonexecutable_cached_unpacker_is_reinstalled(self):
        executable = self.root / 'staging_dir/host/bin/libdeflate-gzip'
        executable.parent.mkdir(parents=True)
        executable.write_text('incomplete restored executable\n')
        executable.chmod(0o644)
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('tools/libdeflate/compile', self.calls())
        self.assertIn('miniupnpd-prepare', self.calls())

    def test_core_without_libdeflate_unpack_requirement_keeps_its_native_gzip(self):
        unpack = self.root / 'include/unpack.mk'
        unpack.write_bytes(unpack.read_bytes().replace(b'/bin/libdeflate-gzip', b'/bin/gzip'))
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('tools/libdeflate/compile', self.calls())
        self.assertIn('miniupnpd-prepare', self.calls())

    def test_existing_zstd_dependency_chain_needs_no_second_host_tool_stage(self):
        shutil.copy(FIXTURES / '3fd1e27a/download.mk', self.root / 'include/toplevel.mk')
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(self.calls().index('tools/libdeflate/compile'), self.calls().index('tools/zstd/compile'))
        self.assertEqual(self.calls().count('tools/libdeflate/compile'), 1)
        self.assertFalse((self.root / 'logs/miniupnpd-host-tools.log').exists())

    def test_host_tool_failure_stops_before_prepare_and_compile(self):
        result = self.run_build(HOST_FAIL='23')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('tools/libdeflate/compile', self.calls())
        self.assertNotIn('miniupnpd-prepare', self.calls())
        self.assertNotIn('compile', self.calls())
        self.assertIn('miniupnpd-host-tools failed', result.stderr)

    def test_successful_stale_stamp_without_executable_is_rejected(self):
        result = self.run_build(HOST_STALE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('tools/libdeflate/compile', self.calls())
        self.assertNotIn('miniupnpd-prepare', self.calls())
        self.assertNotIn('compile', self.calls())
        self.assertIn('libdeflate-gzip', result.stderr)
        self.assertIn('miniupnpd-host-tools failed', result.stderr)

    def test_unselected_miniupnpd_does_not_build_an_unpacker(self):
        (self.root / '.config').write_text('# CONFIG_PACKAGE_miniupnpd-nftables is not set\n')
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('tools/libdeflate/compile', self.calls())
        self.assertNotIn('miniupnpd-prepare', self.calls())
        self.assertEqual(self.calls()[-1], 'compile')

    def test_fixture_source_identities_are_exact(self):
        for item in json.loads((FIXTURES / 'host-tools-sources.json').read_text()):
            data = (FIXTURES / item['fixture']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
            self.assertEqual(hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest(), item['git_blob'])


if __name__ == '__main__':
    unittest.main()
