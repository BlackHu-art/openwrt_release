# SSR Plus compatibility fixtures

`2abdc9aa/` contains complete, unmodified files from
[`fw876/helloworld` commit `2abdc9aa9e19607774dc9789709212b70b8607c6`](https://github.com/fw876/helloworld/tree/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus).
The build explicitly selects this repository's `master` branch, whose recipe at
this revision is `luci-app-ssr-plus` version `190-r3`.

| Fixture | Upstream path | SHA-256 (unchanged LF bytes) |
| --- | --- | --- |
| `shadowsocksr.init` | [`luci-app-ssr-plus/root/etc/init.d/shadowsocksr`](https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/etc/init.d/shadowsocksr) | `6a28c0dfe329f1f20321cacc87ba9512c04af3d8df35722b8e27d6631a88113c` |
| `gfw2ipset.sh` | [`luci-app-ssr-plus/root/usr/share/shadowsocksr/gfw2ipset.sh`](https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/usr/share/shadowsocksr/gfw2ipset.sh) | `2d456af581fcca037e259c285c202f564bfdba00057186f95d626e0db2700309` |
| `update.lua` | [`luci-app-ssr-plus/root/usr/share/shadowsocksr/update.lua`](https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/usr/share/shadowsocksr/update.lua) | `6e925dcd45db3e8884d089d6db48767b2cbcf4de6892b6c16e6956948707df62` |
| `Makefile` | [`luci-app-ssr-plus/Makefile`](https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/Makefile) | `2cc1cf3b4ad9aeb7a4fd4f11f14d7b7264ec64e658645aaf531fe8ec54d49d63` |
| `luci-ssr-plus.defaults` | `luci-app-ssr-plus/root/etc/uci-defaults/luci-ssr-plus` | `af7badfb5dd15082a28229dfaf8af1078e8b96d1f7d6936675818c5b3da9ae7b` |
| `shadowsocksr.config` | `luci-app-ssr-plus/root/usr/share/shadowsocksr/shadowsocksr.config` | `abafa2a4b47fd716c6a0d77dc6a94894d2391b1def56baa6e2396d70f12a8fd3` |

The init script retains its upstream copyright notices and GNU GPL version 3 or
later notice. `COPYING` is the unmodified [upstream root `LICENSE`](https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/LICENSE)
from that same commit (SHA-256
`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`).

`tests/test_ssrplus_compat.sh` applies the real production compatibility helper
and patches to this complete package fixture. The package has no own `.git` and
sits below a parent repository, matching sparse feed transfer. The tests cover
all already-applied patch subsets, repeat application, unknown changes in each
affected source file, a partly patched package, missing patch artifacts and a
missing package. Rejections must preserve every package file. These tests do not
execute router commands, launch services, or modify host routing; Linux runtime
semantics require the separate runtime harness.

All eight subsets of the three legacy startup/DNS/persistence patches and the
complete dependent repair set must converge to the same package, versioned
`190-r10`. Complete r4/r5 sources retain their original nine-target manifests;
r6/r7/r8 sources retain fourteen/sixteen/nineteen patch hashes and eleven targets,
including the 0644 template. Complete r9 sources retain all twenty-one original
patch hashes and their twelve-target manifest, including the unchanged generator.
All upgrade to the twelve-target r10 manifest and prepare twice without drift.
The build gate reverses complete patches only in
an isolated copy, then compares the original Git blobs before writing any feed
source. Unknown changes outside patch context, incomplete patches, a missing
runtime source, and a changed installed runtime helper are rejected. Tests also
exercise the actual pre-install stage order and its explicit failure propagation.
The installed `root/usr/share/shadowsocksr/ssrp-runtime.sh` must be byte-identical
to `wrt_core/compat/ssrplus/runtime.sh`.

The full twelve-file baseline is recorded in
`wrt_core/compat/ssrplus/source-files.tsv`; the ordered twenty-three-patch repair set is
`wrt_core/compat/ssrplus/patches.list`. Additional unchanged fixtures cover
`subscribe.lua`, `ssr-monitor`, `ssr-switch`, and `ssrplusupdate.sh`; the reviewed
`ssr-rules` fixture is in the adjacent `ssrplus-persistence/` directory.

`gen_config.lua` is an additional, unmodified public fixture from the same
commit, upstream path `luci-app-ssr-plus/root/usr/share/shadowsocksr/gen_config.lua`.
Its Git blob is `e226697bced19dab2481fd920f3cad219fa0c666` and unchanged LF
SHA-256 is `58784f09dece11bd755acc99e14bac05a0d87c5dacce01aa72ca82a801a93f21`.
`tests/test_ssrplus_core_config.py` verifies both identities before executing
the complete generator with nodes committed by the real patched subscriber.
The generator is also the twelfth protected source and installed target, so
upstream generator drift or compiled-file corruption cannot bypass the gate;
the eleven previously published baseline rows remain unchanged.
It checks the final core JSON, with isolated UCI/OS/JSON bindings; it does not
launch a core, perform a protocol handshake, or alter router configuration.
Cases cover native SS Base64 credentials and explicit core selection; Trojan
gRPC, TCP, KCP and QUIC parameters; HTTP camouflage host/path defaults; finalmask
JSON; independent TLS/Reality transport Host and SNI fallback; the unchanged
VMess path; and failed subscription groups retaining old/manual nodes.
Decoded Base64 credentials carry the exact password bytes: literal percent
sequences stay literal, without guessing at another encoding layer. Outer URI
escaping is still decoded at its own boundary. The repair takes effect only when
a later subscription actually reparses the link; existing persisted values and
MD5 caches are not migrated. Recovering password content lost by an older parser
requires subscribing again and ensuring the original link is actually reparsed.

The new firstboot harness executes the actual patched init and uci-defaults in
an isolated filesystem. Missing/empty configurations must receive the reviewed
default CBI sections without invoking service cleanup; nonempty configurations
skip default installation while receiving compatible legacy migrations; missing
SS core preferences remain automatic rather than being forced to Rust.
The focused UCI executable boundary implements the hook's get/set/delete/add
and commit effects on the actual config file, followed by the real sed commands.
Final hook values feed the actual subscriber in Lua 5.1 with isolated downloads,
installed-core discovery and the real pinned, package-patched lua-neturl dependency
documented in the adjacent `lua-neturl/` fixtures. Fresh and retained absent SS preferences
remain unset; libev-only ordinary SS selects libev, while Rust+Xray WebSocket SS
keeps its Xray transport, host and path. SS credentials and transport query values
are decoded at their own boundaries exactly once; malformed scalar parameters
are rejected without publishing invalid nodes. Retained nodes, preferences, domain/IP
rules and rule-file bytes survive; failed initialization can retry. These checks
do not execute native target UCI or its package manager.
The initializer and immutable template are protected
in source and artifact checks, with installed modes0755 and0644 respectively.
The mutable active configuration is deliberately not hashed as an artifact.

For local verification, install `tests/requirements.txt` into a test environment
and run `bash tests/run_all.sh`. The updater harness executes the patched Lua
with Lupa's Lua 5.1 runtime; it explicitly skips when that optional runtime is
unavailable. On Windows, use Git Bash and Python. The three tests requiring
Linux `flock`, process-death recovery, or the installed dnsmasq parser also
explicitly skip; they still need Linux execution before firmware acceptance.
These local checks do not compile firmware or prove router/network recovery.
See [the build integration notes](../../../docs/ssrplus-compatibility.md) for
configuration and compiled-artifact verification.
