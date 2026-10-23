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
