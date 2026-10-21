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
`190-r4`. The build gate reverses complete patches only in
an isolated copy, then compares the original Git blobs before writing any feed
source. Unknown changes outside patch context, incomplete patches, a missing
runtime source, and a changed installed runtime helper are rejected. Tests also
exercise the actual pre-install stage order and its explicit failure propagation.
The installed `root/usr/share/shadowsocksr/ssrp-runtime.sh` must be byte-identical
to `wrt_core/compat/ssrplus/runtime.sh`.

The full nine-file baseline is recorded in
`wrt_core/compat/ssrplus/source-files.tsv`; the ordered nine-patch repair set is
`wrt_core/compat/ssrplus/patches.list`. Additional unchanged fixtures cover
`subscribe.lua`, `ssr-monitor`, `ssr-switch`, and `ssrplusupdate.sh`; the reviewed
`ssr-rules` fixture is in the adjacent `ssrplus-persistence/` directory.

For local verification, install `tests/requirements.txt` into a test environment
and run `bash tests/run_all.sh`. The updater harness executes the patched Lua
with Lupa's Lua 5.1 runtime; it explicitly skips when that optional runtime is
unavailable. On Windows, use Git Bash and Python. The three tests requiring
Linux `flock`, process-death recovery, or the installed dnsmasq parser also
explicitly skip; they still need Linux execution before firmware acceptance.
These local checks do not compile firmware or prove router/network recovery.
See [the build integration notes](../../../docs/ssrplus-compatibility.md) for
configuration and compiled-artifact verification.
