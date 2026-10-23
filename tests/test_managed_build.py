#!/usr/bin/env python3
"""Exercise production source preparation using real local package payloads."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_passwall2_tls as shell

ROOT = Path(__file__).resolve().parents[1]


class ManagedBuild(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="managed-build-")
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        # The build checkout is itself a Git repository. Local packages have no
        # nested .git; the real HomeProxy patch path must still work here.
        subprocess.run(["git", "init", "-q", str(self.build)], check=True)
        self.environment = dict(os.environ, BASE_PATH=shell.bash_path(ROOT / "wrt_core"),
                                BUILD_DIR=shell.bash_path(self.build),
                                TEST_PYTHON=Path(sys.executable).as_posix())

    def run_stage(self, body):
        script = '''set -euo pipefail
source "$BASE_PATH/update.sh"
python3() { "$TEST_PYTHON" "$@"; }
git_retry() { echo 'unexpected managed source network download' >&2; return 91; }
curl_retry() { echo 'unexpected managed support network download' >&2; return 92; }
''' + body
        return subprocess.run([shell.bash_executable(), "--noprofile", "--norc", "-c", script],
                              env=self.environment, text=True, encoding="utf-8", errors="strict",
                              capture_output=True, timeout=120)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_homeproxy_uses_local_source_and_applies_patches_inside_parent_git(self):
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed/luci-app-homeproxy"
install_managed_package luci-app-homeproxy "$target"
update_homeproxy
! test -e "$target/.git"
grep -q ucode-mod-math "$target/Makefile"
grep -q 'disable_expire: strToBool(dns_disable_cache_expire)' "$target/root/etc/homeproxy/scripts/generate_client.uc"
git hash-object --no-filters "$target/root/etc/homeproxy/scripts/generate_client.uc" > "$BUILD_DIR/first-hash"
update_homeproxy
git hash-object --no-filters "$target/root/etc/homeproxy/scripts/generate_client.uc" > "$BUILD_DIR/second-hash"
cmp "$BUILD_DIR/first-hash" "$BUILD_DIR/second-hash"
''')
        self.assert_ok(result)
        self.assertIn("HomeProxy", result.stdout)

    def test_themes_are_local_and_argon_settings_have_one_owner(self):
        result = self.run_stage('''
mkdir -p "$BUILD_DIR/feeds/luci/applications/luci-app-argon-config/root/etc/config"
printf 'stale' > "$BUILD_DIR/feeds/luci/applications/luci-app-argon-config/root/etc/config/argon"
mkdir -p "$BUILD_DIR/files/etc/config"
printf 'user custom theme' > "$BUILD_DIR/files/etc/config/argon"
update_argon
update_argon_config
update_aurora
update_aurora_config
test ! -e "$BUILD_DIR/feeds/luci/applications/luci-app-argon-config"
test -f "$BUILD_DIR/feeds/luci/themes/luci-theme-argon/compat/luci-app-argon-config/Makefile"
test -f "$BUILD_DIR/feeds/luci/themes/luci-theme-argon/root/etc/config/argon"
test -f "$BUILD_DIR/feeds/luci/themes/luci-theme-aurora/Makefile"
test -f "$BUILD_DIR/feeds/luci/applications/luci-app-aurora-config/Makefile"
grep -q 'defaults completed; existing settings preserved' "$BUILD_DIR/feeds/luci/applications/luci-app-aurora-config/root/etc/uci-defaults/80_aurora"
test "$(cat "$BUILD_DIR/files/etc/config/argon")" = 'user custom theme'
''')
        self.assert_ok(result)

    def test_quickstart_retains_offline_controller_and_dependency_fixes(self):
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed"
install_managed_package quickstart "$target/quickstart"
mkdir -p "$target/luci-app-quickstart/luasrc/controller"
printf 'old controller' > "$target/luci-app-quickstart/luasrc/controller/istore_backend.lua"
fix_quickstart
cmp "$BASE_PATH/managed/compat/istore_backend.lua" "$target/luci-app-quickstart/luasrc/controller/istore_backend.lua"
! grep -Eq '[+]smartmontools|[+]mdadm|[+]parted|[+]e2fsprogs' "$target/quickstart/Makefile"
''')
        self.assert_ok(result)

    def test_managed_core_recipes_keep_complete_fw_xray_and_existing_sing_box(self):
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed"
install_managed_package xray-core "$target/xray-core"
install_managed_package sing-box "$target/sing-box"
for plugin in passwall2; do
    mkdir -p "$target/luci-app-$plugin/luasrc/$plugin"
    cp "$BASE_PATH/../maintenance/plugins/$plugin/luci-app-$plugin/luasrc/$plugin/util_xray.lua" \
       "$target/luci-app-$plugin/luasrc/$plugin/util_xray.lua"
done
mkdir -p "$BUILD_DIR/feeds/packages/lang/golang/golang"
printf 'GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=3\n' > "$BUILD_DIR/feeds/packages/lang/golang/golang/Makefile"
fix_xray_core_compat "$target/xray-core"
grep -q '^PKG_VERSION:=26.10.21$' "$target/xray-core/Makefile"
grep -q '^PKG_VERSION:=1.14.3$' "$target/sing-box/Makefile"
test "$(find "$target/xray-core/patches" -name '*.patch' | wc -l)" -eq 10
grep -q '^PKG_VERSION:=26.10.21$' "$BASE_PATH/managed/packages/xray-core/Makefile"
fix_xray_core_compat "$target/xray-core"
''')
        self.assert_ok(result)

    def test_tcping_refresh_checks_local_fw_source_without_network_or_changes(self):
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed/tcping"
install_managed_package tcping "$target"
update_tcping
cmp "$BASE_PATH/managed/packages/tcping/Makefile" "$target/Makefile"
printf '\\n# unreviewed override\\n' >> "$target/Makefile"
if update_tcping; then echo 'tcping drift was accepted' >&2; exit 93; fi
''')
        self.assert_ok(result)

    def test_feed_cleanup_removes_conflicting_fw_recipes_but_keeps_unselected_packages(self):
        result = self.run_stage('''
cd "$BUILD_DIR"
for package in net/dns2tcp net/microsocks lang/lua-neturl utils/upx; do
    mkdir -p "feeds/packages/$package"
    printf 'stale source' > "feeds/packages/$package/Makefile"
done
mkdir -p feeds/packages/net/unrelated
remove_unwanted_packages
for package in net/dns2tcp net/microsocks lang/lua-neturl utils/upx; do
    test ! -e "feeds/packages/$package"
done
test -d feeds/packages/net/unrelated
''')
        self.assert_ok(result)

    def test_external_import_rejects_managed_names_before_any_network_or_file_changes(self):
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed"
install_managed_package tcping "$target/tcping"
if sync_sparse_packages_to_feed_dir https://example.invalid/feed.git main "$target" test tcping; then
    echo 'managed sparse overwrite allowed' >&2; exit 93
fi
if sync_repo_root_package_to_feed_dir https://example.invalid/feed.git main "$target" test tcping; then
    echo 'managed root overwrite allowed' >&2; exit 94
fi
cmp "$BASE_PATH/managed/packages/tcping/Makefile" "$target/tcping/Makefile"
''')
        self.assert_ok(result)
        self.assertNotIn("unexpected managed source network download", result.stderr)
        self.assertIn("managed package cannot be imported externally", result.stderr)

    def test_oaf_compatibility_is_called_on_the_real_managed_source(self):
        # Only the two translation symlinks are POSIX-only; the actual affected
        # backend and LuCI ACL inputs are ordinary files on Windows too.
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed"
install_managed_package open-app-filter "$target/open-app-filter"
mkdir -p "$target/luci-app-oaf/root/usr/share/rpcd/acl.d"
cp "$BASE_PATH/managed/packages/luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json" \
   "$target/luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json"
update_oaf_deconfig
test -f "$target/open-app-filter/files/fwx"
test -f "$target/open-app-filter/files/99_disable_oaf"
test ! -e "$target/luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json"
update_oaf_deconfig
''')
        self.assert_ok(result)

    def test_unknown_oaf_version_cannot_silently_skip_default_repairs(self):
        result = self.run_stage('''
target="$BUILD_DIR/feeds/custom_feed"
install_managed_package open-app-filter "$target/open-app-filter"
mkdir -p "$target/luci-app-oaf/root/usr/share/rpcd/acl.d"
cp "$BASE_PATH/managed/packages/luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json" \
   "$target/luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json"
sed -i 's/PKG_VERSION:=7.0.1/PKG_VERSION:=8.0.0/' "$target/open-app-filter/Makefile"
if update_oaf_deconfig; then echo 'unknown OAF recipe accepted' >&2; exit 94; fi
test ! -e "$target/open-app-filter/files/fwx"
test -f "$target/luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json"
''')
        self.assert_ok(result)

    @unittest.skipIf(os.name == "nt", "complete feed materialization restores real symlinks in Linux CI")
    def test_custom_feed_imports_managed_packages_locally_before_indexing(self):
        result = self.run_stage('''
FEEDS_CONF=feeds.conf.default
: > "$BUILD_DIR/$FEEDS_CONF"
sync_sparse_packages_to_feed_dir() {
    local url=$1 branch=$2 target=$3 label=$4 package
    shift 4
    for package in "$@"; do
        case "$package" in
            luci-app-ssr-plus|xray-core|chinadns-ng|dns2socks|dns2tcp|lua-neturl|microsocks|mosdns|shadowsocks-rust|shadowsocksr-libev|simple-obfs|tcping|v2ray-plugin|ipt2socks|upx|sing-box|luci-app-homeproxy|oaf|open-app-filter|luci-app-oaf|luci-app-istorex|quickstart|luci-app-quickstart|luci-app-store|taskd|luci-lib-taskd|luci-lib-xterm)
                echo "managed package requested remotely: $package" >&2; return 93 ;;
        esac
        mkdir -p "$target/$package"
        printf 'PKG_NAME:=%s\n' "$package" > "$target/$package/Makefile"
    done
}
sync_repo_root_package_to_feed_dir() {
    mkdir -p "$3/$5"; printf 'DEPENDS:=+luci-js-deps +luci-base\n' > "$3/$5/Makefile"
}
network_retry() {
    test "$*" = './scripts/feeds update custom_feed'
    test -f "$BUILD_DIR/custom_feed/luci-app-homeproxy/Makefile"
    test -L "$BUILD_DIR/custom_feed/luci-app-oaf/po/zh-cn"
    mkdir -p "$BUILD_DIR/feeds"
    ln -s "$BUILD_DIR/custom_feed" "$BUILD_DIR/feeds/custom_feed"
}
install_custom_feed
grep -Fq "src-link custom_feed $BUILD_DIR/custom_feed" "$BUILD_DIR/$FEEDS_CONF"
test -f "$BUILD_DIR/feeds/custom_feed/luci-app-istorex/Makefile"
''')
        self.assert_ok(result)


if __name__ == "__main__":
    unittest.main()
