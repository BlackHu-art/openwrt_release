/* Kernel/UCI boundary doubles only; production functions are inserted by tests. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <limits.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif

#define REQUIRE(condition) do { if (!(condition)) { fprintf(stderr, "line %d: %s\n", __LINE__, #condition); return 1; } } while (0)
#define GFP_KERNEL 1
#define GFP_ATOMIC 2
#define MIN_HTTP_DATA_LEN 16
#define AF_TRUE 1
#define IPPROTO_TCP 6
#define HTTP_METHOD_GET 1
#define HTTP_METHOD_POST 2
#define NF_ACCEPT 1
#define AF_ERROR(...) ((void)0)
#define AF_LMT_DEBUG(...) ((void)0)
#ifndef min
#define min(a, b) ((a) < (b) ? (a) : (b))
#endif
typedef unsigned char u8;
typedef uint32_t u_int32_t;
typedef struct {
    int match, method, url_len, host_len, data_len;
    char *url_pos, *host_pos, *data_pos;
} http_proto_t;
typedef struct {
    unsigned char *l4_data;
    int l4_len, l4_protocol, src, dst, sport, dport;
    http_proto_t http;
} flow_info_t;
struct sk_buff {
    unsigned char *data;
    unsigned char *fragment;
    unsigned int len, head_len;
    int nonlinear;
};
struct skb_seq_state { struct sk_buff *skb; unsigned int from, to; };
typedef struct { int unused; } af_conn_t;
static int af_conn_lock, allocation_calls, live_allocations, last_gfp;
static int fail_allocation, fail_copy, copy_calls;
static void *kmalloc(size_t len, int flags) {
    void *allocation;
    allocation_calls++;
    last_gfp = flags;
    if (fail_allocation || len > 65536) return NULL;
    allocation = malloc(len ? len : 1);
    if (allocation) live_allocations++;
    return allocation;
}
static void kfree(void *allocation) { if (allocation) { live_allocations--; free(allocation); } }
static int skb_is_nonlinear(struct sk_buff *skb) { return skb->nonlinear; }
static int skb_copy_bits(struct sk_buff *skb, int from, void *output, int len) {
    int index;
    copy_calls++;
    if (fail_copy || !skb || from < 0 || len < 0 || (unsigned)from > skb->len || (unsigned)len > skb->len - from) return -1;
    for (index = 0; index < len; index++) {
        unsigned int position = (unsigned int)(from + index);
        ((unsigned char *)output)[index] = position < skb->head_len ? skb->data[position] : skb->fragment[position - skb->head_len];
    }
    return 0;
}
/* Old sequence API model allows the unpatched functions to compile for RED. */
static void skb_prepare_seq_read(struct sk_buff *skb, unsigned int from, unsigned int to, struct skb_seq_state *state) { state->skb = skb; state->from = from; state->to = to; }
static unsigned int skb_seq_read(unsigned int consumed, const u8 **ptr, struct skb_seq_state *state) {
    unsigned int position = state->from + consumed, end;
    if (!state->skb || position >= state->to || position >= state->skb->len) return 0;
    if (position < state->skb->head_len) { *ptr = state->skb->data + position; end = state->skb->head_len; }
    else { *ptr = state->skb->fragment + position - state->skb->head_len; end = state->skb->len; }
    return min(end, state->to) - position;
}
static void skb_abort_seq_read(struct skb_seq_state *state) { (void)state; }
static void spin_lock(int *lock) { (*lock)++; }
static void spin_unlock(int *lock) { (*lock)--; }
static af_conn_t *af_conn_find_and_add(int a, int b, int c, int d, int e) { (void)a; (void)b; (void)c; (void)d; (void)e; return NULL; }

