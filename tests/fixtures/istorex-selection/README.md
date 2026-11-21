# AX6000 iStoreX selection regression inputs

Original upstream bytes are recorded in `sources.json` with exact commits,
SHA-256 values and independently checked Git blob identities:

- [Core6003f6b8](https://github.com/immortalwrt/immortalwrt/tree/6003f6b8c3278a27712f4fdaaa8d1e5faa2b1f54): metadata generator/parser and package dump helper.
- [Packages decf9463](https://github.com/immortalwrt/packages/tree/decf94639ffd6ddd26591c190b547c6b7eea150b): GNU tar/XZ recipes and GPL license.
- [LuCI8724b54d](https://github.com/immortalwrt/luci/tree/8724b54de3a760294aedeb10a29ffba7e44cca2f): `luci.mk`.

Two byte-identical inputs are reused from the existing fixture instead of
duplicated: `../kconfig-compat/immortalwrt/include/package-defaults.mk` and
`../kconfig-compat/variants/fwknop/master/luci/luci.mk`. Their entries in
`sources.json` retain the independently checked current-core/LuCI provenance.

`test_istorex_selection.py` expands the repository's seven managed iStoreX
recipes plus real tar/XZ definitions through these helpers. It applies the
existing production metadata compatibility transformation in a temporary copy,
then evaluates generated Kconfig with kconfiglib or `KCONFIG_CONF`. Unrelated
libraries are independent leaves. Shared aarch64 is explicit; this bounded
package model does not regenerate hardware defaults or build a firmware image.

The dependency is iStoreX -> luci-app-store -> tar -> xz. Tar enables XZ support
by default. The XZ subpackage has a plain `xz-utils` dependency, requiring its
menu meta-package separately. Metadata propagates
`!PACKAGE_TAR_XZ || PACKAGE_xz-utils` to iStoreX. AX6000 previously omitted this
meta-package; RAX3000M already selected it.

Tests reproduce historical deselection and preserve current AX iStoreX, its
seven-component group, tar/XZ support and eight Docker exclusions. Other cases
preserve RAX and an explicitly disabled iStoreX. A separate private full-core
metadata reproduction with native core6003 `conf` confirmed the same AX before
and after behavior. Host firmware prerequisites were bypassed on macOS only for
that metadata exercise; the owning GitHub full build validates firmware.
