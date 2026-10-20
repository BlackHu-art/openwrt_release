# Plugin runtime regression fixtures

- `adguard-updater.sh` and `AdGuardHome.lua` are unchanged files from
  [ZqinKing/luci-app-adguardhome 36108202f326f65ab6f5a85d15adcba6538f8e8b](https://github.com/ZqinKing/luci-app-adguardhome/tree/36108202f326f65ab6f5a85d15adcba6538f8e8b):
  `root/usr/share/AdGuardHome/update_core.sh` and
  `luasrc/controller/AdGuardHome.lua`. The package's Makefile identifies
  Copyright (C) 2018-2019 Lienol and Apache-2.0; see `COPYING.AdGuardHome`.
- `openclash_curl.sh` contains the unchanged `verify_sha256_checksum` function.
  `openclash.init` contains three unchanged source excerpts, separated by
  comments: the nft and ipset startup-set blocks, and the WAN address discovery
  lines. They come from
  [kenzok8/small-package 549bdea5056436c9c2f9b8ad6eb9297318bbd6a1](https://github.com/kenzok8/small-package/tree/549bdea5056436c9c2f9b8ad6eb9297318bbd6a1/luci-app-openclash),
  `root/usr/share/openclash/openclash_curl.sh` and `root/etc/init.d/openclash`.
  OpenClash is Copyright (c) 2019-2026 vernesong, MIT; see `COPYING.OpenClash`.

The test applies the production patches, executes the extracted update/checksum
and startup-set code with external commands replaced, and verifies idempotence
and rejection of incompatible sources before any partial write. The fixtures do
not start services, download cores, or modify host routing. `PLUGIN_FIX_MODE=original`
can reproduce the downgrade and checksum failures without applying patches.
OpenClash is tested as an untracked subdirectory of the parent source repository,
matching sparse feed transfer, while AdGuard Home has its own cloned repository.
This catches `git apply` silently skipping package-relative paths in a parent repo.

Separate live verification on 2026-10-20 fetched both complete OpenClash files
and both AdGuard Home files again, applied the same helpers twice, and checked
complete shell-file syntax. The Lua log guard is source/patch checked; the
LuCI controller is not executed in these Bash tests.
