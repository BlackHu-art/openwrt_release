# Quickstart runtime fixture

`nixio-util.lua` is the unmodified LuCI `nixio.util` from
[`openwrt/luci@1bb4822dca6113f73e3bc89e2acf15935e6f8e92`](https://github.com/openwrt/luci/blob/1bb4822dca6113f73e3bc89e2acf15935e6f8e92/libs/luci-lib-nixio/root/usr/lib/lua/nixio/util.lua).
Its SHA-256 is `1e9a1693ac0b4cb3b4d3e6adaa77279da1dc247182cc6bf2d1f731b30dcfdb9b`.
The Lua 5.1 regression loads this real extension over controlled socket read/write
primitives. This verifies short writes and nixio's empty/short-string EOF behavior
without connecting to a router or starting a service. It is not firmware input.
