# SmartDNS shutdown regression source

`136c0c2/src/smartdns.c` and `136c0c2/LICENSE` are unmodified upstream bytes
from [pymumu/smartdns at 136c0c2690138d6dedd8b520281aafe49112643f](https://github.com/pymumu/smartdns/tree/136c0c2690138d6dedd8b520281aafe49112643f).
The sibling source-download audit checked the canonical archive's 445 Git blobs;
`provenance.json` records this subset's independently read Git blob identities,
SHA-256 values and original modes. The source and license must remain unchanged.
The additional cache, reply-policy and group-default source files have the same
immutable origin and are also listed in that manifest.

The production patch backports only
[b6139a199232140447aff6c4ec111c222ac84993](https://github.com/pymumu/smartdns/commit/b6139a199232140447aff6c4ec111c222ac84993):
keep client-owned `server_info` alive until server cleanup finishes.
The package source update validates the immutable recipe/core archive first,
then installs `101-smartdns-shutdown-order.patch` in the build package's patches.
Normal OpenWrt preparation applies the patch after verifying that archive.

`tests/test_smartdns_runtime.py` extracts the actual production `_smartdns_exit`
function, compiles it as C, and runs it against a client/server resource-lifetime
contract. The original order returns a deterministic violation; the patched
order releases the resource after use and runs every cleanup exactly once.
This is a focused lifecycle model, not a complete SmartDNS/ASan process or a
router shutdown test. It also checks patch application, drift rejection and raw
fixture identities. The source-download tests separately verify the complete
canonical archive against the pinned Git tree.

The additional `103-smartdns-serve-expired-no.patch` starts with
[1006f640d50f1e2951e13d3e740813cc76a6739e](https://github.com/pymumu/smartdns/commit/1006f640d50f1e2951e13d3e740813cc76a6739e).
The reviewed downstream follow-up also applies the stale-cache policy before
the early dualstack SOA shortcut: stale primary entries are rejected and stale
alternates fall back to a fresh primary instead of forcing a SOA response.
The cache contract compiles the complete real `_dns_server_process_cache` and
`_dns_server_get_reply_ttl` functions, stubbing surrounding cache/network APIs.
It tests stale/fresh cache, explicit global no, per-request no and default yes;
it also checks reply TTL behavior and catches omission of the second condition.
For both A and AAAA primary queries, a faster alternate exercises the real early
SOA branch with stale primary/alternate, both fresh, and policy yes/no cases.
The core group default remains yes, and this patch changes only cache/reply C
conditions; it does not change configuration generation or stored user settings.
This focused C test does not run a complete SmartDNS daemon or DNS transport.
