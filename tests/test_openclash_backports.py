#!/usr/bin/env python3
"""Execute upstream OpenClash files after the production compatibility fixer.

The JavaScript regressions catch status writes to the first dashboard card from
handlers registered once globally. Ruby regressions exercise the actual guard
and overwrite entry point, including the Ruby 3.4 literal AST node variants.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from openclash_fixture import make_package


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/openclash/0.48.002"
BASH = os.environ.get("BASH") or (
    "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
NODE = os.environ.get("NODE") or shutil.which("node")
RUBY = os.environ.get("RUBY") or shutil.which("ruby")
if os.environ.get("OPENCLASH_REQUIRE_NODE") == "1" and not NODE:
    raise RuntimeError("Node is required by OPENCLASH_REQUIRE_NODE")
ORIGINAL = os.environ.get("PLUGIN_FIX_MODE") == "original"
SOURCES = {
    "YAML.rb": ("root/usr/share/openclash/YAML.rb", "1addd1d1cbf09de4ecbec4593a2ba3af25c20e27"),
    "switch_dashboard.htm": ("luasrc/view/openclash/switch_dashboard.htm", "735d7fbefd51bf0e6ba716a09a630d463901138c"),
}


JAVASCRIPT = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const template = fs.readFileSync(process.argv[1], 'utf8');
const testCase = process.argv[2];
const names = ['Dashboard', 'Yacd', 'Metacubexd', 'Zashboard'];
const elements = {};
function element(value = '') {
    return {
        textContent: '', className: 'oc-flush-status',
        firstElementChild: { value, disabled: false, dataset: {} },
        set innerHTML(html) {
            this.html = html;
            this.firstElementChild = {
                value: /value="([^"]*)"/.exec(html)[1], disabled: false, dataset: {}
            };
        },
        get innerHTML() { return this.html; }
    };
}
for (const name of names) {
    elements['switch_dashboard_' + name] = element();
    elements['default_dashboard_' + name] = element('Set to Default');
    elements['delete_dashboard_' + name] = element('Delete');
    elements['switch_dashboard_status_' + name] = element();
}
const requests = [];
let confirmation = 'ok';
const context = vm.createContext({
    document: {
        getElementById: id => elements[id] || null,
        querySelectorAll: () => names.map(n => elements['default_dashboard_' + n])
    },
    XHR: { get: (url, params, callback) => requests.push({url, params, callback}) },
    ocConfirm: () => Promise.resolve(confirmation)
});
context.window = context;
for (const name of names) {
    const rendered = template.replaceAll('<%=self.option%>', name)
        .replace(/<%=luci\.dispatcher\.build_url\("admin", "services", "openclash", "([^"]+)"\)%>/g, '$1')
        .replace(/<%:([^%]+)%>/g, '$1');
    const script = /<script[^>]*>([\s\S]*?)<\/script>/.exec(rendered)[1];
    vm.runInContext(script, context, {filename: 'switch_dashboard_' + name + '.js'});
}
const initial = {
    dashboard_type: 'Official', yacd_type: 'Meta', default_dashboard: 'dashboard',
    dashboard: true, yacd: true, metacubexd: false, zashboard: false
};
for (const request of requests.splice(0)) {
    assert.equal(request.url, 'dashboard_type');
    request.callback({status: 200}, initial);
}
function status(name) { return elements['switch_dashboard_status_' + name]; }
function button(kind, name) { return elements[kind + '_dashboard_' + name].firstElementChild; }
function seedStatuses() {
    for (const name of names) {
        status(name).textContent = 'retained:' + name;
        status(name).className = 'oc-flush-status err';
    }
}
function otherStatusesUnchanged(target) {
    for (const name of names.filter(n => n !== target)) {
        assert.equal(status(name).textContent, 'retained:' + name, 'unrelated card ' + name);
        assert.equal(status(name).className, 'oc-flush-status err', 'unrelated card style ' + name);
    }
}
function takeRequest(url, name) {
    assert.equal(requests.length, 1);
    const request = requests.shift();
    assert.equal(request.url, url);
    assert.equal(request.params.name, name);
    return request;
}
(async function() {
    if (testCase === 'success') {
        for (const name of names) {
            seedStatuses();
            const btn = button('switch', name);
            assert.equal(context.switch_dashboard(btn, name, 'Meta'), false);
            assert.equal(btn.disabled, true);
            assert.equal(btn.value, 'Downloading File...');
            assert.equal(status(name).textContent, '', 'clear clicked card before HTTP');
            otherStatusesUnchanged(name);
            const request = takeRequest('switch_dashboard', name);
            assert.equal(request.params.type, 'Meta');
            request.callback({status: 200}, {download_state: 0});
            const update = name === 'Metacubexd' || name === 'Zashboard';
            assert.equal(status(name).textContent, update ? 'Update Successful' : 'Switch Successful');
            assert.equal(status(name).className, 'oc-flush-status');
            assert.equal(button('switch', name).value, update ? 'Update ' + name + ' Version' : 'Switch To Official Version');
            assert.equal(button('default', name).disabled, false);
            assert.equal(button('delete', name).disabled, false);
            otherStatusesUnchanged(name);
        }
    } else if (testCase === 'failure') {
        for (const [name, code, state, message] of [
            ['Yacd', 503, undefined, 'Switch Failed'],
            ['Metacubexd', 200, 1, 'Update Failed'],
            ['Zashboard', 200, 2, 'Unzip Error'],
            ['Dashboard', 200, 1, 'Switch Failed']
        ]) {
            seedStatuses();
            const btn = button('switch', name);
            const label = btn.value;
            context.switch_dashboard(btn, name, 'Official');
            takeRequest('switch_dashboard', name).callback({status: code}, {download_state: state});
            assert.equal(btn.disabled, false);
            assert.equal(btn.value, label);
            assert.equal(status(name).textContent, message, 'failure belongs to clicked card');
            assert.equal(status(name).className, 'oc-flush-status err');
            otherStatusesUnchanged(name);
        }
    } else if (testCase === 'delete') {
        seedStatuses();
        const btn = button('delete', 'Yacd');
        context.delete_dashboard(btn, 'Yacd');
        await Promise.resolve();
        assert.equal(status('Yacd').textContent, '', 'deletion clears only clicked card');
        assert.equal(status('Yacd').className, 'oc-flush-status');
        assert.equal(btn.disabled, true);
        otherStatusesUnchanged('Yacd');
        takeRequest('delete_dashboard', 'Yacd').callback({status: 200}, {delete_state: 1});
        assert.equal(button('default', 'Yacd').disabled, true);
        otherStatusesUnchanged('Yacd');
        seedStatuses();
        context.delete_dashboard(button('delete', 'Zashboard'), 'Zashboard');
        await Promise.resolve();
        takeRequest('delete_dashboard', 'Zashboard').callback({status: 500}, undefined);
        assert.equal(button('delete', 'Zashboard').disabled, false);
        otherStatusesUnchanged('Zashboard');
        seedStatuses();
        confirmation = null;
        context.delete_dashboard(button('delete', 'Metacubexd'), 'Metacubexd');
        await Promise.resolve();
        assert.equal(requests.length, 0);
        assert.equal(status('Metacubexd').textContent, 'retained:Metacubexd');
        otherStatusesUnchanged('Metacubexd');
    } else throw Error('unknown case ' + testCase);
    console.log('dashboard ' + testCase + ': PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''


RUBY_GUARD = r'''
require 'yaml'
eval(STDIN.read, TOPLEVEL_BINDING, ARGV.fetch(0))
def check(condition, message)
  raise message unless condition
end
if ENV['OPENCLASH_REQUIRE_RUBY34'] == '1'
  check(Gem::Version.new(RUBY_VERSION) >= Gem::Version.new('3.4'), 'Ruby 3.4+ is required for literal AST coverage')
end
values = {'integer' => ['7', 7], 'float' => ['1.25', 1.25],
          'rational' => ['3r', Rational(3)], 'imaginary' => ['4i', Complex(0, 4)],
          'regexp' => ['/edge/', /edge/]}
value = {}
values.each do |key, (source, expected)|
  check(!YAML.overwrite_code_unsafe?(source), "allowed literal rejected: #{key}")
  YAML.overwrite_apply_line(value, 'regression', "ruby_edit 'fixture' '[\"#{key}\"]' '#{source}'")
  check(value[key] == expected, "overwrite did not apply #{key}: #{value.inspect}")
end
check(!YAML.overwrite_code_unsafe?('size'), 'allowed bare method rejected')
['system', 'system("echo unsafe")', 'Kernel', '[1].map { system("echo unsafe") }',
 '`echo unsafe`', 'BEGIN { system("echo unsafe") }'].each do |source|
  check(YAML.overwrite_code_unsafe?(source), "unsafe source accepted: #{source}")
end
YAML.overwrite_apply_line(value, 'regression', %q(ruby_edit 'fixture' '["unsafe"]' 'system'))
check(!value.key?('unsafe'), 'unsafe overwrite reached eval')
puts "Ruby #{RUBY_VERSION} AST guard and overwrite entry: PASS"
'''


class OpenClashBackports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="openclash-backports-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.package = Path(cls.temporary.name) / "package"
        cls.environment = os.environ.copy()
        cls.environment.update(TEST_BASE=(ROOT / "wrt_core").as_posix(),
                               TEST_PACKAGE=cls.package.as_posix(), MSYS_NO_PATHCONV="1")
        make_package(cls.package)
        for name, (target, expected) in SOURCES.items():
            data = (FIXTURES / name).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if blob != expected:
                raise AssertionError("upstream fixture changed: " + name)
            destination = cls.package / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        cls.raw_files = cls.snapshot(cls.package)
        subprocess.run(["git", "init", "-q", str(cls.package)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(cls.package), "config", "core.autocrlf", "false"],
                       check=True, capture_output=True)
        if not ORIGINAL:
            if not BASH:
                raise AssertionError("Bash is required for the production fixer")
            cls.fix_package()

    @classmethod
    def fix_package(cls, package=None):
        environment = cls.environment.copy()
        if package is not None:
            environment["TEST_PACKAGE"] = package.as_posix()
        result = subprocess.run([BASH, "-c", 'BASE_PATH="$TEST_BASE"; source "$BASE_PATH/modules/plugin_compat.sh"; fix_openclash_compat "$TEST_PACKAGE"'],
                                env=environment, text=True, encoding="utf-8", capture_output=True)
        if result.returncode:
            raise AssertionError("production OpenClash fixer failed:\n" + result.stdout + result.stderr)

    @staticmethod
    def snapshot(package):
        return {str(path.relative_to(package)): path.read_bytes()
                for path in package.rglob("*") if path.is_file() and ".git" not in path.parts}

    def raw_package(self, package):
        for relative, data in self.raw_files.items():
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        subprocess.run(["git", "init", "-q", str(package)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(package), "config", "core.autocrlf", "false"],
                       check=True, capture_output=True)

    def run_javascript(self, case):
        if not NODE:
            self.fail("Node.js is required for dashboard behavior tests")
        result = subprocess.run([NODE, "-e", JAVASCRIPT,
                                 str(self.package / SOURCES["switch_dashboard.htm"][0]), case],
                                text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dashboard_success_updates_clicked_card(self):
        self.run_javascript("success")

    def test_dashboard_failure_updates_clicked_card(self):
        self.run_javascript("failure")

    def test_dashboard_deletion_clears_clicked_card(self):
        self.run_javascript("delete")

    def test_ruby_guard_accepts_literals_and_rejects_unsafe_calls(self):
        if not RUBY:
            if os.environ.get("OPENCLASH_REQUIRE_RUBY") == "1" or os.environ.get("OPENCLASH_REQUIRE_RUBY34") == "1":
                self.fail("Ruby is required by OPENCLASH_REQUIRE_RUBY/OPENCLASH_REQUIRE_RUBY34")
            self.skipTest("Ruby unavailable; real AST guard was not executed")
        module = self.package / SOURCES["YAML.rb"][0]
        result = subprocess.run([RUBY, "-EUTF-8", "-e", RUBY_GUARD,
                                 str(self.package / SOURCES["YAML.rb"][0])],
                                input=module.read_text(encoding="utf-8"),
                                env=self.environment, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipIf(ORIGINAL, "source reproduction omits the compatibility fixer")
    def test_reapplying_fixer_preserves_source_bytes(self):
        before = self.snapshot(self.package)
        self.fix_package()
        self.assertEqual(self.snapshot(self.package), before)

    @unittest.skipIf(ORIGINAL, "source reproduction omits the compatibility fixer")
    def test_group_accepts_raw_and_prior_two_patch_state(self):
        with tempfile.TemporaryDirectory(prefix="openclash-backports-prior-") as temporary:
            for previous in (False, True):
                with self.subTest(previous_patches=previous):
                    package = Path(temporary) / str(previous)
                    self.raw_package(package)
                    if previous:
                        for name in ("openclash-wan-subnets.patch", "openclash-checksum-filename.patch"):
                            subprocess.run(["git", "-C", str(package), "apply", str(ROOT / "wrt_core/patches" / name)],
                                           check=True, capture_output=True)
                    self.fix_package(package)
                    self.assertEqual(self.snapshot(package), self.snapshot(self.package))

    @unittest.skipIf(ORIGINAL, "source reproduction omits the compatibility fixer")
    def test_new_source_drift_rejects_before_any_partial_change(self):
        with tempfile.TemporaryDirectory(prefix="openclash-backports-drift-") as temporary:
            for name, (target, _) in SOURCES.items():
                with self.subTest(source=name):
                    package = Path(temporary) / name
                    self.raw_package(package)
                    (package / target).write_text("unreviewed upstream replacement\n", encoding="utf-8")
                    before = self.snapshot(package)
                    with self.assertRaisesRegex(AssertionError, "production OpenClash fixer failed"):
                        self.fix_package(package)
                    self.assertEqual(self.snapshot(package), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
