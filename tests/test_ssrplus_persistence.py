#!/usr/bin/env python3
"""Run the imported nft persistence function without contacting a router.

Only nft's OS boundary is replaced. The tests check the generated nft text,
error propagation and preservation of an existing firewall include file.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ssrplus-persistence/2abdc9aa/ssr-rules"
PATCH = ROOT / "wrt_core/patches/ssrplus-persistence.patch"
TABLE_INET = """table inet ss_spec {
	set ss_spec_wan_ac {
		type ipv4_addr
		flags interval
	}
	chain prerouting {
		type nat hook prerouting priority dstnat; policy accept;
	}
}
"""
TABLE_IP = """table ip ss_spec_mangle {
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
	}
}
"""


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssrplus-persistence-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bash = os.environ.get("BASH")
        if not self.bash:
            self.bash = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt"
                         else shutil.which("bash"))
        self.env = os.environ.copy()
        self.env["MSYS_NO_PATHCONV"] = "1"
        self.env["TEST_ROOT"] = self.base.as_posix()
        self.source = self.base / "root/usr/bin/ssr-rules"
        self.source.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, self.source)
        # A missing patch intentionally exercises the original fixture first:
        # the same assertions must expose the original defect before fixing it.
        if PATCH.exists() and not os.environ.get("SSR_PERSISTENCE_UNPATCHED"):
            self.shell('git -C "$1" apply "$2"', self.base.as_posix(), PATCH.as_posix())
        self.definitions = self.base / "persist-function.sh"
        code = self.source.read_text(encoding="utf-8")
        start = code.index("persist_nftables_rules() {")
        end = code.index("\n# Auto-update daemon", start)
        self.definitions.write_text(code[start:end], encoding="utf-8", newline="\n")
        (self.base / "inet.nft").write_text(TABLE_INET, encoding="utf-8", newline="\n")
        (self.base / "ip.nft").write_text(TABLE_IP, encoding="utf-8", newline="\n")
        self.output = self.base / "persist/ssrplus.nft"
        self.output.parent.mkdir()
        self.old = b"# previous complete rules\n" + TABLE_INET.encode()
        self.output.write_bytes(self.old)

    def shell(self, code, *args, check=True):
        result = subprocess.run(
            [self.bash, "--noprofile", "--norc", "-c", code, "test", *args],
            env=self.env, text=True, capture_output=True, timeout=60,
        )
        if check and result.returncode:
            self.fail(f"shell exited {result.returncode}: {result.stdout}\n{result.stderr}")
        return result

    def persist(self, configuration=""):
        return self.shell(r'''
            source "$1"
            USE_NFT=1
            FORCE_UPDATE=1
            NFT=fake_nft
            NFTABLES_RULES_DIR="$TEST_ROOT/persist"
            NFTABLES_RULES_FILE="$NFTABLES_RULES_DIR/ssrplus.nft"
            loger() { :; }
            compare_rules() { return 1; }
            fake_nft() {
                if [ "$*" = "list tables" ]; then
                    [ "${FAIL_LIST:-0}" = 0 ] || return 1
                    [ "${NO_TABLES:-0}" = 0 ] || return 0
                    printf 'table inet ss_spec\ntable ip ss_spec_mangle\n'
                elif [ "$*" = "list table inet ss_spec" ]; then
                    [ "${NO_TABLES:-0}" = 0 ] || return 1
                    cat "$TEST_ROOT/inet.nft"
                elif [ "$*" = "list table ip ss_spec_mangle" ]; then
                    [ "${NO_TABLES:-0}" = 0 ] || return 1
                    [ "${FAIL_EXPORT:-0}" = 0 ] || { printf 'table ip ss_spec_mangle {'; return 1; }
                    cat "$TEST_ROOT/ip.nft"
                else
                    return 1
                fi
            }
        ''' + configuration + '\npersist_nftables_rules\n',
                          self.definitions.as_posix(), check=False)

    def assert_body(self):
        content = self.output.read_text(encoding="utf-8")
        body = "\n".join(line for line in content.splitlines()
                         if line.strip() and not line.lstrip().startswith("#")) + "\n"
        self.assertEqual(body, TABLE_INET + TABLE_IP,
                         "metadata escaped its comment or exported nft tables changed")
        # Both complete table declarations and every nested block must survive.
        self.assertEqual(body.count("{"), body.count("}"))
        self.assertEqual(re.findall(r"^table (\w+) (\w+) \{$", body, re.M),
                         [("inet", "ss_spec"), ("ip", "ss_spec_mangle")])

    def assert_no_temporary_files(self):
        self.assertEqual([p.name for p in self.output.parent.iterdir()], [self.output.name],
                         "failed persistence leaked a temporary configuration")

    def test_multiline_wan_bypass_preserves_valid_nft_text(self):
        result = self.persist("WAN_BP_IP=$'10.0.0.0/8\\n172.16.0.0/12\\n192.168.0.0/16'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_body()
        content = self.output.read_text(encoding="utf-8")
        self.assertIn("# WAN_BP_IP: 10.0.0.0/8\n# 172.16.0.0/12\n# 192.168.0.0/16\n", content)
        self.assert_no_temporary_files()

    def test_all_metadata_cannot_escape_comments_with_cr_or_lf(self):
        values = ("RUNMODE", "server", "local_port", "WAN_BP_IP", "LAN_AC_IP",
                  "LAN_BP_IP", "WAN_FW_IP", "LAN_FP_IP", "LAN_GM_IP")
        config = "\n".join(f"{name}=$'first\\nflush ruleset\\rlast\\\\literal'" for name in values)
        result = self.persist(config)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_body()
        content = self.output.read_text(encoding="utf-8")
        self.assertEqual(content.count("# flush ruleset\n"), len(values))

    def test_export_failure_preserves_previous_file(self):
        result = self.persist("FAIL_EXPORT=1")
        self.assertNotEqual(result.returncode, 0, "partial nft export was reported as success")
        self.assertEqual(self.output.read_bytes(), self.old,
                         "failed nft export replaced the last complete persistence file")
        self.assert_no_temporary_files()

    def test_no_tables_preserves_previous_file(self):
        result = self.persist("NO_TABLES=1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.output.exists(), "no-table export deleted the previous file")
        self.assertEqual(self.output.read_bytes(), self.old)
        self.assert_no_temporary_files()

    def test_table_list_failure_preserves_previous_file(self):
        result = self.persist("FAIL_LIST=1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output.read_bytes(), self.old)
        self.assert_no_temporary_files()

    def test_replacement_is_atomic_and_write_failure_preserves_previous_file(self):
        result = self.persist(r'''
            mv() {
                cmp -s "$NFTABLES_RULES_FILE" "$TEST_ROOT/expected-old" || return 31
                [ -s "$2" ] || return 32
                return 1
            }
            cp "$NFTABLES_RULES_FILE" "$TEST_ROOT/expected-old"
        ''')
        self.assertNotEqual(result.returncode, 0, "failed final rename was reported as success")
        self.assertEqual(self.output.read_bytes(), self.old,
                         "the previous file changed before the final rename")
        self.assert_no_temporary_files()

    def test_unchanged_rules_skip_export_and_preserve_file(self):
        result = self.persist(r'''
            FORCE_UPDATE=0
            compare_rules() { return 0; }
            fake_nft() { return 93; }
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), self.old)
        self.assert_no_temporary_files()

    def run_cli(self, *arguments):
        """Execute the full real script, replacing only system operations."""
        init = self.base / "etc/init.d/shadowsocksr"
        init.parent.mkdir(parents=True)
        init.write_text(r'''
check_run_environment() { USE_TABLES=nftables; }
echolog() { :; }
uci() { :; }
logger() { :; }
nft() {
    case "$*" in
        'list tables') printf 'table inet ss_spec\ntable ip ss_spec_mangle\n' ;;
        'list table inet ss_spec') cat "$TEST_ROOT/inet.nft" ;;
        'list table ip ss_spec_mangle') printf 'table ip ss_spec_mangle {'; return 1 ;;
        *) return 1 ;;
    esac
}
''', encoding="utf-8", newline="\n")
        code = self.source.read_text(encoding="utf-8")
        code = code.replace('NFTABLES_RULES_DIR="/usr/share/nftables.d/ruleset-post"',
                            'NFTABLES_RULES_DIR="$TEST_ROOT/persist"')
        code = code.replace('NFTABLES_RULES_FILE="$NFTABLES_RULES_DIR/99-shadowsocksr.nft"',
                            'NFTABLES_RULES_FILE="$NFTABLES_RULES_DIR/ssrplus.nft"')
        code = code.replace('/tmp/', self.base.as_posix() + '/state/')
        code = code.replace('/etc/ssrplus/', self.base.as_posix() + '/etc/ssrplus/')
        # Keep CLI parsing and the entire control flow unchanged. These
        # functions perform kernel changes outside persistence's contract.
        operations = r'''
flush_r() { :; }
ipset_r() { :; }
fw_rule() { :; }
ac_rule() { :; }
tp_rule() { :; }
gen_include() { :; }
'''
        code = code.replace('# Main process\n', operations + '\n# Main process\n', 1)
        command = self.base / "cli-test.sh"
        command.write_text(code, encoding="utf-8", newline="\n")
        (self.base / "state").mkdir()
        return self.shell('IPKG_INSTROOT="$TEST_ROOT" bash "$@"',
                          command.as_posix(), *arguments, check=False)

    def test_real_force_update_cli_preserves_previous_file_on_export_failure(self):
        result = self.run_cli("-P")
        self.assertNotEqual(result.returncode, 0, "-P reported a partial export as success")
        self.assertTrue(self.output.exists(), "-P deleted the previous file before export")
        self.assertEqual(self.output.read_bytes(), self.old)
        self.assert_no_temporary_files()

    def test_changed_ip_list_preserves_previous_file_on_export_failure(self):
        result = self.run_cli("-s", "198.51.100.1", "-l", "1234", "-b", "10.0.0.0/8 172.16.0.0/12")
        self.assertTrue(self.output.exists(), "IP list change deleted the previous file before export")
        self.assertEqual(self.output.read_bytes(), self.old)
        self.assertNotEqual(result.returncode, 0, "failed persistence in the rebuild path was ignored")
        self.assert_no_temporary_files()

    def test_changed_mode_preserves_previous_file_on_export_failure(self):
        result = self.run_cli("-s", "198.51.100.1", "-l", "1234", "-g")
        self.assertTrue(self.output.exists(), "mode change deleted the previous file before export")
        self.assertEqual(self.output.read_bytes(), self.old)
        self.assertNotEqual(result.returncode, 0, "failed persistence in the mode change path was ignored")
        self.assert_no_temporary_files()

    def test_patch_is_reversible_and_detected_on_second_application(self):
        if not PATCH.exists() or os.environ.get("SSR_PERSISTENCE_UNPATCHED"):
            self.skipTest("unpatched baseline run")
        self.shell('git -C "$1" apply --reverse --check "$2"',
                   self.base.as_posix(), PATCH.as_posix())
        result = self.shell('git -C "$1" apply --check "$2"',
                            self.base.as_posix(), PATCH.as_posix(), check=False)
        self.assertNotEqual(result.returncode, 0,
                            "already-applied patch was not detected")
        self.shell('bash -n "$1"', self.source.as_posix())


if __name__ == "__main__":
    unittest.main()
