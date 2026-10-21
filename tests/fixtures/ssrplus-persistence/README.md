# SSR Plus+ nft persistence fixture

The unchanged `2abdc9aa/ssr-rules` file comes from the firmware project's SSR
source, `fw876/helloworld`, commit
`2abdc9aa9e19607774dc9789709212b70b8607c6`:

https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/usr/bin/ssr-rules

SHA-256: `4bfcda4e9a184b2b94570de61956d7278e60d248b75bb0286f502e14b5fd4412`

`tests/test_ssrplus_persistence.py` applies the production patch in a temporary
package directory, extracts and executes the actual persistence function, and
replaces only the `nft` process boundary. The exported fixture tables contain
complete nft declarations. Tests compare every non-comment output line against
those declarations, inject CR/LF metadata, and simulate failed or partial
exports and failed atomic renames. This is not a router or kernel nft validation.

Set `SSR_PERSISTENCE_UNPATCHED=1` to reproduce failures in the original source.
No test contacts the router or modifies the original fixture.
