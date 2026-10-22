#!/usr/bin/env python3
"""Run imported SSR initialization in a private filesystem; never access a router.

All ordered patches are applied to blob-checked upstream fixtures. Only fixed
system paths and unavailable UCI/service OS boundaries are substituted. Linux
executes real /bin/sh and flock; Windows uses Git sh and optional native flock.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ssrplus/2abdc9aa"
SHELL = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("sh")


@unittest.skipUnless(SHELL, "a POSIX shell is required")
class FirstbootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = tempfile.TemporaryDirectory(prefix="ssrp-firstboot-source-")
        cls.addClassCleanup(cls.prepared.cleanup)
        package = Path(cls.prepared.name)
        for row in (ROOT / "wrt_core/compat/ssrplus/source-files.tsv").read_text().splitlines():
            blob, target, fixture = row.split()
            data = (ROOT / "tests/fixtures" / fixture).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != blob:
                raise AssertionError("upstream fixture changed: " + fixture)
            path = package / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in (ROOT / "wrt_core/compat/ssrplus/patches.list").read_text().splitlines():
            if os.environ.get("SSRP_FIRSTBOOT_UNPATCHED") and name == "ssrplus-firstboot.patch":
                continue
            result = subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(package),
                                     "apply", str(ROOT / "wrt_core/patches" / name)],
                                    capture_output=True, text=True, timeout=20)
            if result.returncode:
                raise AssertionError(name + ": " + result.stderr)
        cls.init_code = (package / "root/etc/init.d/shadowsocksr").read_text(encoding="utf-8")
        cls.defaults_code = (package / "root/etc/uci-defaults/luci-ssr-plus").read_text(encoding="utf-8")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssrp-firstboot-run-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.environment = os.environ.copy()
        self.environment["MSYS_NO_PATHCONV"] = "1"
        self.environment["TEST_ROOT"] = self.base.as_posix()
        if os.name == "nt":
            self.environment["TEST_ROOT"] = subprocess.check_output(
                [SHELL, "--noprofile", "--norc", "-c", 'cygpath -u "$1"', "path", str(self.base)],
                env=self.environment, text=True).strip()
            flock_dir = os.environ.get("SSRP_TEST_FLOCK_DIR", str(Path(tempfile.gettempdir()) /
                "codex-ssr-msys-flock-probe/usr/bin"))
            self.environment["PATH"] = flock_dir + os.pathsep + self.environment["PATH"]
        self.config = self.base / "fs/etc/config/shadowsocksr"
        self.template = self.base / "fs/usr/share/shadowsocksr/shadowsocksr.config"
        for directory in ("fs/etc/config", "fs/etc/ssrplus", "bin"):
            (self.base / directory).mkdir(parents=True)
        self.write("init.sh", self.relocate(self.init_code))
        self.write("defaults.sh", self.relocate(self.defaults_code), executable=True)
        self.write("fs/usr/share/shadowsocksr/ssrp-runtime.sh", self.relocate(
            (ROOT / "wrt_core/compat/ssrplus/runtime.sh").read_text(encoding="utf-8")))
        self.template.write_bytes((FIXTURE / "shadowsocksr.config").read_bytes())
        # Load the real init once per invocation; only its rc.common dispatch
        # entry point is represented by this shim. The hook calls it externally.
        self.write("fs/etc/init.d/shadowsocksr", '''#!/bin/sh
. "$TEST_ROOT/init.sh" || exit
. "$TEST_ROOT/boundary.sh" || exit
printf 'entry:%s\\n' "$*" >> "$TEST_ROOT/entries"
"$@"
''', executable=True)
        self.write("boundary.sh", r'''
PATH="$TEST_ROOT/bin:$PATH"
export PATH
forbidden() { printf '%s\n' "$*" >> "$TEST_ROOT/forbidden"; return 87; }
ssrp_stop() { forbidden stop; }
ssrp_start() { forbidden start; }
ssrp_dnsmasq() { forbidden dnsmasq; }
service_start() { forbidden core; }
nft() { forbidden nft; }; iptables() { forbidden iptables; }
ip() { forbidden ip; }; killall() { forbidden killall; }
curl() { forbidden curl; }; ssh() { forbidden ssh; }
''')
        # UCI itself is an OS dependency unavailable on the test host. This
        # boundary checks section-bearing syntax and records migration calls.
        # Named package lookup models UCI's runtime overrides/saved deltas;
        # absolute lookup reads the exact candidate and bypasses those paths.
        # It does not implement installation, locking, or failure handling.
        self.write("bin/uci", r'''#!/bin/sh
printf '%s\n' "$*" >> "$TEST_ROOT/uci-calls"
directory=
while [ "$#" -gt 0 ]; do
    case "$1" in
        -q) shift ;;
        -c) directory=$2; shift 2 ;;
        *) break ;;
    esac
done
case "$1" in
    batch) cat >> "$TEST_ROOT/uci-batch"; exit 0 ;;
    get)
        [ "${FAIL_UCI:-0}" != 1 ] || exit 1
        case "$2" in
            /*)
                candidate=${2%'.@global[0]'}
                [ "$candidate" != "$2" ] || exit 1
                relative=${candidate#"$TEST_ROOT/fs/etc/config/"}
                [ "$relative" != "$candidate" ] || exit 1
                # UCI splits tuples at dots. Check the production stage path
                # after removing the relocated host prefix, which may have dots.
                case "$relative" in ssrplus-init-*/shadowsocksr) :;; *) exit 1;; esac
                stage_name=${relative%/shadowsocksr}
                case "$stage_name" in *.*|*/*) exit 1;; esac
                printf '%s\n' "$candidate" >> "$TEST_ROOT/uci-validation-files"
                ;;
            'shadowsocksr.@global[0]')
                [ -n "$directory" ] || exit 1
                candidate="$directory/shadowsocksr"
                if [ -f "$TEST_ROOT/fs/var/run/uci/shadowsocksr" ]; then
                    candidate="$TEST_ROOT/fs/var/run/uci/shadowsocksr"
                fi
                # A saved delta can add a global section to a named package.
                if [ -s "$TEST_ROOT/fs/tmp/.uci/shadowsocksr" ]; then
                    printf 'global\n'; exit 0
                fi
                ;;
            *) exit 1 ;;
        esac
        awk '
            /^[ \t]*($|#)/ { next }
            $1 == "config" && NF >= 2 && NF <= 3 { if ($2 == "global") global=1; next }
            ($1 == "option" || $1 == "list") && NF >= 3 { next }
            { bad=1 }
            END { exit !(global && !bad) }
        ' "$candidate" || exit 1
        printf 'global\n' ;;
    *) exit 0 ;;
esac
''', executable=True)

    def write(self, relative, text, executable=False):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        if executable:
            path.chmod(0o755)
        return path

    def relocate(self, code):
        # One pass prevents replacing a /tmp inside an inserted host path.
        code = code.replace('${IPKG_INSTROOT:-}', '').replace('$IPKG_INSTROOT', '')
        return re.sub(r'/(?:etc|usr|var|tmp|proc|lib)/', lambda m: '$TEST_ROOT/fs' + m.group(), code)

    def shell(self, body, check=True):
        command = [SHELL]
        if os.name == "nt":
            command += ["--noprofile", "--norc"]
        result = subprocess.run(command + ["-c", '''
. "$TEST_ROOT/init.sh" || exit
. "$TEST_ROOT/boundary.sh" || exit
''' + body], env=self.environment, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def initialize(self, body="", check=True):
        return self.shell(body + "\ninitialize\n", check=check)

    def assert_clean(self):
        self.assertFalse((self.base / "forbidden").exists(), "initialization entered service lifecycle")
        self.assertFalse((self.base / "fs/var/etc").exists(), "initialization created runtime directory")
        self.assertEqual(list(self.config.parent.glob(".ssrplus-init.*")), [], "staging files leaked")
        self.assertEqual(list(self.config.parent.glob("ssrplus-init-*")), [], "staging files leaked")

    def entries(self):
        path = self.base / "entries"
        self.assertTrue(path.exists(), "defaults hook never invoked the initialization entry point")
        return path.read_text().splitlines()

    def assert_factory(self):
        self.assertEqual(self.config.read_bytes(), self.template.read_bytes())
        sections = re.findall(r"^config (\w+)", self.config.read_text(encoding="utf-8"), re.M)
        self.assertEqual(sections, ["global", "server_subscribe", "access_control", "socks5_proxy",
                                    "server_global", "global_xray_fragment"])
        self.shell('test "$(stat -c %a "$TEST_ROOT/fs/etc/config/shadowsocksr")" = 644')
        self.assert_clean()

    def test_initialize_is_an_exported_rc_common_command(self):
        self.shell('case " $EXTRA_COMMANDS " in *" initialize "*) :;; *) exit 70;; esac')

    def test_missing_config_initializes_factory_and_all_ui_sections(self):
        self.initialize()
        self.assert_factory()

    def test_empty_config_initializes_without_runtime_directories(self):
        # Create through the shell: on this Windows host a Python-created empty
        # file is incorrectly reported as size4096 by MSYS stat/[ -s ]. Merely
        # truncating it does not repair that metadata; a shell-created file does.
        self.shell('touch "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                   'test ! -s "$TEST_ROOT/fs/etc/config/shadowsocksr"')
        self.initialize()
        self.assert_factory()

    def test_nonempty_even_malformed_config_skips_missing_or_invalid_template(self):
        for existing in (b"config global\n option global_server 'my-node'\n", b"malformed user data\n"):
            for template in (None, b"invalid template\n"):
                with self.subTest(existing=existing, template=template):
                    self.config.write_bytes(existing)
                    before = self.config.stat()
                    if template is None:
                        self.template.unlink(missing_ok=True)
                    else:
                        self.template.write_bytes(template)
                    self.initialize()
                    self.assertEqual(self.config.read_bytes(), existing)
                    self.assertEqual(self.config.stat().st_mtime_ns, before.st_mtime_ns)
                    self.assertFalse((self.base / "uci-calls").exists(), "existing config should skip validation")
                    self.assert_clean()

    def test_repeated_initialization_preserves_user_changes_and_inode(self):
        self.initialize()
        self.config.write_bytes(b"config global\n option global_server 'mine'\n")
        before = self.config.stat()
        self.template.unlink()
        self.initialize()
        self.assertEqual(self.config.stat().st_ino, before.st_ino)
        self.assertEqual(self.config.read_bytes(), b"config global\n option global_server 'mine'\n")
        self.assert_clean()

    def test_concurrent_initialization_serializes_and_copies_once(self):
        result = self.shell('command -v flock', check=False)
        if result.returncode and os.name == "nt":
            self.skipTest("native flock unavailable on Windows; required on Linux")
        self.assertEqual(result.returncode, 0, "Linux CI must provide real flock")
        self.shell(r'''
cp() { echo copy >> "$TEST_ROOT/copies"; command sleep .1; command cp "$@"; }
initialize & first=$!
initialize & second=$!
wait "$first" || exit
wait "$second" || exit
test "$(wc -l < "$TEST_ROOT/copies")" = 1
''')
        self.assert_factory()

    def test_missing_empty_invalid_and_no_global_templates_fail_without_publishing(self):
        for data in (None, b"", b"INVALID UCI\n", b"config server_subscribe\n"):
            with self.subTest(data=data):
                if data is None:
                    self.template.unlink()
                else:
                    self.template.write_bytes(data)
                result = self.initialize(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.config.exists())
                self.assert_clean()

    def test_validation_reads_absolute_dot_free_staged_package(self):
        self.initialize()
        calls = self.base / "uci-validation-files"
        self.assertTrue(calls.exists(), "UCI validation used a named package instead of the staged file")
        candidates = calls.read_text().splitlines()
        self.assertEqual(len(candidates), 1)
        prefix = self.environment["TEST_ROOT"] + "/fs/etc/config/"
        self.assertTrue(candidates[0].startswith(prefix))
        self.assertRegex(candidates[0][len(prefix):], r"^ssrplus-init-[A-Za-z0-9]+/shadowsocksr$")
        self.assert_factory()

    def test_valid_template_ignores_invalid_runtime_override(self):
        self.write("fs/var/run/uci/shadowsocksr", "INVALID runtime override\n")
        self.initialize()
        self.assert_factory()

    def test_runtime_override_cannot_supply_missing_template_global(self):
        self.template.write_bytes(b"config server_subscribe\n")
        self.write("fs/var/run/uci/shadowsocksr", "config global\n")
        result = self.initialize(check=False)
        self.assertNotEqual(result.returncode, 0, "runtime override masked an invalid factory template")
        self.assertFalse(self.config.exists())
        self.assert_clean()

    def test_saved_delta_cannot_supply_missing_template_global(self):
        self.template.write_bytes(b"config server_subscribe\n")
        self.write("fs/tmp/.uci/shadowsocksr", "shadowsocksr.stale='global'\n")
        result = self.initialize(check=False)
        self.assertNotEqual(result.returncode, 0, "saved delta masked an invalid factory template")
        self.assertFalse(self.config.exists())
        self.assert_clean()

    def test_copy_chmod_uci_and_rename_failures_preserve_empty_destination(self):
        for command in ("cp", "chmod", "mv", "mktemp", "mkdir", "uci"):
            with self.subTest(command=command):
                self.shell('rm -f "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                           'touch "$TEST_ROOT/fs/etc/config/shadowsocksr"; '
                           'test ! -s "$TEST_ROOT/fs/etc/config/shadowsocksr"')
                before = self.config.stat()
                # mkdir is used by the existing lock owner too; direct function
                # isolates the installation's own checked mkdir boundary.
                body = f'{command}() {{ return 73; }}\n'
                result = self.shell(body + "ssrp_initialize_config\n", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.config.read_bytes(), b"")
                self.assertEqual(self.config.stat().st_ino, before.st_ino)
                self.assert_clean()

    def test_real_defaults_hook_initializes_before_migrations_and_never_resets(self):
        self.shell('"$TEST_ROOT/defaults.sh"')
        self.assert_factory()
        self.assertEqual(self.entries(), ["entry:initialize"])
        calls = (self.base / "uci-calls").read_text()
        self.assertIn("/shadowsocksr.@global[0]", calls)
        self.assertIn("get shadowsocksr.@server_subscribe[0].auto_update_time", calls)
        self.assertIn("commit shadowsocksr", calls)

    def test_real_defaults_hook_failure_exits_before_migrations_and_later_sed(self):
        self.template.unlink()
        self.write("bin/sed", '#!/bin/sh\necho sed >> "$TEST_ROOT/later"\n', executable=True)
        result = self.shell('"$TEST_ROOT/defaults.sh"', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSR Plus: configuration initialization failed", result.stderr)
        self.assertEqual(self.entries(), ["entry:initialize"])
        calls = (self.base / "uci-calls").read_text()
        self.assertNotIn("get shadowsocksr.@server_subscribe", calls)
        self.assertFalse((self.base / "later").exists())
        self.assertEqual(self.config.read_bytes(), b"")
        self.assert_clean()

    def test_real_defaults_hook_preserves_existing_config_with_missing_template(self):
        existing = b"config global\n option global_server 'user-node'\nconfig servers 'user-node'\n"
        self.config.write_bytes(existing)
        self.template.unlink()
        self.shell('"$TEST_ROOT/defaults.sh"')
        self.assertEqual(self.config.read_bytes(), existing)
        self.assertEqual(self.entries(), ["entry:initialize"])
        self.assert_clean()

    def test_explicit_reset_keeps_stop_failure_protection(self):
        original = b"config global\n option global_server 'user-node'\n"
        self.config.write_bytes(original)
        result = self.shell("reset", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual((self.base / "forbidden").read_text().splitlines(), ["stop"])


if __name__ == "__main__":
    unittest.main()
