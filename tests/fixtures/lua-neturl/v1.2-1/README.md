# Public lua-neturl subscription dependency

The actual Lua subscription harness loads this dependency instead of a Python
URL-parser substitute. These are public upstream inputs; no router files,
subscription data, credentials or private backups are used.

`url.lua` and `LICENSE.txt` are verbatim LF files from golgote/neturl commit
`fd0df85f44b545d91c2840dc4339abb3656d031d`, the commit addressed by annotated
tag `v1.2-1` (tag object `2dccf173aac8e71b6207285b8594da554e5deead`):

- <https://raw.githubusercontent.com/golgote/neturl/fd0df85f44b545d91c2840dc4339abb3656d031d/lib/net/url.lua>
- <https://raw.githubusercontent.com/golgote/neturl/fd0df85f44b545d91c2840dc4339abb3656d031d/LICENSE.txt>

The package recipe uses `neturl-1.2-1` with source archive SHA256
`fc4ea1b114125ae821bef385936cd12429485204576e77b6283692bd0cc9b1ab`.
`010-userinfo-regex.patch` is the exact public ImmortalWrt packaging patch from
commit `383b517a1d1df74daada5e5652a0dc75e8e102b3`:
<https://github.com/immortalwrt/packages/blob/383b517a1d1df74daada5e5652a0dc75e8e102b3/lang/lua/lua-neturl/patches/010-userinfo-regex.patch>.
Its punctuation and scheme matching changes also occur in helloworld's copy.
The harness checks the inputs before applying this patch in a temporary tree.

| File | Git blob | SHA256 |
| --- | --- | --- |
| `url.lua` | `71d253438b3affa8a5e814ed080883b6fe670284` | `29f0914ee0f17df6a9cc90f8feb014dbd5075e4dc908ab77df6f610b02244d85` |
| `010-userinfo-regex.patch` | `9dbd91ccfc173159677f352c151d35caf272cadc` | `a11baa581ad2abbd47948d3150d2941e9c91874e7a25ed77c11317a120b3798c` |
| `LICENSE.txt` | `e3983ef2e54c7096be68d67fb9ac9ebdd956078d` | `07bfcfe585f4e8264630b1852a9bfcbd4b3cf3b393571de787c8ee6d3e97e5e7` |

The MIT license is retained in `LICENSE.txt`. Real neturl decodes query `%HH`
escapes once and treats raw query `+` as space; userinfo is a separate
credentials boundary. Regression expectations distinguish these semantics.
