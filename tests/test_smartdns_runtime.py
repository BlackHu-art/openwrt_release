#!/usr/bin/env python3
"""Run the pinned production shutdown function against its resource contract.

The C harness models client-owned server_info and the server's cleanup use of it;
it does not replace a complete SmartDNS process/ASan or router shutdown test.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from c_test_env import compile_c


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/smartdns-runtime/136c0c2'
PATCH = ROOT / 'wrt_core/patches/101-smartdns-shutdown-order.patch'
EXPIRED_PATCH = ROOT / 'wrt_core/patches/103-smartdns-serve-expired-no.patch'
SOURCE_SHA256 = '7f53978859535bc18762935d00502c34a2ee0e66549567128af88cbd70bef62d'


def shutdown_function(data):
    # Include the exact original function declaration/body, not a translated
    # list of calls. A changed implementation must run through the same harness.
    match = re.search(rb'static void _smartdns_exit\(void\)\n\{.*?\n\}', data, re.S)
    if match is None:
        raise AssertionError('Pinned production shutdown function is missing')
    return match.group().decode('ascii')


class SmartdnsShutdown(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='smartdns-shutdown-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.original = (FIXTURE / 'src/smartdns.c').read_bytes()
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), SOURCE_SHA256)
        for source in FIXTURE.rglob('*'):
            if source.is_file():
                target = self.directory / source.relative_to(FIXTURE)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        self.source = self.directory / 'src/smartdns.c'

    def run_shutdown(self, source):
        harness = r'''
#include <stdio.h>
#include <stdlib.h>
struct server_info { int active; };
static struct server_info *client_owned_server;
static int violation, closed, calls[11];
static void _smartdns_plugin_exit(void) { calls[0]++; }
static void dns_client_exit(void) {
    calls[1]++;
    free(client_owned_server);
    client_owned_server = NULL;
}
static void proxy_exit(void) { calls[2]++; }
static void fast_ping_exit(void) { calls[3]++; }
static void dns_server_exit(void) {
    calls[4]++;
    /* _dns_server_close_socket needs the client's server_info during exit. */
    if (client_owned_server == NULL) {
        fputs("server cleanup used released client server_info\n", stderr);
        violation = 41;
        return;
    }
    client_owned_server->active = 0;
    closed++;
}
static void dns_stats_exit(void) { calls[5]++; }
static void _smartdns_destroy_ssl(void) { calls[6]++; }
static void dns_timer_destroy(void) { calls[7]++; }
static void tlog_exit(void) { calls[8]++; }
static void dns_server_load_exit(void) { calls[9]++; }
'''
        harness += shutdown_function(source)
        harness += r'''
int main(void) {
    client_owned_server = malloc(sizeof(*client_owned_server));
    if (!client_owned_server) return 45;
    client_owned_server->active = 1;
    _smartdns_exit();
    if (violation) return violation;
    if (client_owned_server != NULL || closed != 1) return 42;
    for (int i = 0; i < 10; i++) if (calls[i] != 1) return 43;
    return 0;
}
'''
        program = self.directory / 'shutdown.c'
        executable = self.directory / ('shutdown.exe' if os.name == 'nt' else 'shutdown')
        program.write_text(harness, encoding='ascii')
        compile_c(program, executable)
        return subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)

    def apply_patch(self, patch=PATCH):
        self.assertTrue(patch.is_file(), 'Production SmartDNS runtime patch missing')
        result = subprocess.run(['git', 'apply', '--check', str(patch)], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run(['git', 'apply', str(patch)], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_original_production_function_exposes_released_resource(self):
        result = self.run_shutdown(self.original)
        self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
        self.assertIn('released client server_info', result.stderr)

    def test_patched_production_function_closes_server_before_releasing_resources(self):
        # Before the patch exists, deliberately run the unmodified function so
        # the RED failure demonstrates the lifecycle bug, not a missing file.
        if PATCH.exists():
            self.apply_patch()
        result = self.run_shutdown(self.source.read_bytes())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((FIXTURE / 'src/smartdns.c').read_bytes(), self.original)

    def test_patch_rejects_changed_preimage_and_repeated_application(self):
        self.apply_patch()
        before = self.source.read_bytes()
        result = subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_bytes(), before)
        self.source.write_bytes(self.original.replace(b'\tdns_client_exit();',
                                                       b'\tdns_client_exit_changed();'))
        before = self.source.read_bytes()
        result = subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_bytes(), before)

    def test_raw_source_and_license_match_independent_git_blob_identities(self):
        manifest = json.loads((FIXTURE / 'provenance.json').read_bytes())
        for name, expected in manifest['files'].items():
            data = (FIXTURE / name).read_bytes()
            blob = b'blob ' + str(len(data)).encode() + b'\0' + data
            self.assertEqual(hashlib.sha1(blob).hexdigest(), expected['git_blob'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256'])

    def run_cache_contract(self):
        def function(relative, name):
            data = (self.directory / relative).read_bytes()
            match = re.search(rb'int ' + name.encode() + rb'\([^\n]*\)\n\{.*?\n\}', data, re.S)
            self.assertIsNotNone(match, 'Missing real production function ' + name)
            return match.group().decode('ascii')

        harness = r'''
#include <stdio.h>
#include <string.h>
#define BIND_FLAG_NO_CACHE 1
#define DNS_T_A 1
#define DNS_T_AAAA 28
#define DNS_RC_NOERROR 0
#define DNS_QUEY_OPTION_ECS_DNS 1
#define DNS_QUEY_OPTION_EDNS0_DO 2
#define PREFETCH_FLAGS_NOPREFETCH 1
#define DOMAIN_CHECK_NONE 0
#define tlog(...) ((void)0)
struct dns_conf_group {
    int dns_serve_expired, dns_serve_expired_reply_ttl;
    int dns_dualstack_ip_allow_force_AAAA, dns_dualstack_ip_selection_threshold;
};
struct check_orders { struct { int type; } orders[1]; };
struct dns_request {
    struct dns_conf_group *conf;
    struct check_orders *check_order_list;
    char *dns_group_name, *domain;
    char cname[256];
    int qtype, server_flags, dualstack_selection, id, ip_ttl, no_serve_expired;
    int has_ecs, ecs, edns0_do, passthrough, has_soa, no_cache;
    void *conn;
};
struct dns_cache { struct { int qtype, speed; } info; };
struct dns_cache_key { char *dns_group_name, *domain; int qtype, query_flag; };
struct dns_server_query_option { int server_flags, ecs_enable_flag, ecs_dns; char *dns_group_name; };
static struct { int cachesize; } dns_conf = { 1 };
static struct dns_cache cached = { { DNS_T_A, 1 } };
static int cached_ttl, served, released, refreshed, updated;
static int _dns_server_has_bind_flag(struct dns_request *r, int flag) { (void)r; (void)flag; return 1; }
static struct dns_cache *dns_cache_lookup(struct dns_cache_key *key) { (void)key; return &cached; }
static int _dns_server_is_dns64_request(struct dns_request *r) { (void)r; return 0; }
static int _dns_server_get_expired_ttl_reply(struct dns_request *r, struct dns_cache *c) { (void)r; (void)c; return 5; }
static int _dns_server_reply_SOA(int code, struct dns_request *r) { (void)code; (void)r; return 0; }
static int dns_cache_get_ttl(struct dns_cache *c) { (void)c; return cached_ttl; }
static int _dns_server_process_cache_data(struct dns_request *r, struct dns_cache *c) { (void)r; (void)c; served++; return 0; }
static int dns_cache_get_query_flag(struct dns_cache *c) { (void)c; return 0; }
static char *dns_cache_get_dns_group_name(struct dns_cache *c) { (void)c; return "default"; }
static void _dns_server_prefetch_request(char *d, int q, struct dns_server_query_option *o, int f) { (void)d; (void)q; (void)o; (void)f; refreshed++; }
static void dns_cache_update(struct dns_cache *c) { (void)c; updated++; }
static void dns_cache_release(struct dns_cache *c) { (void)c; released++; }
static int _dns_server_get_conf_ttl(struct dns_request *r, int ttl) { (void)r; return ttl; }
'''
        harness += function('src/dns_server/cache.c', '_dns_server_process_cache')
        harness += '\n' + function('src/dns_server/rules.c', '_dns_server_get_reply_ttl')
        harness += r'''
static int check_case(int global, int per_request, int ttl, int expect_cache, int reply_ttl) {
    struct dns_conf_group group = { global, 5, 0, 10 };
    struct check_orders orders = { { { 1 } } };
    struct dns_request r = {0};
    r.conf = &group; r.check_order_list = &orders;
    r.domain = "example.test"; r.dns_group_name = "default";
    r.qtype = DNS_T_A; r.no_serve_expired = per_request;
    cached_ttl = ttl; served = released = refreshed = updated = 0;
    int ret = _dns_server_process_cache(&r);
    if ((ret == 0) != expect_cache || served != expect_cache || released != 1) {
        fprintf(stderr, "cache policy mismatch global=%d request=%d ttl=%d served=%d ret=%d\n", global, per_request, ttl, served, ret);
        return 51;
    }
    if (refreshed != (expect_cache && ttl == 0) || updated != (expect_cache && ttl != 0)) return 52;
    if (_dns_server_get_reply_ttl(&r, 60) != reply_ttl) {
        fprintf(stderr, "reply TTL policy mismatch global=%d request=%d\n", global, per_request);
        return 53;
    }
    return 0;
}
int main(void) {
    int ret;
    /* Default yes remains usable; explicit no must reject stale cache. */
    if ((ret = check_case(1, 0, 0, 1, 5))) return ret;
    if ((ret = check_case(0, 0, 0, 0, 60))) return ret;
    if ((ret = check_case(0, 0, -1, 0, 60))) return ret;
    if ((ret = check_case(1, 1, 0, 0, 60))) return ret;
    if ((ret = check_case(0, 0, 60, 1, 60))) return ret;
    if ((ret = check_case(1, 0, 60, 1, 5))) return ret;
    return 0;
}
'''
        program = self.directory / 'cache-contract.c'
        program.write_text(harness, encoding='ascii')
        executable = self.directory / ('cache-contract.exe' if os.name == 'nt' else 'cache-contract')
        compile_c(program, executable)
        return subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)

    def test_original_production_cache_ignores_explicit_global_no(self):
        result = self.run_cache_contract()
        self.assertEqual(result.returncode, 51, result.stdout + result.stderr)
        self.assertIn('cache policy mismatch global=0', result.stderr)

    def test_patched_cache_and_reply_ttl_honor_global_and_request_policy(self):
        if EXPIRED_PATCH.exists():
            self.apply_patch(EXPIRED_PATCH)
        result = self.run_cache_contract()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ttl_contract_catches_missing_second_upstream_condition(self):
        self.apply_patch(EXPIRED_PATCH)
        rules = self.directory / 'src/dns_server/rules.c'
        data = rules.read_bytes()
        fixed = b'request->conf->dns_serve_expired == 1 && request->has_soa == 0'
        self.assertIn(fixed, data)
        rules.write_bytes(data.replace(fixed, b'request->has_soa == 0'))
        result = self.run_cache_contract()
        self.assertEqual(result.returncode, 53, result.stdout + result.stderr)
        self.assertIn('reply TTL policy mismatch global=0', result.stderr)

    def test_core_group_default_and_generator_remain_untouched(self):
        defaults = (self.directory / 'src/dns_conf/dns_conf_group.c').read_bytes()
        self.assertIn(b'\tgroup_rule->dns_serve_expired = 1;', defaults)
        before = {p.relative_to(self.directory): p.read_bytes()
                  for p in self.directory.rglob('*') if p.is_file()}
        self.apply_patch(EXPIRED_PATCH)
        self.assertEqual((self.directory / 'src/dns_conf/dns_conf_group.c').read_bytes(), defaults)
        changed = {p.relative_to(self.directory).as_posix() for p in self.directory.rglob('*')
                   if p.is_file() and p.read_bytes() != before.get(p.relative_to(self.directory))}
        self.assertEqual(changed, {'src/dns_server/cache.c', 'src/dns_server/rules.c'})

    def test_expired_patch_rejects_preimage_drift_and_repeated_application(self):
        self.apply_patch(EXPIRED_PATCH)
        cached = self.directory / 'src/dns_server/cache.c'
        before = cached.read_bytes()
        result = subprocess.run(['git', 'apply', '--check', str(EXPIRED_PATCH)], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cached.read_bytes(), before)
        for relative in ('src/dns_server/cache.c', 'src/dns_server/rules.c'):
            (self.directory / relative).write_bytes((FIXTURE / relative).read_bytes())
        cached.write_bytes(cached.read_bytes().replace(
            b'if (dns_cache_get_ttl(dns_cache) <= 0 && request->no_serve_expired == 1)',
            b'if (dns_cache_get_ttl(dns_cache) < 0 && request->no_serve_expired == 1)'))
        before = cached.read_bytes()
        result = subprocess.run(['git', 'apply', '--check', str(EXPIRED_PATCH)], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cached.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
