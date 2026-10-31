#!/usr/bin/env python3
"""Run stable OpenClash download, Lua rename and Ruby merge entry points offline."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from openclash_fixture import ROOT, SOURCES, make_package
from test_openclash_filename import LUA_BOUNDARIES
from lupa.lua51 import LuaRuntime

BASH = os.environ.get("BASH") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
RUBY = os.environ.get("RUBY") or shutil.which("ruby")
if RUBY:
    RUBY = str(Path(RUBY).resolve())
CORE = ROOT / "wrt_core"
VALID = "proxies:\n  - {name: new-node, type: direct}\nproxy-groups: []\n"
OLD = "proxies:\n  - {name: old-node, type: direct}\n"


class UpdatePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = tempfile.TemporaryDirectory(prefix="openclash-updates-")
        cls.package = Path(cls.sandbox.name) / "package"
        make_package(cls.package)
        subprocess.run(["git", "init", "-q", str(cls.package)], check=True)
        subprocess.run(["git", "-C", str(cls.package), "config", "core.autocrlf", "false"], check=True)
        helper = CORE / "openclash_runtime_compat.py"
        if helper.exists() and os.environ.get("PLUGIN_FIX_MODE") != "original":
            result = subprocess.run([sys.executable, str(helper), "prepare", "--core", str(CORE), "--package", str(cls.package)], capture_output=True, text=True, encoding="utf-8")
        else:
            legacy = ["openclash-wan-subnets.patch", "openclash-checksum-filename.patch", "openclash-ruby-ast.patch", "openclash-dashboard-switch.patch", "openclash-filename-safety.patch", "openclash-tun-stack.patch"]
            result = subprocess.run(["git", "-C", str(cls.package), "apply", *[str(CORE / "patches" / patch) for patch in legacy]], capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="openclash-runtime-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        for name in ("config", "tmp", "history"):
            (self.directory / name).mkdir()

    def command(self, args, **kwargs):
        result = subprocess.run(args, cwd=self.directory, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def ruby(self, body):
        self.assertTrue(RUBY, "Ruby is required for the executable OpenClash regressions")
        libs = self.package / "root/usr/share/openclash"
        # Native Windows has a case-insensitive filesystem: -I would make the
        # plugin's YAML.rb shadow the stdlib yaml.rb. Load stdlib first, then
        # evaluate the complete production modules with their filename metadata.
        loader = 'ARGV.shift(2).each { |p| eval(File.read(p, encoding: "UTF-8").gsub("/tmp/", "tmp/"), TOPLEVEL_BINDING, p) }; '
        return self.command([RUBY, "-E", "UTF-8", "-ryaml", "-rjson", "-e", loader + "eval(STDIN.read, TOPLEVEL_BINDING)",
                             str(libs / "YAML.rb"), str(libs / "uci.rb")], input=body)

    def shell(self, body, *, payload=VALID, curl_status=0, core_status=0):
        libs = self.package / "root/usr/share/openclash"
        source = (libs / "openclash.sh").read_text(encoding="utf-8")
        source = source[source.index("config_test()\n"):source.index("#分别获取订阅信息进行处理")]
        source = source.replace('"/usr/share/openclash"', json.dumps(libs.as_posix()))
        source = source.replace("/etc/openclash/config/", "config/").replace("/tmp/", "tmp/")
        (self.directory / "functions.sh").write_text(source, encoding="utf-8", newline="\n")
        for filename in ("openclash_curl.sh", "openclash_etag.sh"):
            text = (libs / filename).read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if not line.startswith(". "))
            text = text.replace("/tmp/", "tmp/")
            (self.directory / filename).write_text(text + "\n", encoding="utf-8", newline="\n")
        (self.directory / "payload.yaml").write_text(payload, encoding="utf-8", newline="\n")
        (self.directory / "config/中文 配置.yaml").write_text(OLD, encoding="utf-8", newline="\n")
        (self.directory / "core.sh").write_text('#!/bin/bash\necho "fatal: unusable configuration" >&2\nexit ' + str(core_status) + '\n', encoding="utf-8", newline="\n")
        (self.directory / "core.sh").chmod(0o755)
        prefix = r'''
source ./openclash_etag.sh
source ./openclash_curl.sh
source ./functions.sh
ETAG_CACHE=history/etag
LOG_OUT() { :; }; LOG_TIP() { :; }; LOG_INFO() { :; }; LOG_ERROR() { echo "$*" >> tmp/errors; }; LOG_WARN() { :; }
sleep() { :; }
ruby() {
  local program
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -e) program="$2"; shift 2; break;;
      -I|-E) shift 2;;
      -ryaml|-rYAML) shift;;
      *) echo "unexpected Ruby adapter argument $1" >&2; return 99;;
    esac
  done
  "$RUBY" -E UTF-8 -ryaml -e 'eval(File.read(ARGV.shift, encoding: "UTF-8"), TOPLEVEL_BINDING); eval(ARGV.shift, TOPLEVEL_BINDING)' "$YAML_LIBRARY" "$program" "$@"
}
uci_get_age_secret_keys() { :; }
config_get() {
  local result="$4"
  case "$3" in name) result='中文 配置';; address) result='https://example.invalid/sub';; keyword) result="${TEST_KEYWORD:-}";; esac
  printf -v "$1" '%s' "$result"
}
config_get_bool() { config_get "$@"; }
config_list_foreach() { if [ "$2" = keyword ] && [ -n "${TEST_KEYWORD:-}" ]; then "$3" "$TEST_KEYWORD" "$4"; fi; }
pidof() { return 1; }
uci() { :; }
curl() {
  local header output
  while [ "$#" -gt 0 ]; do
    case "$1" in -D) header="$2"; shift;; -o) output="$2"; shift;; esac
    shift
  done
  printf 'HTTP/1.1 200 OK\r\netag: "new-tag"\r\n' > "$header"
  cp payload.yaml "$output"
  printf '\n200\n'
  return "$CURL_STATUS"
}
CLASH=./core.sh
CLASH_CONFIG=.
LOG_FILE=tmp/log
CONFIG_PATH='config/中文 配置.yaml'
router_self_proxy=0
restart=0; only_download=0; norestart=1; exit_code=0
SAVE_ETAG_TO_CACHE 'https://example.invalid/sub' old-tag "$CONFIG_PATH"
'''
        env = dict(os.environ, RUBY=str(RUBY), CURL_STATUS=str(curl_status), YAML_LIBRARY=(libs / "YAML.rb").as_posix(),
                   REAL_CORE=os.environ.get("MIHOMO_NEW_TEST_BIN", ""))
        (self.directory / "run.sh").write_text(prefix + "\n" + body, encoding="utf-8", newline="\n")
        return self.command([BASH, "--noprofile", "--norc", "run.sh"], env=env)


class SubscriptionTests(UpdatePackage):
    def test_core_nonzero_without_magic_failure_text_keeps_previous_configuration_and_etag(self):
        self.shell('sub_info_get test; [ "$exit_code" = 1 ]', core_status=23)
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)
        self.assertIn('etag="old-tag"', (self.directory / "history/etag").read_text())

    def test_download_failure_keeps_previous_configuration_and_etag(self):
        self.shell('sub_info_get test; [ "$exit_code" = 1 ]', curl_status=7)
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)
        self.assertIn('etag="old-tag"', (self.directory / "history/etag").read_text())

    def test_invalid_empty_or_missing_nodes_never_replace_or_advance_etag(self):
        for payload in ("", "[]\n", "proxies: []\n", "proxies: bad\n", "proxies: [oops]\n", "proxy-providers: {bad: 1}\n", "dns: {enable: true}\n", "proxies: [\n"):
            with self.subTest(payload=payload):
                self.shell('sub_info_get test; [ "$exit_code" = 1 ]', payload=payload)
                self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)
                self.assertIn('etag="old-tag"', (self.directory / "history/etag").read_text())

    def test_download_defers_cache_until_successful_replace(self):
        self.shell('''
name='中文 配置'; subscribe_url='https://example.invalid/sub'; CONFIG_FILE="$CONFIG_PATH"; CFG_FILE='tmp/中文 配置.yaml'
config_download
[ "$DOWNLOAD_RESULT" = 0 ] || exit 2
[ "$(GET_ETAG_BY_PATH "$CONFIG_FILE")" = old-tag ] || exit 3
yaml_sub_validate && config_test || exit 4
config_su_check
[ "$(GET_ETAG_BY_PATH "$CONFIG_FILE")" = new-tag ] || exit 5
''')
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), VALID)

    def test_failed_install_keeps_previous_file_and_cache(self):
        self.shell('''
mv() { case "$*" in *"$CONFIG_PATH") return 1;; *) command mv "$@";; esac; }
sub_info_get test
[ "$exit_code" = 1 ]
''')
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)
        self.assertIn('etag="old-tag"', (self.directory / "history/etag").read_text())

    def test_custom_filter_removing_every_node_keeps_previous_file(self):
        self.shell('''
config_cus_up() { printf 'proxies: []\n' > "$CFG_FILE"; }
sub_info_get test
[ "$exit_code" = 1 ]
''')
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)

    def test_ruby_unavailable_preserves_previous_configuration(self):
        self.shell('ruby() { return 127; }; sub_info_get test; [ "$exit_code" = 1 ]')
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)

    def test_same_valid_bytes_commit_new_etag(self):
        self.shell('sub_info_get test; [ "$exit_code" = 0 ]', payload=OLD)
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)
        self.assertIn('etag="new-tag"', (self.directory / "history/etag").read_text())

    def test_provider_only_subscription_can_replace_and_commit_etag(self):
        payload = "proxy-providers:\n  provider: {type: file, path: ./provider.yaml}\n"
        self.shell('sub_info_get test; [ "$exit_code" = 0 ]', payload=payload)
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), payload)
        self.assertIn('etag="new-tag"', (self.directory / "history/etag").read_text())

    def test_real_filter_cannot_install_configuration_rejected_by_post_filter_core_test(self):
        payload = '''proxies:
  - {name: keep, type: direct}
  - {name: drop, type: direct}
proxy-groups:
  - {name: FilterGroup, type: select, proxies: [drop]}
rules: ["MATCH,FilterGroup"]
'''
        self.shell('''
TEST_KEYWORD=keep
if [ -n "$REAL_CORE" ]; then
  CLASH="$REAL_CORE"
else
  # The external core boundary rejects the known empty-group case offline.
  # Set MIHOMO_NEW_TEST_BIN to repeat this case with the pinned real core.
  cat > core.sh <<'EOF'
#!/bin/bash
while [ "$#" -gt 0 ]; do if [ "$1" = -f ]; then file="$2"; break; fi; shift; done
if grep -q 'proxies: \[\]' "$file"; then exit 23; fi
exit 0
EOF
fi
sub_info_get test
[ "$exit_code" = 1 ]
''', payload=payload)
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), OLD)
        self.assertIn('etag="old-tag"', (self.directory / "history/etag").read_text())

    def test_absent_core_preserves_existing_yaml_validation_semantics(self):
        self.shell('CLASH=./missing-core; sub_info_get test; [ "$exit_code" = 0 ]')
        self.assertEqual((self.directory / "config/中文 配置.yaml").read_text(encoding="utf-8"), VALID)


class CacheTests(UpdatePackage):
    def test_an_old_live_writer_keeps_exclusive_access_until_release(self):
        self.shell(r'''
ETAG_CACHE=history/slow
date() {
  if [ "$1" = -r ] && [ "$2" = "${ETAG_CACHE}.lock" ]; then printf '0\n'
  elif [ "$1" = +%s ]; then printf '1000\n'
  else command date "$@"; fi
}
trap 'touch release; wait "$first" "$second" 2>/dev/null || :' EXIT
(
  awk() {
    command awk "$@"
    touch first.entered
    while [ ! -f release ]; do command sleep 0.01; done
  }
  SAVE_ETAG_TO_CACHE url first-tag first-path
) & first=$!
for attempt in $(seq 1 200); do [ -f first.entered ] && break; command sleep 0.01; done
[ -f first.entered ] || exit 2
(
  sleep() {
    touch second.waiting
    while [ ! -f release ]; do command sleep 0.01; done
    command sleep 0.05
  }
  SAVE_ETAG_TO_CACHE url second-tag second-path
  echo "$?" > second.done
) & second=$!
for attempt in $(seq 1 500); do
  [ -f second.waiting ] || [ -f second.done ] && break
  command sleep 0.01
done
[ -f second.waiting ] && [ ! -f second.done ] || exit 3
touch release
wait "$first" || exit 4
wait "$second" || exit 5
[ "$(cat second.done)" = 0 ] || exit 6
[ "$(GET_ETAG_BY_PATH first-path)" = first-tag ] || exit 7
[ "$(GET_ETAG_BY_PATH second-path)" = second-tag ] || exit 8
''')

    def test_exhausted_lock_budget_fails_without_modifying_cache(self):
        self.shell(r'''
cp "$ETAG_CACHE" before-cache
(
  exec 9>"${ETAG_CACHE}.lock"
  flock -x 9 || exit
  touch holder.ready
  while [ ! -f release ]; do command sleep 0.01; done
) & holder=$!
trap 'touch release; wait "$holder" 2>/dev/null || :' EXIT
for attempt in $(seq 1 200); do [ -f holder.ready ] && break; command sleep 0.01; done
[ -f holder.ready ] || exit 2
if SAVE_ETAG_TO_CACHE url rejected-tag "$CONFIG_PATH"; then exit 3; fi
cmp before-cache "$ETAG_CACHE" || exit 4
touch release
wait "$holder"
''')

    def test_cache_repairs_missing_fields_and_preserves_literal_backslashes(self):
        self.shell('''
key=$(printf '%s' "$CONFIG_PATH" | md5sum); key=${key%% *}
printf '[%s]\netag="broken"\n' "$key" > "$ETAG_CACHE"
SAVE_ETAG_TO_CACHE 'https://example.invalid/a\\b' 'fresh\\tag' "$CONFIG_PATH"
[ "$(GET_ETAG_BY_PATH "$CONFIG_PATH")" = 'fresh\\tag' ]
''')
        cache = (self.directory / "history/etag").read_text()
        self.assertIn('url="https://example.invalid/a\\b"', cache)
        self.assertIn('path="config/中文 配置.yaml"', cache)
        self.assertIn('time="', cache)

    def test_parallel_writers_do_not_lose_updates_or_share_temp_files(self):
        source = self.package / "root/usr/share/openclash/openclash_etag.sh"
        # Existing entries force the read/modify/write path. The slow awk boundary
        # makes all old writers read the same cache before any is allowed to move it.
        script = r'''
source "$1"
ETAG_CACHE=history/concurrent
for i in 1 2 3 4; do SAVE_ETAG_TO_CACHE url old "path-$i" || exit; done
awk() { command awk "$@"; command sleep 0.2; }
for i in 1 2 3 4; do ( SAVE_ETAG_TO_CACHE "url-$i" "new-$i" "path-$i" ) & done
result=0
for pid in $(jobs -p); do wait "$pid" || result=1; done
[ "$result" = 0 ] || exit 2
for i in 1 2 3 4; do [ "$(GET_ETAG_BY_PATH "path-$i")" = "new-$i" ] || exit 3; done
'''
        self.command([BASH, "--noprofile", "--norc", "-c", script, "concurrency", source.as_posix()])
        self.assertEqual(list((self.directory / "history").glob("*.tmp*")), [])
        self.assertTrue((self.directory / "history/concurrent.lock").is_file())


class RenameTests(UpdatePackage):
    def test_lua_rename_accepts_scalar_groups_and_queues_only_yaml_configurations(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(r'''
rows = {proxies={{['.name']='p', groups='Old'}}, proxy_providers={{['.name']='v', groups='Old'}},
        proxy_groups={{['.name']='edited', config='all'}, {['.name']='g', other_group='Old'}}, dns_servers={}}
local cursor = {}
function cursor:foreach(pkg, kind, fn) for _, row in ipairs(rows[kind] or {}) do fn(row) end end
function cursor:get(pkg, sid, key) for _, list in pairs(rows) do for _, row in ipairs(list) do if row['.name']==sid then return row[key] end end end end
function cursor:set(pkg, sid, key, value) for _, list in pairs(rows) do for _, row in ipairs(list) do if row['.name']==sid then row[key]=value end end end end
function cursor:set_list(...) self:set(...) end
function cursor:delete(pkg, sid, key) self:set(pkg, sid, key, nil) end
function cursor:add(pkg, kind) rows[kind]=rows[kind] or {}; local id='r'..#rows[kind]; table.insert(rows[kind], {['.name']=id}); return id end
function cursor:commit() end
uci=cursor; main_uci=cursor; openclash='openclash'
fs = {glob=function() return {'/etc/openclash/config/中文 配置.yaml', '/etc/openclash/config/other.yml', '/etc/openclash/config/readme.txt'} end,
      basename=function(path) return path:match('[^/]+$') end, IsYamlExt=function(name) return name:match('%.ya?ml$') ~= nil end}
''')
        source = (self.package / SOURCES["proxy-groups-config.lua"]).read_text(encoding="utf-8")
        block = source[source.index("local function sync_group_name"):source.index("local t = {")]
        lua.execute(block + '\nsync_group_name("edited", "Old", "New")')
        rows = lua.globals().rows
        self.assertEqual(rows.proxies[1].groups[1], "New")
        self.assertEqual(rows.proxy_providers[1].groups[1], "New")
        self.assertEqual(rows.proxy_groups[2].other_group[1], "New")
        self.assertEqual({row.config for row in rows.group_rename.values()}, {"中文 配置.yaml", "other.yml"})

    def test_real_ruby_merge_updates_only_policy_targets_and_chain_renames(self):
        rules = ["DOMAIN,Old,Old", "DOMAIN-SUFFIX,Old.example,Old,no-resolve", "RULE-SET,Old,Old", "MATCH,Old", "FINAL, Old ",
                 "AND,((DOMAIN,Old),(NETWORK,TCP)),Old", "DOMAIN-REGEX,^a,b$,Old", "SUB-RULE,(NETWORK,TCP),Old"]
        value = {"rules": rules, "sub-rules": {"Old": ["DOMAIN,Old,Old"]}, "listeners": [{"name": "Old", "proxy": "Old"}],
                 "tunnels": [{"proxy": "Old", "target": "Old"}], "dns": {"nameserver": ["https://Old/dns"]}, "rule-providers": {"Old": {"url": "https://Old/provider"}}}
        (self.directory / "config.yaml").write_text(json.dumps(value), encoding="utf-8")
        self.ruby('''
renames = [{'old_name'=>'Old','new_name'=>'Middle'}, {'old_name'=>'Middle','new_name'=>'New'}]
abort 'merge failed' unless UCI.merge_fragments('config.yaml', renames)
''')
        result = self.ruby("puts JSON.generate(YAML.load_file('config.yaml'))")
        actual = json.loads(result.stdout)
        self.assertEqual(actual["rules"], ["DOMAIN,Old,New", "DOMAIN-SUFFIX,Old.example,New,no-resolve", "RULE-SET,Old,New", "MATCH,New", "FINAL, New ", "AND,((DOMAIN,Old),(NETWORK,TCP)),New", "DOMAIN-REGEX,^a,b$,New", rules[-1]])
        self.assertEqual(actual["sub-rules"], {"Old": ["DOMAIN,Old,New"]})
        self.assertEqual(actual["listeners"], [{"name": "Old", "proxy": "New"}])
        self.assertEqual(actual["tunnels"], [{"target": "Old", "proxy": "New"}])
        self.assertEqual(actual["dns"], value["dns"])
        self.assertEqual(actual["rule-providers"], value["rule-providers"])

    def test_ruby_group_generation_accepts_single_value_memberships(self):
        result = self.ruby('''
group = {'name'=>'Target','type'=>'select','config'=>'test.yaml','other_group'=>'DIRECT'}
node = {'name'=>'node','groups'=>'Target','enabled'=>'1','config'=>'test.yaml'}
provider = {'name'=>'provider','groups'=>'Target','enabled'=>'1','config'=>'test.yaml'}
puts UCI.member_lines(group, [], [node], 'Target', 'test.yaml')
puts UCI.use_lines('Target', [provider], 'test.yaml')
''')
        self.assertIn('- DIRECT', result.stdout)
        self.assertIn('- "node"', result.stdout)
        self.assertIn('- provider', result.stdout)

    def test_write_proxies_consumes_only_successful_configuration_rename_queue(self):
        storage = self.directory / "storage"
        storage.mkdir()
        pending = """config group_rename 'first'
  option config '中文 配置.yaml'
  option old_name 'Old'
  option new_name 'New'
