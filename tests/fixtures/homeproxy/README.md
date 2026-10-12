# HomeProxy compatibility fixture

`Makefile` and `generate_client.uc` are unmodified files from
[`immortalwrt/homeproxy` commit `98a6ad9`](https://github.com/immortalwrt/homeproxy/commit/98a6ad9):

- [Makefile](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/Makefile)
- [generate_client.uc](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/root/etc/homeproxy/scripts/generate_client.uc)

Both retain their upstream `SPDX-License-Identifier: GPL-2.0-only` and copyright
notices. They are distributed under GPL version 2 only. `COPYING` is the
unmodified [upstream license text](https://raw.githubusercontent.com/immortalwrt/homeproxy/98a6ad9/LICENSE)
and applies to these vendored files rather than the parent repository's GPL v3
license. `.gitattributes` preserves LF line endings for reproducible Git blobs.

The generator's Git blob is `890d23b0642a6b748805513c953782026f59d25e`.
Applying only upstream commit
[`7c6ded7b99953c7148f3f4a2edf69a592a4f424e`](https://github.com/immortalwrt/homeproxy/commit/7c6ded7b99953c7148f3f4a2edf69a592a4f424e)
must produce blob `1fbe424744bd48f1c5d2af6a571d77a6697825d8`.
This independent expected result excludes the second PR #673 commit's VPN
interface-selection change. The test derives additional dependency and drift
cases from these files in a temporary directory; it requires no network access.
