#!/usr/bin/env python3
"""Exercise SmartDNS init script sections against controlled UCI state."""
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from shell_test_helpers import bash_executable

ROOT = Path(__file__).resolve().parents[1]
INIT = Path("package/openwrt/files/etc/init.d/smartdns")
ORIGINAL = ROOT / "tests/fixtures/smartdns-runtime/136c0c2" / INIT
PATCH = ROOT / "wrt_core/patches/102-smartdns-dhcp-option.patch"


class SmartdnsInit(unittest.TestCase):
    def test_service_setup_does_not_duplicate_the_dns_option(self):
        data = ORIGINAL.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "74c6a3c0c1866558dd1007c102515edf6ef44da7c0db6640f17a988fc17a7f75")
        with tempfile.TemporaryDirectory(prefix="smartdns-dhcp-") as temporary:
            work = Path(temporary)
            source = work / INIT
            source.parent.mkdir(parents=True)
            source.write_bytes(data)
            if PATCH.exists():
                subprocess.run(["git", "apply", str(PATCH)], cwd=work, check=True)
            function = re.search(r"^set_main_dns\(\)\n\{.*?^\}", source.read_text(),
                                 re.MULTILINE | re.DOTALL)
            self.assertIsNotNone(function)
            # Keep the actual setup function and isolate UCI and service reloads.
            setup = function.group().replace("/etc/init.d/dnsmasq reload", "reload_dnsmasq")
            script = r'''
reload_dnsmasq() { :; }
uci() {
    case "$*" in
        '-q get network.lan.ipaddr') echo '10.0.0.1/24' ;;
        '-q get dhcp.@dnsmasq[0].port') cat port ;;
        '-q get dhcp.lan.dhcp_option') paste -s -d ' ' options ;;
        '-q get dhcp.@dnsmasq[0].dns_redirect') echo 0 ;;
        'commit dhcp') : ;;
        'batch -q -')
            while read -r op value; do
                case "$op:$value" in
                    'set:dhcp.@dnsmasq[0].port=0') echo 0 > port ;;
                    'add_list:dhcp.lan.dhcp_option="6,10.0.0.1"') echo '6,10.0.0.1' >> options ;;
                    :) ;;
                    *) echo "Unexpected UCI command: $op $value" >&2; return 2 ;;
                esac
            done ;;
        *) return 2 ;;
    esac
}
'''
            script += setup + r'''

# Restore the ordinary dnsmasq port between calls, as a service reconfigure can.
echo 53 > port
set_main_dns
echo 53 > port
set_main_dns
cat options
'''
            (work / "options").write_text("6,10.0.0.10\n3,10.0.0.254\n", newline="\n")
            result = subprocess.run([bash_executable(), "-c", script], cwd=work,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                "6,10.0.0.10", "3,10.0.0.254", "6,10.0.0.1",
            ])
            self.assertEqual((work / "port").read_text().strip(), "0")

    def test_expired_cache_checkbox_emits_explicit_policy_and_retains_unset_default(self):
        with tempfile.TemporaryDirectory(prefix="smartdns-cache-config-") as temporary:
            work = Path(temporary)
            source = work / INIT
            source.parent.mkdir(parents=True)
            source.write_bytes(ORIGINAL.read_bytes())
            patch = ROOT / "wrt_core/patches/104-smartdns-expired-cache-config.patch"
            if patch.exists():
                subprocess.run(["git", "apply", str(patch)], cwd=work, check=True)
            code = re.search(r"^\tconfig_get serve_expired .*?\n(?=\n\tconfig_get cache_size )",
                             source.read_text(), re.MULTILINE | re.DOTALL)
            self.assertIsNotNone(code)
            boundary = r'''
config_get() {
    [ "$2" = config ] && [ "$3" = serve_expired ] || exit 2
    printf -v "$1" '%s' "${CONFIG_VALUE:-${4:-}}"
}
conf_append() { printf '%s %s\n' "$1" "$2"; }
section=config
'''
            for value, expected in (("0", "serve-expired no"), ("1", "serve-expired yes"),
                                    ("", ""), ("unknown", "")):
                with self.subTest(setting=value):
                    result = subprocess.run(
                        [bash_executable(), "-c", 'CONFIG_VALUE=$1\n' + boundary + code.group() + '\n:',
                         "smartdns-uci", value], text=True, capture_output=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