config group_rename 'unrelated'
  option config 'other.yaml'
  option old_name 'Keep'
  option new_name 'Other'
"""
        (storage / "openclash").write_text(pending, encoding="utf-8")
        (self.directory / "config.yaml").write_text("rules: [MATCH,Old]\n", encoding="utf-8")
        # The only UCI double is its external import operation; section parsing,
        # queue selection, fragment generation, YAML merge and queue deletion run
        # through the complete production Ruby module.
        self.ruby('''
def UCI.import(dir, pkg, text, order = true)
  File.write(File.join(dir, pkg), text)
  nil
end
UCI.write_proxies('config.yaml', '中文 配置.yaml', 'storage')
''')
        result = self.ruby("puts JSON.generate(YAML.load_file('config.yaml'))")
        self.assertEqual(json.loads(result.stdout)["rules"], ["MATCH", "Old"])
        # The rule above intentionally is a YAML sequence of two strings. It is
        # unrelated text and must remain untouched. A real rule is checked below.
        self.assertNotIn("'first'", (storage / "openclash").read_text(encoding="utf-8"))
        self.assertIn("'unrelated'", (storage / "openclash").read_text(encoding="utf-8"))
        (storage / "openclash").write_text(pending, encoding="utf-8")
        (self.directory / "config.yaml").write_text('rules: ["MATCH,Old"]\n', encoding="utf-8")
        self.ruby('''
def UCI.import(dir, pkg, text, order = true); File.write(File.join(dir, pkg), text); nil; end
UCI.write_proxies('config.yaml', '中文 配置.yaml', 'storage')
''')
        result = self.ruby("puts JSON.generate(YAML.load_file('config.yaml'))")
        self.assertEqual(json.loads(result.stdout)["rules"], ["MATCH,New"])

    def test_failed_yaml_merge_keeps_pending_group_rename_for_retry(self):
        storage = self.directory / "storage"
        storage.mkdir()
        pending = "config group_rename 'retry'\n  option config 'test.yaml'\n  option old_name 'Old'\n  option new_name 'New'\n"
        (storage / "openclash").write_text(pending, encoding="utf-8")
        (self.directory / "config.yaml").write_text("[]\n", encoding="utf-8")
        self.ruby('''
def UCI.import(dir, pkg, text, order = true); File.write(File.join(dir, pkg), text); nil; end
UCI.write_proxies('config.yaml', 'test.yaml', 'storage')
''')
        self.assertEqual((storage / "openclash").read_text(encoding="utf-8"), pending)

    def test_controller_reports_preserved_config_and_keeps_filename_guard(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(LUA_BOUNDARIES)
        lua.execute((self.package / "luasrc/openclash.lua").read_text(encoding="utf-8"))
        lua.execute('package.loaded["luci.i18n"].translate=function(s) return s end; luci={i18n=package.loaded["luci.i18n"]}')
        lua.execute((self.package / "luasrc/controller/openclash.lua").read_text(encoding="utf-8"))
        lua.execute('package.loaded["luci.sys"].call=function(command) record("service",command); return 1 end; reset({filename="中文 配置.yaml"})')
        controller = lua.globals().package.loaded["luci.controller.openclash"]
        controller.action_update_config()
        self.assertEqual(lua.globals().state.response.status, "error")
        self.assertIn("existing configuration was kept", lua.globals().state.response.message)
        lua.execute('reset({filename="../escape.yaml"})')
        controller.action_update_config()
        self.assertEqual(len(lua.globals().state.calls), 0)


class GuardTests(UpdatePackage):
    def load_helper(self):
        spec = importlib.util.spec_from_file_location("openclash_runtime_compat_test", CORE / "openclash_runtime_compat.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper

    def snapshot(self, package):
        return {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file() and ".git" not in p.parts}

    def metadata(self, package):
        return {p.relative_to(package).as_posix(): (p.stat().st_mode, p.stat().st_mtime_ns)
                for p in package.rglob("*") if p.is_file() and ".git" not in p.parts}

    def test_changed_content_invalidates_mtime_build_stamp_and_repeat_preserves_it(self):
        helper = self.load_helper()
        package = self.directory / "package"
        make_package(package)
        self.command(["git", "init", "-q", str(package)])
        self.command(["git", "-C", str(package), "config", "core.autocrlf", "false"])
        self.command(["git", "-C", str(package), "apply", *[str(CORE / "patches" / name) for name in helper.PATCHES[:6]]])
        old_ns = 1600000000000000000
        for path in package.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                os.utime(path, ns=(old_ns, old_ns))
        before = self.snapshot(package)
        old_meta = self.metadata(package)
        helper.prepare(CORE, package)
        after = self.snapshot(package)
        new_meta = self.metadata(package)
        changed = [name for name in before if before[name] != after[name]]
        self.assertTrue(changed)
        # OpenWrt's default find_md5 fingerprints file paths and mtimes, not bytes.
        self.assertNotEqual(old_meta, new_meta, "new contents must invalidate prepare dependency stamps")
        for name in changed:
            self.assertGreater(new_meta[name][1], old_meta[name][1], name)
            self.assertEqual(new_meta[name][0], old_meta[name][0], name)
        self.assertEqual(helper.prepare(CORE, package), 0)
        self.assertEqual(self.metadata(package), new_meta)

    def test_original_maintenance_and_managed_sources_are_rejected_without_changes(self):
        helper = self.load_helper()
        repository = self.directory / "repository"
        core = repository / "wrt_core"
        shutil.copytree(CORE / "compat/openclash-runtime", core / "compat/openclash-runtime")
        (core / "patches").mkdir()
        for name in helper.PATCHES:
            shutil.copyfile(CORE / "patches" / name, core / "patches" / name)
        for package in (repository / "maintenance/plugins/openclash/luci-app-openclash", core / "managed/packages/openclash"):
            make_package(package)
            before = self.snapshot(package)
            with self.assertRaisesRegex(ValueError, "protected|original"):
                helper.prepare(core, package)
            self.assertEqual(self.snapshot(package), before)

    def test_publication_failure_restores_every_original_file_and_removes_staging(self):
        helper = self.load_helper()
        package = self.directory / "package"
        make_package(package)
        before = self.snapshot(package)
        metadata_before = self.metadata(package)
        actual_replace = os.replace
        calls = []
        def fail_second_publication(source, target):
            calls.append(str(target))
            if len(calls) == 2:
                raise OSError("injected second publication failure")
            return actual_replace(source, target)
        with patch.object(helper.os, "replace", side_effect=fail_second_publication):
            with self.assertRaisesRegex(OSError, "injected second publication failure"):
                helper.prepare(CORE, package)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(self.snapshot(package), before)
        self.assertEqual(self.metadata(package), metadata_before)

    def test_guard_rejects_unknown_source_without_partial_six_patch_changes(self):
        helper = CORE / "openclash_runtime_compat.py"
        self.assertTrue(helper.is_file(), "whole-stack source guard is required")
        package = self.directory / "package"
        make_package(package)
        target = package / SOURCES["openclash_etag.sh"]
        target.write_bytes(target.read_bytes() + b"\n# unknown source drift\n")
        before = {path.relative_to(package).as_posix(): path.read_bytes() for path in package.rglob("*") if path.is_file()}
        result = subprocess.run([sys.executable, str(helper), "prepare", "--core", str(CORE), "--package", str(package)], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source", result.stderr.lower())
        self.assertEqual(before, {path.relative_to(package).as_posix(): path.read_bytes() for path in package.rglob("*") if path.is_file()})

    def test_complete_stack_is_idempotent_and_receipt_matches_pristine_fixtures(self):
        helper = CORE / "openclash_runtime_compat.py"
        self.assertTrue(helper.is_file(), "whole-stack source guard is required")
        manifest = json.loads((CORE / "compat/openclash-runtime/sources.json").read_text())
        for name, path in SOURCES.items():
            data = (ROOT / "tests/fixtures/openclash/0.48.002" / name).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            self.assertEqual(manifest["files"][path], blob, path)
        before = {path.relative_to(self.package).as_posix(): path.read_bytes() for path in self.package.rglob("*") if path.is_file() and ".git" not in path.parts}
        self.command([sys.executable, str(helper), "prepare", "--core", str(CORE), "--package", str(self.package)])
        self.assertEqual(before, {path.relative_to(self.package).as_posix(): path.read_bytes() for path in self.package.rglob("*") if path.is_file() and ".git" not in path.parts})

    def test_prior_six_patches_are_accepted_then_new_patch_is_applied(self):
        package = self.directory / "package"
        make_package(package)
        self.command(["git", "init", "-q", str(package)])
        self.command(["git", "-C", str(package), "config", "core.autocrlf", "false"])
        patches = ["wan-subnets", "checksum-filename", "ruby-ast", "dashboard-switch", "filename-safety", "tun-stack"]
        self.command(["git", "-C", str(package), "apply", *[str(CORE / ("patches/openclash-" + name + ".patch")) for name in patches]])
        self.command([sys.executable, str(CORE / "openclash_runtime_compat.py"), "prepare", "--core", str(CORE), "--package", str(package)])
        self.assertEqual((package / SOURCES["openclash.sh"]).read_bytes(), (self.package / SOURCES["openclash.sh"]).read_bytes())

    def test_all_sixty_four_prior_patch_subsets_produce_the_same_reviewed_stack(self):
        helper = self.load_helper()
        legacy = helper.PATCHES[:6]
        package = self.directory / "package"
        package.mkdir()
        self.command(["git", "init", "-q", str(package)])
        self.command(["git", "-C", str(package), "config", "core.autocrlf", "false"])
        expected = self.snapshot(self.package)
        for mask in range(64):
            with self.subTest(mask=mask):
                make_package(package)
                selected = [str(CORE / "patches" / name) for bit, name in enumerate(legacy) if mask & (1 << bit)]
                if selected:
                    self.command(["git", "-C", str(package), "apply", *selected])
                helper.prepare(CORE, package)
                self.assertEqual(self.snapshot(package), expected)

    def test_partial_new_patch_is_rejected_without_modifying_other_files(self):
        package = self.directory / "package"
        make_package(package)
        target = package / SOURCES["controller-openclash.lua"]
        target.write_text(target.read_text(encoding="utf-8").replace('message = "Failed to update config"', 'message = luci.i18n.translate("Subscription update failed; existing configuration was kept")'), encoding="utf-8", newline="\n")
        before = {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(CORE / "openclash_runtime_compat.py"), "prepare", "--core", str(CORE), "--package", str(package)], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source drift", result.stderr)
        self.assertEqual(before, {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
