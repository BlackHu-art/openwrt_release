# OpenClash 0.48.002 regression fixtures

These are complete, byte-identical files from
[kenzok8/small-package 549bdea5056436c9c2f9b8ad6eb9297318bbd6a1](https://github.com/kenzok8/small-package/tree/549bdea5056436c9c2f9b8ad6eb9297318bbd6a1/luci-app-openclash).
The package Makefile identifies version `0.48.002`.
The files were rechecked against mirror commit
[`3d5609257639ed76aaacdeffe242343d51265fea`](https://github.com/kenzok8/small-package/tree/3d5609257639ed76aaacdeffe242343d51265fea/luci-app-openclash)
and official [`e553e82e01c697aefbe1555261a503f425e00ccd`](https://github.com/vernesong/OpenClash/tree/e553e82e01c697aefbe1555261a503f425e00ccd/luci-app-openclash).

| Fixture | Package-relative source | Git blob |
| --- | --- | --- |
| `YAML.rb` | `root/usr/share/openclash/YAML.rb` | `1addd1d1cbf09de4ecbec4593a2ba3af25c20e27` |
| `switch_dashboard.htm` | `luasrc/view/openclash/switch_dashboard.htm` | `735d7fbefd51bf0e6ba716a09a630d463901138c` |
| `openclash.init` | `root/etc/init.d/openclash` | `7bc7e7568c74c197668ddf6372c7013de2baf152` |
| `controller-openclash.lua` | `luasrc/controller/openclash.lua` | `f04546b358bdcb7e8c98a93b5980eec30bbb6304` |
| `config-subscribe-edit.lua` | `luasrc/model/cbi/openclash/config-subscribe-edit.lua` | `609f2f3804639877e716805dc4fd5bd5a9b29a76` |
| `luci-openclash.lua` | `luasrc/openclash.lua` | `72f61f4f81507f68a6e57aacb12a51de78a4342c` |
| `config_edit.js` | `root/www/luci-static/resources/openclash/js/config_edit.js` | `07b04ca809cfbd4b3a14eaa1c639b31eb6131a3c` |
| `yml_change.sh` | `root/usr/share/openclash/yml_change.sh` | `abbce9f50b25f5459611f7d32940a018caf40ecd` |
| `settings.lua` | `luasrc/model/cbi/openclash/settings.lua` | `047b497980b53b159f95a3f38d41106097ee0f16` |

OpenClash is Copyright (c) 2019-2026 vernesong, MIT; see
[COPYING.OpenClash](../../plugin-runtime/COPYING.OpenClash).

The regression runner applies the shared production fixer before executing the
template's JavaScript and the complete Ruby module source, supplied as UTF-8
standard input to Ruby with the original filename retained as eval metadata.
Its DOM/XHR doubles isolate
the browser and HTTP boundaries; no service, device, network or host routing is
used. Set `PLUGIN_FIX_MODE=original` to reproduce the unfixed dashboard behavior.
Ruby tests report a skip when Ruby is unavailable; CI can require the runtime with
`OPENCLASH_REQUIRE_RUBY=1` and Ruby 3.4 or later with `OPENCLASH_REQUIRE_RUBY34=1`.

`test_openclash_tun_stack.py` executes the production-patched shell selection and
the complete Ruby generation body. Its platform adapter carries YAML/cache bytes
inline for Windows native-file-view isolation and supplies the OpenWrt UCI and
network-interface boundaries. The assertions inspect the actual generated TUN
map. Set `MIHOMO_OLD_TEST_BIN` and `MIHOMO_NEW_TEST_BIN` to official 1.19.30 and
1.19.33 binaries for generated-config `-t -config` checks and startup gating.
Startup checks execute the production init functions and isolate procd/UCI;
they do not start a listener or operate a router.

CI requires these two real cores with `OPENCLASH_REQUIRE_MIHOMO=1`; missing
executables fail import instead of silently skipping the capability checks.
`tests/fetch_mihomo_test_cores.py` explicitly downloads pinned official amd64-v1
assets; their archive SHA-256 values match the official release API digests:

| Release | Linux `.gz` SHA-256 | Windows `.zip` SHA-256 |
| --- | --- | --- |
| [v1.19.30](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.30) | `cbe553d0319a414bd3a372c5976a252155b2c4882b66bce88a4d6bba9571a553` | `8b81fe2c5cd04ca6deb61eec6075150b44cc5ad13ab867750642e2422f7c1278` |
| [v1.19.33](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.33) | `8ec92e7b2fdc6b853ba00156bab7e4e965c8b0d843b8c4ac8ab98795f02ad524` | `fb0b960eff568459502d4ebe53e9cca203053d86ec9024fe935f19615d74d9aa` |

These binaries are validation inputs only. Firmware runtime core selection and
saved OpenClash configuration remain under the plugin/user's control.
