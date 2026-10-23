# Shared proxy core fixtures

Production recipe checks use the complete captured
`maintenance/plugins/ssrplus/upstream-v198.2/xray-core` subtree as the independent
fixture. It contains the fw876 recipe, EIP93 notes and all ten patches. Tests
remove and modify every patch, add an unexpected patch, and verify that the
production gate rejects these trees before compilation. Source hashes and the
pinned fw876 test binary are recorded in
`wrt_core/compat/proxy-cores/xray-26.10.21.json`.

`small-package-3d560925/xray-core/Makefile` is retained only as a negative fixture:
an official-only recipe cannot satisfy the fw876 source gate. Its exact Git blob
is `481e0342987bde364588e00ec716c1f23a250512`, from `kenzok8/small-package`
commit `3d5609257639ed76aaacdeffe242343d51265fea`. The original MPL-2.0 license
declaration is retained. The old official recipe upgrade patch has no production
caller.

The tests create minimal Passwall2 and Go version declarations in temporary
build trees. They validate the recipe admission boundary without downloading
OpenWrt build dependencies or cross-compiling firmware. Go >=1.27.3 and the
Passwall2 minimum version remain mandatory on every call.

The separately pinned official Xray test binaries validate common configuration
syntax only. fw876-specific protocols require the exact verified fw876 release
binary on Linux; the official binary is not a replacement for that gate.
