#!/usr/bin/env python3
"""Exercise upstream build repairs at their real shell/Git boundaries."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("BASH") or shutil.which("bash")
NETCONTROL_FIXTURE = ROOT / "tests/fixtures/netcontrol/61364846"


class UpstreamBuildFixes(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="upstream-build-fixes-")
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name)

    def shell(self, source, *arguments):
        environment = dict(os.environ, BUILD_DIR=self.build.as_posix(),
                           BASE_PATH=(ROOT / "wrt_core").as_posix(), LC_ALL="C")
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", source, "upstream-fix", *map(str, arguments)],
                              cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)

    def netcontrol_donor(self, *, with_second_package=False):
        """Create a real Git donor whose default branch has newer, wrong bytes."""
        writer = self.build / "netcontrol-donor"
        shutil.copytree(NETCONTROL_FIXTURE, writer)
        if with_second_package:
            (writer / "second-package").mkdir()
            (writer / "second-package/Makefile").write_text("PKG_NAME:=second-package\n")
        def git(*arguments):
            return subprocess.run(["git", "-C", str(writer), "-c", "core.autocrlf=false",
                                   "-c", "commit.gpgsign=false", *arguments],
                                  capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Source fixture")
        git("config", "user.email", "source-fixture@example.invalid")
        git("add", ".")
        git("commit", "-qm", "reviewed source fixture")
        reviewed = git("rev-parse", "HEAD")
        (writer / "luci-app-netcontrol/Makefile").write_text("PKG_NAME:=unreviewed-newer-package\n")
        git("commit", "-qam", "unreviewed newer default branch")
        return writer, reviewed

    def test_pinned_sparse_package_copies_reviewed_recipe_helpers_and_modes(self):
        donor, reviewed = self.netcontrol_donor()
        target = self.build / "imported"
        target.mkdir()
        result = self.shell('source "$BASE_PATH/modules/custom_feed.sh"; '
                            'git_retry() { git -c core.autocrlf=false "$@"; }; '
                            'sync_sparse_packages_to_feed_dir "$1" "$3" "$2" fixture luci-app-netcontrol',
                            donor.as_uri(), target, reviewed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        package = target / "luci-app-netcontrol"
        expected = NETCONTROL_FIXTURE / "luci-app-netcontrol"
        self.assertEqual(sorted(p.relative_to(package) for p in package.rglob("*") if p.is_file()),
                         sorted(p.relative_to(expected) for p in expected.rglob("*") if p.is_file()))
        for source in expected.rglob("*"):
            if source.is_file():
                actual = package / source.relative_to(expected)
                self.assertEqual(actual.read_bytes(), source.read_bytes())
                if os.name != "nt":
                    self.assertEqual(actual.stat().st_mode & 0o777, source.stat().st_mode & 0o777)
        self.assertFalse((package / ".git").exists())

    def test_missing_sparse_pin_keeps_old_package_and_never_publishes_head(self):
        donor, _ = self.netcontrol_donor()
        target = self.build / "imported"
        package = target / "luci-app-netcontrol"
        package.mkdir(parents=True)
        (package / "Makefile").write_text("existing reviewed package\n")
        result = self.shell('source "$BASE_PATH/modules/custom_feed.sh"; '
                            'git_retry() { git -c core.autocrlf=false "$@"; }; '
                            'sync_sparse_packages_to_feed_dir "$1" "$3" "$2" fixture luci-app-netcontrol',
                            donor.as_uri(), target, "0" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((package / "Makefile").read_text(), "existing reviewed package\n")
        self.assertEqual([p.name for p in package.iterdir()], ["Makefile"])

    def sparse_with_injection(self, donor, reviewed, target, injection="", *packages):
        script = r'''source "${SPARSE_IMPORT_MODULE:-$BASE_PATH/modules/custom_feed.sh}"
git_retry() {
    if [[ "$1" == clone ]]; then
        CLONE_DEST=${@: -1}
        printf '%s\n' "$CLONE_DEST" > "$BUILD_DIR/clone-destination"
    fi
    git -c core.autocrlf=false "$@"
}
TARGET=$2
''' + injection + r'''
if sync_sparse_packages_to_feed_dir "$1" "$3" "$2" fixture "${@:4}"; then
    touch "$BUILD_DIR/indexed"
else
    exit $?
fi
'''
        return self.shell(script, donor.as_uri(), target, reviewed,
                          *(packages or ("luci-app-netcontrol",)))

    def test_sparse_publication_failure_removes_partial_new_files_and_restores_old_package(self):
        donor, reviewed = self.netcontrol_donor()
        target = self.build / "imported"
        package = target / "luci-app-netcontrol"
        package.mkdir(parents=True)
        (package / "Makefile").write_text("old reviewed recipe\n")
        (package / "old-runtime").write_text("keep existing complete runtime\n")
        injection = r'''
mv() {
    local args=("$@") src=${@: -2:1} dst=${@: -1}
    if [[ "$src" == */luci-app-netcontrol && "$src" != */previous/* &&
          ( "$dst" == "$TARGET/" || "$dst" == "$TARGET/luci-app-netcontrol" ) ]]; then
        mkdir -p "$TARGET/luci-app-netcontrol"
        cp "$src/Makefile" "$TARGET/luci-app-netcontrol/Makefile"
        return 79
    fi
    command mv "${args[@]}"
}
'''
        result = self.sparse_with_injection(donor, reviewed, target, injection)
        self.assertNotEqual(result.returncode, 0, "partial move was accepted for feed indexing")
        self.assertFalse((self.build / "indexed").exists())
        self.assertEqual((package / "Makefile").read_text(), "old reviewed recipe\n")
        self.assertEqual((package / "old-runtime").read_text(), "keep existing complete runtime\n")
        self.assertEqual(sorted(p.name for p in package.iterdir()), ["Makefile", "old-runtime"])

    def test_sparse_publication_prevalidates_every_requested_directory(self):
        donor, reviewed = self.netcontrol_donor()
        target = self.build / "imported"
        package = target / "luci-app-netcontrol"
        package.mkdir(parents=True)
        (package / "Makefile").write_text("old reviewed recipe\n")
        result = self.sparse_with_injection(donor, reviewed, target, "",
                                            "luci-app-netcontrol", "missing-package")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.build / "indexed").exists())
        self.assertEqual((package / "Makefile").read_text(), "old reviewed recipe\n")

    def test_sparse_clone_is_staged_below_target_filesystem(self):
        donor, reviewed = self.netcontrol_donor()
        target = self.build / "imported"
        target.mkdir()
        result = self.sparse_with_injection(donor, reviewed, target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        clone = Path((self.build / "clone-destination").read_text().strip())
        self.assertTrue(clone.is_relative_to(target), "clone was staged in a different temporary filesystem")

    def test_sparse_cleanup_failure_is_not_reported_as_indexable_success(self):
        donor, reviewed = self.netcontrol_donor()
        target = self.build / "imported"
        target.mkdir()
        injection = r'''
rm() {
    local path=${@: -1}
    if [[ -n ${CLONE_DEST:-} && ( "$CLONE_DEST" == "$path" || "$CLONE_DEST" == "$path/"* ) ]]; then
        return 78
    fi
    command rm "$@"
}
'''
        result = self.sparse_with_injection(donor, reviewed, target, injection)
        # The old global-TMPDIR implementation needs this fixture-only cleanup.
        clone = Path((self.build / "clone-destination").read_text().strip())
        if clone.exists() and not clone.is_relative_to(self.build):
            shutil.rmtree(clone)
        self.assertNotEqual(result.returncode, 0, "failed staging cleanup was accepted for indexing")
        self.assertFalse((self.build / "indexed").exists())

    def test_sparse_failed_target_removal_cannot_publish_or_reach_index(self):
        donor, reviewed = self.netcontrol_donor()
        target = self.build / "imported"
        package = target / "luci-app-netcontrol"
        package.mkdir(parents=True)
        (package / "Makefile").write_text("old reviewed recipe\n")
        injection = r'''
REMOVAL_FAILED=0
rm() {
    if [[ ${@: -1} == "$TARGET/luci-app-netcontrol" && "$REMOVAL_FAILED" == 0 ]]; then
        REMOVAL_FAILED=1
        return 75
    fi
    command rm "$@"
}
'''
        result = self.sparse_with_injection(donor, reviewed, target, injection)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.build / "indexed").exists())
        self.assertEqual((package / "Makefile").read_text(), "old reviewed recipe\n")

    def test_sparse_later_publication_failure_rolls_back_all_prior_replacements(self):
        donor, reviewed = self.netcontrol_donor(with_second_package=True)
        target = self.build / "imported"
        for package, content in (("luci-app-netcontrol", "old first package\n"),
                                 ("second-package", "old second package\n")):
            (target / package).mkdir(parents=True)
            (target / package / "Makefile").write_text(content)
        injection = r'''
mv() {
    local src=${@: -2:1} dst=${@: -1}
    if [[ "$src" == */second-package && "$src" != */previous/* &&
          ( "$dst" == "$TARGET/" || "$dst" == "$TARGET/second-package" ) ]]; then
        mkdir -p "$TARGET/second-package"
        cp "$src/Makefile" "$TARGET/second-package/Makefile"
        return 79
    fi
    command mv "$@"
}
'''
        result = self.sparse_with_injection(donor, reviewed, target, injection,
                                            "luci-app-netcontrol", "second-package")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.build / "indexed").exists())
        self.assertEqual((target / "luci-app-netcontrol/Makefile").read_text(), "old first package\n")
        self.assertEqual((target / "second-package/Makefile").read_text(), "old second package\n")

    @unittest.skipIf(os.name == "nt", "complete managed feed materialization restores POSIX symlinks")
    def test_s20m_installs_netcontrol_before_index_and_others_do_not_fetch_it(self):
        donor, reviewed = self.netcontrol_donor()
        script = r'''set -euo pipefail
source "$BASE_PATH/modules/custom_feed.sh"
source "$BASE_PATH/modules/feeds.sh"
eval "$(declare -f sync_sparse_packages_to_feed_dir | sed '1s/sync_sparse_packages_to_feed_dir/real_sparse_import/')"
sync_sparse_packages_to_feed_dir() {
    case "$1" in
        https://github.com/rule2c/luci-app-netcontrol.git)
            local ref=$2
            [[ "$ref" != 61364846e1188d87801f778749efc4f2a4deac43 ]] || ref=$REVIEWED
            real_sparse_import "$DONOR" "$ref" "$3" "$4" "${@:5}" ;;
        https://github.com/kenzok8/small-package.git|https://github.com/sbwml/luci-app-mosdns.git|https://github.com/sirpdboy/luci-app-partexp.git|https://github.com/nikkinikki-org/OpenWrt-nikki.git)
            local target=$3 package
            shift 4
            for package in "$@"; do mkdir -p "$target/$package"; done ;;
        *) echo "unexpected donor: $1" >&2; return 91 ;;
    esac
}
sync_repo_root_package_to_feed_dir() {
    [[ "$1" == https://github.com/adminchenyu/eMMC-Health.git ]]
    mkdir -p "$3/$5"
    printf 'DEPENDS:=+luci-base\n' > "$3/$5/Makefile"
}
git_retry() { git -c core.autocrlf=false "$@"; }
run_feed_index() { printf 'indexed\n' > "$BUILD_DIR/indexed"; }
source "$BASE_PATH/modules/managed_plugins.sh"
FEEDS_CONF=feeds.conf.default
DONOR=$1 REVIEWED=$2 REPO_URL=$3 COMMIT_HASH=$4
: > "$BUILD_DIR/$FEEDS_CONF"
install_custom_feed
'''
        for suffix in (".git", ".git///", "/"):
            with self.subTest(alias=suffix):
                result = self.shell(script, donor.as_uri(), reviewed,
                                    "https://github.com/padavanonly/immortalwrt-mt798x-6.6" + suffix,
                                    "ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                package = self.build / "feeds/custom_feed/luci-app-netcontrol"
                self.assertTrue((package / "Makefile").is_file(),
                                "selected S20M Netcontrol recipe is absent before feed indexing")
                self.assertEqual((package / "Makefile").read_bytes(),
                                 (NETCONTROL_FIXTURE / "luci-app-netcontrol/Makefile").read_bytes())
                self.assertTrue((self.build / "indexed").exists())
                if suffix == ".git":
                    from test_netcontrol_compat import run_firstboot
                    runtime = self.build / "installed-firstboot"
                    boot = run_firstboot((package / "root/etc/uci-defaults/luci-netcontrol").read_text(), runtime)
                    self.assertEqual(boot.returncode, 0, boot.stdout + boot.stderr)
                    self.assertFalse(any(line.startswith("timecontrol ")
                                         for line in (runtime / "events").read_text().splitlines()),
                                     "the actual custom feed path published the unsafe raw initializer")
        result = self.shell(script, donor.as_uri(), reviewed,
                            "https://github.com/VIKINGYFY/immortalwrt.git",
                            "3fd1e27a511851b41cf082b067b60099e8e026c4")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.build / "feeds/custom_feed/luci-app-netcontrol").exists())
        (self.build / "indexed").unlink()
        result = self.shell(script, donor.as_uri(), "0" * 40,
                            "https://github.com/padavanonly/immortalwrt-mt798x-6.6.git",
                            "ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.build / "indexed").exists(), "a missing pin reached feed indexing")
        self.assertFalse((self.build / "custom_feed/luci-app-netcontrol").exists())

    def test_direct_iptables_dependency_is_gated_for_new_kernels_and_repeat_is_stable(self):
        include = self.build / "include/netfilter.mk"
        include.parent.mkdir()
        include.write_text("\n".join((
            "CONFIG_IP_NF_IPTABLES_LEGACY, $(P_V4)ip_tables, ge 6.12",
            "CONFIG_IP6_NF_IPTABLES_LEGACY, $(P_V6)ip6_tables, ge 6.12",
            "CONFIG_IP_NF_IPTABLES_LEGACY, xt_standard ipt_icmp xt_tcp xt_udp xt_comment xt_set xt_SET, ge 6.12",
            "CONFIG_IP6_NF_IPTABLES_LEGACY, ip6t_icmp6, ge 6.12",
        )) + "\n")
        recipe = self.build / "package/kernel/linux/modules/netfilter.mk"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("define KernelPackage/ipt-nat\n  DEPENDS:=+kmod-iptables +kmod-nf-nat\nendef\n")
        script = 'source "$BASE_PATH/modules/service_fixes.sh"; fix_netfilter_kmod_clash'
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DEPENDS:=+(!(LINUX_6_12||LINUX_6_18)):kmod-iptables +kmod-nf-nat", recipe.read_text())
        before = recipe.read_bytes()
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, recipe.read_bytes())

    def test_airoha_root_recipe_is_unique_and_uses_the_installed_luci_feed(self):
        package = self.build / "luci-app-airoha-npu"
        nested = package / "luci-app-airoha-npu"
        nested.mkdir(parents=True)
        (package / "Makefile").write_text("LUCI_TITLE:=Airoha NPU\ninclude ../../luci.mk\n")
        (nested / "Makefile").write_text("LUCI_TITLE:=Duplicate Airoha NPU\ninclude ../../luci.mk\n")
        script = ('source "$BASE_PATH/modules/custom_feed.sh"; '
                  'remove_nested_airoha_npu_package "$1" && fix_airoha_npu_luci_mk "$1"')
        result = self.shell(script, package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.relative_to(package).as_posix() for p in package.rglob("Makefile")], ["Makefile"])
        self.assertEqual((package / "Makefile").read_text(),
                         "LUCI_TITLE:=Airoha NPU\ninclude $(TOPDIR)/feeds/luci/luci.mk\n")
        before = (package / "Makefile").read_bytes()
        result = self.shell(script, package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, (package / "Makefile").read_bytes())

    def test_pinned_root_package_fetch_uses_reviewed_commit_after_remote_advances(self):
        writer = self.build / "writer"
        writer.mkdir()
        def git(*arguments):
            return subprocess.run(["git", "-C", str(writer), *arguments], capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Source fixture")
        git("config", "user.email", "source-fixture@example.invalid")
        (writer / "Makefile").write_text("LUCI_TITLE:=Reviewed package\n")
        git("add", ".")
        git("commit", "-qm", "reviewed")
        reviewed = git("rev-parse", "HEAD")
        (writer / "Makefile").write_text("LUCI_TITLE:=Unreviewed newer package\n")
        git("commit", "-qam", "newer")
        target = self.build / "custom_feed"
        target.mkdir()
        script = ('source "$BASE_PATH/modules/custom_feed.sh"; git_retry() { git "$@"; }; '
                  'sync_repo_root_package_to_feed_dir "$1" main "$2" fixture luci-app-airoha-npu "$3"')
        result = self.shell(script, writer.as_uri(), target, reviewed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((target / "luci-app-airoha-npu/Makefile").read_text(), "LUCI_TITLE:=Reviewed package\n")
        self.assertFalse((target / "luci-app-airoha-npu/.git").exists())

    def test_local_feed_registration_creates_link_before_index_only_update(self):
        custom = self.build / 'custom_feed'
        custom.mkdir()
        conf = self.build / 'feeds.conf.default'
        conf.write_text('')
        script = ('source "$BASE_PATH/modules/custom_feed.sh"; '
                  'register_local_feed_source "$1" "$2"')
        result = self.shell(script, custom, conf)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        link = self.build / 'feeds/custom_feed'
        self.assertTrue(link.is_symlink(), 'index-only updates do not create src-link checkouts')
        self.assertEqual(link.resolve(), custom.resolve())
        result = self.shell(script, custom, conf)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(conf.read_text().count('src-link custom_feed '), 1)


if __name__ == "__main__":
    unittest.main()