struct uci_context { int unused; };
struct in_addr { uint32_t s_addr; };
#define CMD_GET_LAN_IP_FMT "ip:%s"
#define CMD_GET_LAN_MASK_FMT "mask:%s"
#define MIN_INET_ADDR_LEN 7
static int lan_missing, wrong_schema, saw_custom_interface;
static uint32_t actual_lan_ip, actual_lan_mask;
static struct uci_context context;
static struct uci_context *uci_alloc_context(void) { return &context; }
static void uci_free_context(struct uci_context *ctx) { (void)ctx; }
static int fwx_uci_get_value(struct uci_context *ctx, const char *key, char *output, int len) {
    (void)ctx; (void)len;
    if (strcmp(key, "fwx.global.lan_ifname")) { wrong_schema = 1; return -1; }
    if (lan_missing) return -1;
    strcpy(output, "br-test"); return 0;
}
static void exec_with_result_line(const char *command, char *output, size_t len) {
    (void)len;
    if (strstr(command, "br-test")) { saw_custom_interface++; strcpy(output, command[0] == 'i' ? "10.23.0.1" : "255.255.255.0"); }
    else if (strstr(command, "br-lan")) strcpy(output, command[0] == 'i' ? "10.0.0.1" : "255.255.255.0");
}
static int inet_aton(const char *text, struct in_addr *address) { address->s_addr = strcmp(text, "255.255.255.0") == 0 ? 0xffffff00u : strcmp(text, "10.23.0.1") == 0 ? 0x0a170001u : 0x0a000001u; return 1; }
static void update_fwx_proc_u32_value(const char *key, uint32_t value) { if (!strcmp(key, "lan_ip")) actual_lan_ip = value; else actual_lan_mask = value; }

/* PRODUCTION_FUNCTIONS */

