# HomeProxy compatibility fixture

The following are unmodified files from
[`immortalwrt/homeproxy` commit `98a6ad9`](https://github.com/immortalwrt/homeproxy/commit/98a6ad9):

- [Makefile](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/Makefile)
- [generate_client.uc](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/root/etc/homeproxy/scripts/generate_client.uc)
- [client.js](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/htdocs/luci-static/resources/view/homeproxy/client.js)
- [homeproxy.init](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/root/etc/init.d/homeproxy) (renamed locally)
- [luci.homeproxy](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/root/usr/share/rpcd/ucode/luci.homeproxy)

These files retain their upstream `SPDX-License-Identifier: GPL-2.0-only` and copyright
notices. They are distributed under GPL version 2 only. `COPYING` is the
unmodified [upstream license text](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/LICENSE)
and applies to these vendored files rather than the parent repository's GPL v3
license. `.gitattributes` preserves LF line endings for reproducible Git blobs.

The generator's Git blob is `890d23b0642a6b748805513c953782026f59d25e`.
Applying only upstream commit
[`7c6ded7b99953c7148f3f4a2edf69a592a4f424e`](https://github.com/immortalwrt/homeproxy/commit/7c6ded7b99953c7148f3f4a2edf69a592a4f424e)
must produce blob `1fbe424744bd48f1c5d2af6a571d77a6697825d8`.
The build additionally applies these unchanged upstream commit patches:

- [PR #641: 1a32fca68ecddf129f7a29e254b6cfdfc3cb3d84](https://github.com/immortalwrt/homeproxy/commit/1a32fca68ecddf129f7a29e254b6cfdfc3cb3d84)
- [PR #672: 10f4244d2e3775b29207c180c3adca1257e1f79f](https://github.com/immortalwrt/homeproxy/commit/10f4244d2e3775b29207c180c3adca1257e1f79f)

`patched-blobs.txt` records the six resulting file blobs from the separately
reviewed upstream source with LF line endings. The combined generator blob is
`c216f07507a4c47d090e5a0ca86c7d58551be096`. This excludes the second PR #673
commit's VPN interface-selection change. Tests check byte identity, repeated
application, every already-applied subset, dependencies, incompatible source,
missing/partial patches, and clone/stage failure propagation in temporary
directories without network access. They do not validate live LuCI, ucode,
dnsmasq, nftables, TUN behavior, or feature-cache runtime behavior on a router.
