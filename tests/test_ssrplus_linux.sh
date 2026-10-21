#!/usr/bin/env bash
# Real parser acceptance. Invoke only inside a fresh Linux network namespace:
# sudo unshare -n bash tests/test_ssrplus_linux.sh
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
fail() { echo "FAIL: $*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || fail "Linux is required for kernel nft validation"
[[ $EUID == 0 ]] || fail "run with sudo unshare -n for isolated nft validation"
[[ $(readlink /proc/self/ns/net) != "$(readlink /proc/1/ns/net)" ]] ||
    fail "refusing to run nft outside a separate network namespace"

for program in nft dnsmasq python3 git bash flock ip; do
    command -v "$program" >/dev/null || fail "required executable missing: $program"
done
nft_bin=$(command -v nft)
dnsmasq_bin=$(command -v dnsmasq)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT

# Reuse the real persistence function and source fixtures from the regression
# suite. Only nft export is simulated here; acceptance uses the real parser.
python3 - "$test_root" <<'PY'
import importlib.util
import os
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "ssrplus_persistence_tests", "tests/test_ssrplus_persistence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for patched, filename in ((False, "original.nft"), (True, "patched.nft")):
    if patched:
        os.environ.pop("SSR_PERSISTENCE_UNPATCHED", None)
    else:
        os.environ["SSR_PERSISTENCE_UNPATCHED"] = "1"
    case = module.PersistenceTests("test_multiline_wan_bypass_preserves_valid_nft_text")
    try:
        case.setUp()
        result = case.persist("WAN_BP_IP=$'10.0.0.0/8\\n172.16.0.0/12\\n192.168.0.0/16'")
        if result.returncode:
            raise RuntimeError(f"failed to generate {filename}: {result.stderr}")
        shutil.copyfile(case.output, destination / filename)
    finally:
        case.doCleanups()
os.environ.pop("SSR_PERSISTENCE_UNPATCHED", None)
PY

if "$nft_bin" -c -f "$test_root/original.nft" > "$test_root/original.log" 2>&1; then
    fail "original multiline metadata unexpectedly passed the nft parser"
fi
if ! grep -Eqi 'syntax error|unexpected' "$test_root/original.log"; then
    cat "$test_root/original.log" >&2
    fail "original nft rejection was not the expected syntax error"
fi
"$nft_bin" -c -f "$test_root/patched.nft"
echo "Real nft parser: original multiline metadata rejected; patched rules accepted: PASS"

# Exercise the whole patched ssr-rules CLI with real nft/ip/flock and real /proc.
# Only init configuration/paths are local to the harness. The namespace check at
# the top protects the host before any kernel firewall or route operation.
SSRP_NFT_BIN="$nft_bin" python3 - <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

spec = importlib.util.spec_from_file_location(
    "ssrplus_lifecycle_tests", "tests/test_ssrplus_persistence_lifecycle.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
case = module.LifecycleTests()
case.setUp()
processes = []
nft_bin = os.environ["SSRP_NFT_BIN"]

def nft(*args):
    return subprocess.run([nft_bin, *args], text=True, capture_output=True,
                          check=True).stdout

def cli(*args, env=None, background=False):
    runtime_env = case.env.copy()
    runtime_env.update(IPKG_INSTROOT=case.base.as_posix(), SSRP_NFT_BIN=nft_bin)
    if env:
        runtime_env.update(env)
    command = [case.bash, str(case.command), *args]
    if background:
        child = subprocess.Popen(command, env=runtime_env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        processes.append(child)
        return child
    return subprocess.run(command, env=runtime_env, text=True,
                          capture_output=True, timeout=20)

try:
    # Preserve the real process interface in the CLI; the unit suite uses a
    # controlled /proc tree for stale/reused PID scenarios.
    code = case.command.read_text().replace(
        'SSRP_PROC_ROOT="$TEST_ROOT/proc"', 'SSRP_PROC_ROOT="/proc"')
    case.command.write_text(code, encoding="utf-8", newline="\n")
    init = case.base / "etc/init.d/shadowsocksr"
    init.write_text(r'''
check_run_environment() { USE_TABLES=nftables; }
echolog() { :; }
uci() { printf '%s/include.sh\n' "$TEST_ROOT"; }
logger() { :; }
nft() {
    if [ "${SSRP_PAUSE_EXPORT:-0}" = "1" ] && [ "$*" = "list tables" ]; then
        : > "$TEST_ROOT/export-entered"
        while [ ! -f "$TEST_ROOT/release-export" ]; do sleep 0.02; done
    fi
    "$SSRP_NFT_BIN" "$@"
}
''', encoding="utf-8", newline="\n")

    # A basic fw4-style NAT table must survive every SSR operation byte-for-byte.
    seed = case.base / "kernel-seed.nft"
    seed.write_text('''table inet fw4 {
    chain srcnat { type nat hook postrouting priority srcnat; policy accept; }
}
''' + module.INET + module.MANGLE, encoding="utf-8", newline="\n")
    nft("-f", str(seed))
    base_nat = json.loads(nft("-j", "list", "table", "inet", "fw4"))
    result = cli("-P")
    assert result.returncode == 0, result.stderr
    assert not (case.legacy / "99-shadowsocksr.nft").exists()
    assert "192.0.2.1" in case.snapshot.read_text()
    for _ in range(3):
        result = cli("-R")
        assert result.returncode == 0, result.stderr
        assert "192.0.2.1" in nft("list", "set", "inet", "ss_spec", "whitelist")
        assert "redirect to :1234" in nft("list", "chain", "inet", "ss_spec", "ss_spec_wan_fw")
        assert json.loads(nft("-j", "list", "table", "inet", "fw4")) == base_nat

    # A structurally SSR-only but syntactically broken file reaches the actual
    # nft dry run, and its failure must leave both SSR and basic NAT intact.
    live_ssr = json.loads(nft("-j", "list", "table", "inet", "ss_spec"))
    case.snapshot.write_text('table inet ss_spec {\n    definitely invalid syntax\n}\n',
                             encoding="utf-8", newline="\n")
    result = cli("-R")
    assert result.returncode != 0, "malformed snapshot unexpectedly restored"
    assert json.loads(nft("-j", "list", "table", "inet", "ss_spec")) == live_ssr
    assert json.loads(nft("-j", "list", "table", "inet", "fw4")) == base_nat
    case.active.touch()
    result = case.functions("gen_include_nft")
    assert result.returncode == 0, result.stderr
    runtime_env = case.env.copy()
    runtime_env.update(IPKG_INSTROOT=case.base.as_posix(), SSRP_NFT_BIN=nft_bin)
    hook = subprocess.run([case.bash, str(case.base / "include.sh")],
                          env=runtime_env, capture_output=True, timeout=20)
    assert hook.returncode == 0, "SSR hook blocked basic firewall installation"
    assert json.loads(nft("-j", "list", "table", "inet", "fw4")) == base_nat
    assert cli("-P").returncode == 0

    # While one real export owns FD 8, both -A and -K must wait on that same
    # persistent inode. Neither is permitted to race past the exporter.
    exporting = cli("-P", env={"SSRP_PAUSE_EXPORT": "1"}, background=True)
    deadline = time.monotonic() + 5
    while not (case.base / "export-entered").exists():
        assert exporting.poll() is None, "export exited before its test barrier"
        assert time.monotonic() < deadline, "export barrier was not reached"
        time.sleep(0.02)
    starting = cli("-A", background=True)
    stopping = cli("-K", background=True)
    time.sleep(0.15)
    assert starting.poll() is None and stopping.poll() is None, "daemon CLI bypassed export lock"
    assert not case.pidfile.exists(), "daemon started while an exporter held its lock"
    (case.base / "release-export").touch()
    for child in (exporting, starting, stopping):
        _, error = child.communicate(timeout=10)
        assert child.returncode == 0, error.decode()

    # A finite external ssr-rules call is different from its daemon. Kill the
    # lifecycle owner while the actual patched start_rules function is waiting
    # for a controlled external worker: that worker must retain FD9 until done.
    # Reintroducing 9>&- at the finite call boundary makes this assertion fail.
    finite_package = case.base / "finite-package"
    for row in Path("wrt_core/compat/ssrplus/source-files.tsv").read_text().splitlines():
        _, target, fixture = row.split()
        destination = finite_package / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path("tests/fixtures") / fixture, destination)
    subprocess.run(["git", "init", "-q", str(finite_package)], check=True)
    for patch in Path("wrt_core/compat/ssrplus/patches.list").read_text().splitlines():
        subprocess.run(["git", "-C", str(finite_package), "apply",
                        str(Path("wrt_core/patches", patch).resolve())], check=True)
    init_code = (finite_package / "root/etc/init.d/shadowsocksr").read_text(encoding="utf-8")
    begin = init_code.index("\nstart_rules() {\n") + 1
    end = init_code.index("\n}\n", begin) + 3
    finite_function = init_code[begin:end].replace(
        "/usr/bin/ssr-rules", '"$TEST_ROOT/finite-rules"').replace(
        "/usr/share/shadowsocksr/gfw2ipset.sh", ":")
    worker = case.base / "finite-rules"
    worker.write_text('''#!/bin/sh
printf '%s\\n' "$$" > "$TEST_ROOT/finite-child-pid"
: > "$TEST_ROOT/finite-entered"
while [ ! -f "$TEST_ROOT/release-finite" ]; do sleep 0.02; done
: > "$TEST_ROOT/finite-completed"
''', encoding="utf-8", newline="\n")
    worker.chmod(0o755)
    owner = case.base / "finite-owner.sh"
    owner.write_text('. "' + str(Path("wrt_core/compat/ssrplus/runtime.sh").resolve()) + '"\n' +
                     finite_function + r'''
get_host_ip() { printf '198.51.100.1\n'; }
uci_get_by_name() { case "$2" in local_port) printf '1234\n' ;; esac; }
uci_get_by_type() { case "$2" in run_mode) printf 'router\n' ;; esac; }
USE_TABLES=nftables
GLOBAL_SERVER=fixture
kcp_enable_flag=0
redir_udp=0
shunt=0
LOCK_FILE="$TEST_ROOT/var/lock/finite-lifecycle.lock"
ssrp_run_locked start_rules
''', encoding="utf-8", newline="\n")
    launcher = subprocess.Popen([case.bash, str(owner)], env=runtime_env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(launcher)
    finite_lock = case.base / "var/lock/finite-lifecycle.lock"
    try:
        deadline = time.monotonic() + 5
        while not (case.base / "finite-entered").exists():
            assert launcher.poll() is None, "finite start_rules exited before its external worker"
            assert time.monotonic() < deadline, "finite worker barrier was not reached"
            time.sleep(0.02)
        child_pid = (case.base / "finite-child-pid").read_text().strip()
        fields = Path("/proc", child_pid, "status").read_text().splitlines()
        owner_pid = int(next(line.split()[1] for line in fields if line.startswith("PPid:")))
        assert owner_pid > 1 and owner_pid != os.getpid()
        lock_inode = finite_lock.stat().st_ino
        os.kill(owner_pid, signal.SIGKILL)
        launcher.wait(timeout=5)
        blocked = subprocess.run(["flock", "-n", str(finite_lock), "true"])
        assert blocked.returncode != 0, "owner SIGKILL released FD9 while finite external child was still running"
        (case.base / "release-finite").touch()
        deadline = time.monotonic() + 5
        while subprocess.run(["flock", "-n", str(finite_lock), "true"]).returncode:
            assert time.monotonic() < deadline, "finite child did not release its inherited lifecycle lock"
            time.sleep(0.02)
        assert (case.base / "finite-completed").exists()
        assert finite_lock.stat().st_ino == lock_inode, "lifecycle lock inode was replaced"
    finally:
        (case.base / "release-finite").touch()

    # Prove the daemon owns neither the persistence FD nor the init lifecycle
    # FD. A parent starting it deliberately holds both before exec.
    lifecycle_lock = case.base / "var/lock/ssrplus.lock"
    started = subprocess.run([
        case.bash, "-c",
        'exec 9>"$1"; flock -x 9; exec "$2" -A', "test",
        str(lifecycle_lock), str(case.command)], env=runtime_env,
        text=True, capture_output=True, timeout=10)
    assert started.returncode == 0, started.stderr
    pid, starttime = case.pidfile.read_text().split()
    assert Path("/proc", pid, "cmdline").read_bytes().endswith(b"--persistence-daemon\0")
    for lock in (lifecycle_lock, case.base / "var/lock/ssr-rules-persistence.lock"):
        subprocess.run(["flock", "-n", str(lock), "true"], check=True, timeout=5)
    assert cli("-K").returncode == 0
    assert not case.pidfile.exists()
    print("Real SSR export/restore, malformed snapshot NAT isolation, daemon PID and locks: PASS")
finally:
    (case.base / "release-export").touch()
    for child in processes:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
    try:
        cli("-K")
    finally:
        case.doCleanups()
PY

# Run the actual DNS generator/publisher regression harness with the real
# dnsmasq parser. An audited PATH wrapper proves that the real-parser interface
# was exercised, rather than allowing an unrecognised env flag to pass silently.
mkdir "$test_root/bin"
cat > "$test_root/bin/dnsmasq" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
    *' --test '*|*' -t '*)
        printf '%s\n' "$*" >> "$SSRP_PARSER_LOG"
        ;;
    *' --version '*) ;;
    *) echo "Refusing non-parser dnsmasq invocation in tests: $*" >&2; exit 1 ;;
esac
exec "$SSRP_DNSMASQ_BIN" "$@"
EOF
chmod 755 "$test_root/bin/dnsmasq"
SSRP_REAL_DNSMASQ=1 \
SSRP_DNSMASQ_BIN="$dnsmasq_bin" \
SSRP_PARSER_LOG="$test_root/dnsmasq-parser.log" \
PATH="$test_root/bin:$PATH" \
python3 tests/test_ssrplus_runtime.py
[[ -s "$test_root/dnsmasq-parser.log" ]] ||
    fail "runtime harness did not call the real dnsmasq parser"
grep -Eq -- '(^|[[:space:]])(--test|-t)([[:space:]]|$)' "$test_root/dnsmasq-parser.log" ||
    fail "dnsmasq parser audit did not contain a syntax check"
echo "Real dnsmasq parser accepted the generated SSR configuration: PASS"