static struct sk_buff packet(unsigned int length) {
    struct sk_buff skb;
    unsigned int index;
    skb.len = length; skb.head_len = min(length, 32); skb.nonlinear = 1;
    skb.data = malloc(skb.head_len ? skb.head_len : 1);
    skb.fragment = malloc(length - skb.head_len + 1);
    for (index = 0; index < length; index++) {
        if (index < skb.head_len) skb.data[index] = (unsigned char)(index % 251);
        else skb.fragment[index - skb.head_len] = (unsigned char)(index % 251);
    }
    return skb;
}
static void free_packet(struct sk_buff *skb) { free(skb->data); free(skb->fragment); }
static int test_copy(void) {
    struct sk_buff skb = packet(80);
    unsigned char *bytes = read_skb(&skb, 25, 40);
    int index;
    REQUIRE(bytes != NULL);
    for (index = 0; index < 40; index++) REQUIRE(bytes[index] == (unsigned char)((25 + index) % 251));
    REQUIRE(last_gfp == GFP_ATOMIC);
    REQUIRE(allocation_calls == 1);
    kfree(bytes); free_packet(&skb); REQUIRE(live_allocations == 0); return 0;
}
static int test_range(void) {
    struct sk_buff skb = packet(80);
    int cases[][2] = {{-1, 1}, {0, 0}, {0, -1}, {81, 1}, {80, 1}, {79, 2}, {INT_MAX, INT_MAX}};
    unsigned int index;
    for (index = 0; index < sizeof(cases) / sizeof(cases[0]); index++) REQUIRE(read_skb(&skb, cases[index][0], cases[index][1]) == NULL);
    REQUIRE(read_skb(NULL, 0, 1) == NULL);
    REQUIRE(allocation_calls == 0); REQUIRE(copy_calls == 0);
    free_packet(&skb); return 0;
}
static int test_copy_failure(int allocation) {
    struct sk_buff skb = packet(80);
    fail_allocation = allocation; fail_copy = !allocation;
    REQUIRE(read_skb(&skb, 25, 40) == NULL);
    REQUIRE(live_allocations == 0); REQUIRE(allocation_calls == 1);
    free_packet(&skb); return 0;
}
static int test_nonlinear(void) {
    int lengths[] = {2999, 3000, 3001, 7000};
    unsigned int index;
    int hook;
    for (hook = 0; hook < 2; hook++) for (index = 0; index < sizeof(lengths) / sizeof(lengths[0]); index++) {
        struct sk_buff skb = packet((unsigned int)lengths[index] + 20);
        flow_info_t flow;
        int position, copied;
        memset(&flow, 0, sizeof(flow)); flow.l4_data = skb.data + 20; flow.l4_len = lengths[index];
        copied = hook ? copy_fwx_hook_gateway_handle(&skb, &flow) : copy_fwx_hook_bypass_handle(&skb, &flow);
        REQUIRE(copied == 77);
        REQUIRE(flow.l4_len == min(lengths[index], 3000));
        for (position = 0; position < flow.l4_len; position++) REQUIRE((unsigned char)flow.l4_data[position] == (unsigned char)((position + 20) % 251));
        kfree(flow.l4_data); free_packet(&skb); REQUIRE(live_allocations == 0);
    }
    return 0;
}
static unsigned char *guarded_data(const char *text, size_t length) {
    char *region;
    size_t page;
#ifdef _WIN32
    SYSTEM_INFO info;
    DWORD old_protect;
    GetSystemInfo(&info); page = info.dwPageSize;
    region = VirtualAlloc(NULL, page * 2, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!region || !VirtualProtect(region + page, page, PAGE_NOACCESS, &old_protect)) abort();
#else
    page = (size_t)sysconf(_SC_PAGESIZE);
    region = mmap(NULL, page * 2, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (region == MAP_FAILED || mprotect(region + page, page, PROT_NONE)) abort();
#endif
    memcpy(region + page - length, text, length);
    return (unsigned char *)(region + page - length);
}
static int test_http_short(void) {
    const char *cases[] = {"abcdefghijklmno\r", "abcdefghijklmn\r\n", "abcdefghij\r\nG\r\n", "abcdefghij\r\nP\r\n", "abcdefghij\r\nHost:\r\n", "abcdefghij\r\n\r\n"};
    unsigned int index;
    flow_info_t flow;
    for (index = 0; index < sizeof(cases) / sizeof(cases[0]); index++) {
        size_t length = strlen(cases[index]);
        memset(&flow, 0, sizeof(flow)); flow.l4_protocol = IPPROTO_TCP;
        flow.l4_len = (int)length; flow.l4_data = guarded_data(cases[index], length);
        dpi_http_proto(&flow);
        REQUIRE(flow.http.match == 0); REQUIRE(flow.http.host_len >= 0); REQUIRE(flow.http.url_len >= 0); REQUIRE(flow.http.data_len >= 0);
    }
    memset(&flow, 0, sizeof(flow)); flow.l4_protocol = IPPROTO_TCP; flow.l4_len = 16;
    dpi_http_proto(&flow);
    return 0;
}
static int test_http_valid(void) {
    const char *cases[] = {"GET /a HTTP/1.1\r\nHost: example.test\r\n\r\nbody", "POST /b HTTP/1.1\r\nHost: example.test\r\n\r\nbody"};
    unsigned int index;
    for (index = 0; index < 2; index++) {
        flow_info_t flow;
        size_t length = strlen(cases[index]);
        memset(&flow, 0, sizeof(flow)); flow.l4_protocol = IPPROTO_TCP;
        flow.l4_len = (int)length; flow.l4_data = guarded_data(cases[index], length);
        dpi_http_proto(&flow);
        REQUIRE(flow.http.match == 1); REQUIRE(flow.http.method == (index ? HTTP_METHOD_POST : HTTP_METHOD_GET));
        REQUIRE(flow.http.url_len == 11); REQUIRE(!memcmp(flow.http.url_pos, index ? "/b HTTP/1.1" : "/a HTTP/1.1", 11));
        REQUIRE(flow.http.host_len == 12); REQUIRE(!memcmp(flow.http.host_pos, "example.test", 12));
        REQUIRE(flow.http.data_len == 4); REQUIRE(!memcmp(flow.http.data_pos, "body", 4));
    }
    return 0;
}
static int test_lan(void) {
    update_lan_ip(); REQUIRE(wrong_schema == 0); REQUIRE(saw_custom_interface == 2);
    REQUIRE(actual_lan_ip == 0x0a170001u); REQUIRE(actual_lan_mask == 0xffffff00u);
    lan_missing = 1; update_lan_ip(); REQUIRE(actual_lan_ip == 0x0a000001u); REQUIRE(actual_lan_mask == 0xffffff00u);
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "copy")) return test_copy();
    if (!strcmp(argv[1], "range")) return test_range();
    if (!strcmp(argv[1], "copy-failure")) return test_copy_failure(0);
    if (!strcmp(argv[1], "allocation-failure")) return test_copy_failure(1);
    if (!strcmp(argv[1], "lock")) { REQUIRE(connection_allocation() == NF_ACCEPT); REQUIRE(af_conn_lock == 0); return 0; }
    if (!strcmp(argv[1], "nonlinear")) return test_nonlinear();
    if (!strcmp(argv[1], "http-short")) return test_http_short();
    if (!strcmp(argv[1], "http-valid")) return test_http_valid();
    if (!strcmp(argv[1], "lan")) return test_lan();
    return 2;
}
