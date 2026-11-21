# 2026-11-21 构建与已选插件上游修复

## 本轮范围

按 18 个设备的实际配置组合，检查 35 个显式 `luci-app-*` 和两个主题，另检查 iStoreX
传递组件与 SSR 配套核心。来源审查截止 2026-11-21；“无新修复”只指当时所核对的来源。
原项目上游审查范围为 `ZqinKing/wrt_release@4bf1cc0...b3074c6` 的 38 个提交。

固件及 feeds 版本配套见 [来源锁](../feed-source-lock.md)。原始受管单元仍为 30 个，
主题以完整原始文件及来源锁刷新；其他必要修复沿现有适配器作用于构建副本。
显式设备、插件、LAN 10.0.0.1、双主题、五个旧 IPQ60xx pin 和京东云 Docker 排除保留。

## 已选择的修复

| 对象 | 上游身份 | 本地结果 |
| --- | --- | --- |
| 旧 VIKINGYFY / packages | [ffbc2408](https://github.com/immortalwrt/packages/commit/ffbc2408fccfb5c579363365a8971862a9718fb0) | 固定为 Rust 接口迁移前的兼容 feed，其他底座按原维护分支配套；获取精确提交后才索引。 |
| Qt5 | [6a3b5fd6](https://github.com/openwrt/video/commit/6a3b5fd6e963f41caa73ef4f691e156d467e2894) | 保留新的依赖/安装修复，并处理新引入的 linuxfb/DRM 父包循环；同时支持维护分支的真实 squeezelite 配方。 |
| fwknop / GnuPG2 | [上游问题 31215 的作者建议](https://github.com/openwrt/packages/issues/31215#issuecomment-6808924386) | 对精确审查的配方补上 `gnupg2-utils` 的必需运行时自动选择，消除传递依赖环，保留 fwknop 功能开关。建议尚未合并，本项目作为兼容修复采用。 |
| SmartDNS 下载 | [1db3543c](https://github.com/pymumu/openwrt-smartdns/commit/1db3543cfaa397cd1115b0479416f73062711a63) | 直接获取固定核心提交的 codeload 归档，按 SHA-256 校验。两种底座的原生下载器都核对了 445 个文件，并拒绝错误校验值。 |
| SmartDNS 运行 | [b6139a1](https://github.com/pymumu/smartdns/commit/b6139a199232140447aff6c4ec111c222ac84993)、[21c940e](https://github.com/pymumu/smartdns/commit/21c940edc65520849ba03544c5cf8d9cf326e680)、[1006f64](https://github.com/pymumu/smartdns/commit/1006f640d50f1e2951e13d3e740813cc76a6739e) | 按依赖顺序清理服务资源，避免退出时崩溃。重复配置主 DNS 时只写入一次同一 DHCP 选项。显式关闭过期缓存时按设置处理缓存和响应有效时间。 |
| SSR Plus | [67449c65](https://github.com/fw876/helloworld/commit/67449c659329e92d683075962555d602c98978b3)、[e825742c](https://github.com/fw876/helloworld/commit/e825742c1e9267906d5208f080fb3b65d8b300e7)、[6fbc9f56](https://github.com/fw876/helloworld/commit/6fbc9f563c9e7cd3b65061fba13ffc62666066aa) | 外部 runtime selects 仅随父包启用；所有核心获得 coreutils/timeout；保持原核心默认选择，派生 198-r3。 |
| Xray | [fa29e877](https://github.com/fw876/helloworld/commit/fa29e87710fef1c2eeb7c38bcca62996f0798ef2) | 只在 Naive 启用时精确允许 Cronet 静态库链接标志；保留 26.10.21、十份私有补丁、UPX 复用及 Go 门槛，派生 r4。 |
| OpenClash 缓存 | [2faa4fab](https://github.com/vernesong/OpenClash/commit/2faa4fabfe1c12899feb1ddc060adda3fa7f2343) | 核心退出后按原运行配置名备份最终 cache.db；超过十秒仍存活时保留旧备份，防止复制半写缓存。 |
| OpenClash DNS | [73f3abdb](https://github.com/vernesong/OpenClash/commit/73f3abdb8d4ef46ea939b1b9c730f13d3e800d5b) | 仅回移 scalar 列表、域名树匹配和 CN 分类三项修复；保持订阅/ETag 失败处理及现有防火墙行为。 |
| Argon | [稳定 v3.1.4 / c5c0873e](https://github.com/jerrykuku/luci-theme-argon/tree/c5c0873e122dc767c7ab0198c8bffc6e952b5cfb) | 完整刷新 249 个原始文件：菜单加载、CSS 缓存/下拉层级、壁纸 TLS/超时、翻译更新等；保留已有配置。 |
| Aurora | [298dbcc7](https://github.com/eamonxg/luci-theme-aurora/commit/298dbcc74ddf820923a51285fb0826d429e5d7ca) | 固定三个已合并修复后的 218 个原始文件：通知关闭、导航加载/会话缓存、登录令牌与新 LuCI 兼容。配方为 1.4.3，**并非已发布稳定 release**；配置包仍为 1.2.5。 |
| W1701K NPU | [原项目 e16d7ace](https://github.com/ZqinKing/wrt_release/commit/e16d7ace545f4795155247c8b8a6f9cdbb6ad4a9)、[devmem fe48c218](https://github.com/ZqinKing/wrt_release/commit/fe48c218) | 仅 W1701K 获取必选插件的固定来源及运行工具；其他设备不依赖该下载。不引入该提交中的 Passwall/CUPS/其他软件包。 |
| S20M Netcontrol | [rule2c / 61364846](https://github.com/rule2c/luci-app-netcontrol/commit/61364846e1188d87801f778749efc4f2a4deac43) | 固定完整提交补齐已选但缺失的插件，仅 S20M 获取；保留默认关闭，并在构建副本省去自动迁移/停用旧 timecontrol 的步骤。 |
| netfilter | [d567052b](https://github.com/ZqinKing/wrt_release/commit/d567052b09b26e5e30f2981008e1cd5e577aed8d) | 覆盖无条件 `+kmod-iptables` 配方，保留 Linux 6.12/6.18 的互斥修复。 |
| CI 环境 | [b3074c60](https://github.com/ZqinKing/wrt_release/commit/b3074c60870242df523cd171c31a5167a8e79d14) | 先 checkout 再运行受管 setup；下载失败明确退出，避免完整系统升级和 APT recommends，并检查工具。 |

## 全部已选插件清单

下表中外部直接获取入口会获取其核对时的上游修复；是否成功装载仍以实际 Linux 构建记录为准。
core/feed 所有的插件随对应已锁定的核心/LuCI/软件包来源更新，不为同一插件另外混入不配套来源。

| 插件 | 来源与处理 |
| --- | --- |
| luci-app-argon-config | 随 Argon 稳定版 3.1.4（c5c0873e）更新内嵌兼容包；设置仍由主题唯一提供，不恢复旧独立 UI。 |
| luci-app-aurora-config | 固定 a5299ce0 / 1.2.5；上游无新提交，保留已有配置保护。 |
| luci-app-homeproxy | 上游仍为 fadaa676，与原锁一致；已有 sing-box/ACL/缓存补丁保留。 |
| luci-app-istorex | small-package fca4816303d6157379efc3842310621cc9095963，0.6.6 — 后续仅a7990a0b01ad72954a2a6968e27e09626f421baa加空PKG_RELEASE，未发现需单独修复的运行变更。 |
| luci-app-oaf | small-package fca4816303d6157379efc3842310621cc9095963，OAF7/fwx既有schema — **所需安全修复已回移**0892bf4f；之后仅oaf_version7.0.1→7.0.2(c24c255a672fb39b4627cfaddbff0820e60a7699)。不回退ACL/默认关闭/生命周期/runtime guard。 |
| luci-app-openclash | 外部 small-package 来源仍为 0.48.002；新增两项回移见上表，完整保护文件由 14 增至 15。 |
| luci-app-ssr-plus | fw876 v198.2 原始输入不变；回移父包选择及通用 timeout 依赖，派生 198-r3。 |
| luci-app-adguardhome | ZqinKing 上游仍为 36108202，与审查快照一致，无新增运行修复；原直接获取与兼容处理保留。 |
| luci-app-smartdns | 保留包装来源 cdf0de1、核心 136c0c2 和固定 WebUI。回移核心归档下载及适用的运行修复，编译器引号由现有 TARGET_CC_NOCACHE 处理。 |
| luci-app-diskman | [lisaac/luci-app-diskman c20df1d4f40d86e32fd919f33122b2a48f8a99b4](https://github.com/lisaac/luci-app-diskman/commit/c20df1d4f40d86e32fd919f33122b2a48f8a99b4)，2026-05-19 — applications/luci-app-diskman，0.2.13-r1；原逻辑已克隆最新并改ntfs3，**无新回移需要**。 |
| luci-app-dockerman | [lisaac/luci-app-dockerman 6fd9937954e0b080bf07967182d714ea21fe7eb1](https://github.com/lisaac/luci-app-dockerman/commit/6fd9937954e0b080bf07967182d714ea21fe7eb1)，2026-09-21 — applications/luci-app-dockerman，v0.5.26；已包含932c165256f39acfb83da3f4e1bb4d5a9da95b5e events-controller修复。默认克隆机制已包括；保持Docker选择gate，京东云不恢复。 |
| luci-app-quickfile | [sbwml/luci-app-quickfile ef2ca5d16ad1156539930d8763c3069f6ac4eb12](https://github.com/sbwml/luci-app-quickfile/commit/ef2ca5d16ad1156539930d8763c3069f6ac4eb12)，2026-10-25 — 默认克隆已到2.0.9，Rust源码/安装contract与guard一致。新archive SHA256 f73204997e3a572f05e303be1cfb7bb82a03bd3a2a5052a9b9d3217a00233f3b；仅静态查recipe，未重新下载archive或交叉编译。文档2.0.8是旧核验身份，不表示实际固定。 |
| luci-app-emmc-health | [adminchenyu/eMMC-Health f17cbea85ebcb9071b659ac7bafd2c56a9de7b3c](https://github.com/adminchenyu/eMMC-Health/commit/f17cbea85ebcb9071b659ac7bafd2c56a9de7b3c)，2026-05-13 — main根包1.1.3-r1；现有直接clone已含，**无新回移**。上游仍+luci-js-deps，保留现有特定依赖删除。 |
| luci-app-athena-led | [NONGFAH/luci-app-athena-led f8eeb3119008ac0e429fc642c125512f9253ec1b](https://github.com/NONGFAH/luci-app-athena-led/commit/f8eeb3119008ac0e429fc642c125512f9253ec1b)，2025-02-14 — 根包0.0.7；现有clone已含旧httpGet修复。两JDCloud =m，**无新回移**。 |
| luci-app-partexp | [sirpdboy/luci-app-partexp ef79d6b8c7f1e4d476be55dabb4c34d5b7f334c5](https://github.com/sirpdboy/luci-app-partexp/commit/ef79d6b8c7f1e4d476be55dabb4c34d5b7f334c5)，2026-10-29 — custom_feed克隆main/luci-app-partexp；已含[8b6659917d32967cc04afcf9f20bcfe64c3e6b5c](https://github.com/sirpdboy/luci-app-partexp/commit/8b6659917d32967cc04afcf9f20bcfe64c3e6b5c) overlay静默不复制修复，**不用重复回移**。 |
| luci-app-bandix | [timsaya/luci-app-bandix 108369b8da05f01296a3ed0210a2ab60809712e5](https://github.com/timsaya/luci-app-bandix/commit/108369b8da05f01296a3ed0210a2ab60809712e5)，2026-10-27 — main/luci-app-bandix 0.12.12-r5，核心[0760d1f5b52d1a2317dfd171ab00fe6543a9a0c4](https://github.com/timsaya/openwrt-bandix/commit/0760d1f5b52d1a2317dfd171ab00fe6543a9a0c4)0.12.12-r1；现有feed机制已含WiFi按频率辨频段f06ee5cf与checkbox对齐2cb887a1修复，主代理新feed lock固定同一head；仅x64选择。 |
| luci-app-amlogic | kenzok8/small-package 当前main [88b426ba5cf70ae82a616c60d1eb6c6a8b8c252b](https://github.com/kenzok8/small-package/commit/88b426ba5cf70ae82a616c60d1eb6c6a8b8c252b)；该目录最近更新8de766779813b5a19bf88ef4d31b2863651035bf(11月20) — custom_feed已从滚动small-package获取；仅N1选择；**无需对原锁回移**（它不在30受管单元中）。未在本审查做Amlogic刷机/设备兼容升级。 |
| luci-app-autoreboot | 所选LuCI/core feed；保留选择，随对应feed固定，不新增来源。 |
| luci-app-vlmcsd | 所选LuCI/core feed；部分目标明确n，保留。 |
| luci-app-samba4 | 所选LuCI/core feed与packages/samba4；保留选择；没有本轮独立回移证据。 |
| luci-app-statistics | 所选LuCI/feed与collectd；京东云/NN6000V2；随feed一致性处理。 |
| luci-app-wifischedule | 所选LuCI/feed；京东云/NN6000V2；保留选择。 |
| luci-app-sqm | 所选LuCI/routing或NSS对应来源；遵守设备n和libwrt NSS源，不移植其它设备的版本。 |
| luci-app-cpufreq | 仅redmi_ax5；核心/feed-owned，保持来源。 |
| luci-app-ttyd | 全设备compile_base选择；核心/feed-owned，不能漏选。 |
| luci-app-upnp | 全设备compile_base选择；miniupnpd核心兼容沿用已审查修复，不整recipe滚动替换。 |
| luci-app-eqos-mtk | 仅S20M；padavanonly固定核心/24.10 feed，避免混入主线不同实现。 |
| luci-app-turboacc-mtk | 仅S20M；同上，设备平台功能。 |
| luci-app-wrtbwmon | 仅S20M；同上，保留配置。 |
| luci-app-netcontrol | S20M 原来已选择，但实际固定核心、24.10 LuCI 与 small-package 都没有配方。现从原作者 rule2c/luci-app-netcontrol 固定 `61364846e1188d87801f778749efc4f2a4deac43` 获取 1.0.0-r1；运行依赖 nftables/conntrack，保留默认关闭及原配置选择。构建副本只省去旧 timecontrol 自动迁移，不自动复制其配置、配额或停用旧服务。 |
| luci-app-airoha-flowsense | W1701K core `ZqinKing/immortalwrt@796897b5417537c0b10ee9ec31166ac5901bc33b`，package/luci-app-airoha-flowsense/Makefile blobac9a10a1b6b59923c6e8758605a88b240d2cff9e，已验证完整tree存在。 |
| luci-app-mlo | 同一W1701K core package/luci-app-mlo/Makefile blob0536311214025c1c6e6328ba4ae054e44b8e5b74，已存在。 |
| luci-app-w1700k-fancontrol | 同一core package/luci-app-w1700k-fancontrol/Makefile blob4f9cf7ae8157d7a7c99018f554d0e6690c0742bf，已存在。 |
| luci-app-wifi7 | 同一core package/luci-app-wifi7/Makefile blobefbc1964870bad1d7232ab6615180f82e88cc9ce，已存在。 |
| luci-app-airoha-npu | 已补齐 rchen14b 来源，固定 14521b8414da1e98517a295d8ec267087c7dde8e；移除嵌套重复包、修正 luci.mk 引用，W1701K 补 BusyBox devmem。 |

## 传递组件及未采纳变更

- iStoreX 的 quickstart、luci-app-quickstart、luci-app-store、taskd、luci-lib-taskd、luci-lib-xterm 一并核对。
  后四个没有新提交；原 Quickstart HTTP/安装参数及 OAF 数据包安全修复已于 10 月 31 日回移。
  新 Quickstart 0.17.1 RC 为前后端替换，原项目 Netwiz/Vantage、其他新设备迁移不属于必要修复。
- fw876 的 ChinaDNS-NG、MosDNS、Shadowsocks Rust/Libev、simple-obfs、dns2tcp、dns2socks、
  ipt2socks、UPX 等受管子目录相对原锁没有变化。
- fw876 最新 dev 仍存在 Hysteria2 realm 的未定义 `node` 引用，不整体切换。
- sing-box 最新 1.15 alpha 的 IPv6 DNS/URLTest 改动需要独立核心升级验证，保持 1.14.3。
- OpenClash 全局网桥开关和 TPROXY 失败直连策略会改变已有网络行为，未整批移植。
- miniupnpd 已有精确修复，不用滚动 25.12 recipe 覆盖；SmartDNS 核心包装 pin 与 WebUI 兼容保持。
- MosDNS LuCI、Nikki、Lucky、Easytier 和 timecontrol 没有被本轮额外选入。
- 构建输入锁覆盖固件与原生 feeds；原有直接 clone 的外部插件入口、Go 工具链和下载归档仍各自维护，
  不把本轮描述为全部外部内容离线化。受管内容/兼容输入漂移依然明确拒绝。
- Netcontrol 原始输入及 fixture 完整保留；[构建适配器](../../wrt_core/netcontrol_compat.py)
  仅接受原样或完整派生的首次启动脚本，单文件原子写入并保留权限。已有 timecontrol 的迁移需另行决定。
  外部稀疏导入在目标文件系统暂存，先检查全部请求目录，再保留旧副本并发布；移动/清理失败明确退出，
  部分发布会回滚，失败不进入 feed 索引。

## 验证状态

源码身份、受管 30 单元校验、固定输入行为回归与各修复先失败后通过的证据已分别记录。
本机 macOS 无 Linux `/proc`、网络命名空间或目标交叉工具链，Linux 专属检查由精确提交 CI 验证。

- `229ee8b` 的 [Linux 全量回归 44871821569](https://github.com/BlackHu-art/openwrt_release/actions/runs/44871821569)
  通过：55 组 Python 测试共 787 项（786 通过、1 项 Windows 专属测试跳过），以及全部 shell 检查。
  包括真实 Xray/Mihomo、原生 Kconfig，以及网络命名空间内实际 dnsmasq/nft、9 种 IPv6 模式检查。
- 独立整分支审查及后续复审完成。发现的本地设备切换、静默索引漏报、SSR 写入回滚、
  配置产物隐藏文件、配置检查缓存和 NPU 下载范围问题均已补回归；清理失败会在重置源码前退出。
- `42abb91` 的六种核心身份来源准备/defconfig 全部通过，已下载并核对配置产物：完整保留 `.config`、
  `.config.requested` 和来源锁，原请求的 LuCI 插件均保留，京东云 Docker 排除仍成立。

| 目标 | 配置验证 | 保留的 LuCI 应用数 |
| --- | --- | --- |
| JDCloud ImmortalWrt / 3fd1 | [44870591385](https://github.com/BlackHu-art/openwrt_release/actions/runs/44870591385) | 24 |
| JDCloud LiBwrt / 25.12 | [44870593970](https://github.com/BlackHu-art/openwrt_release/actions/runs/44870593970) | 23 |
| Redmi AX6 / f9b0 | [44870596745](https://github.com/BlackHu-art/openwrt_release/actions/runs/44870596745) | 14 |
| x64 / master | [44870599779](https://github.com/BlackHu-art/openwrt_release/actions/runs/44870599779) | 19 |
| W1701K / master | [44870602436](https://github.com/BlackHu-art/openwrt_release/actions/runs/44870602436) | 19 |
| S20M / 24.10 | [44870605379](https://github.com/BlackHu-art/openwrt_release/actions/runs/44870605379) | 15 |

随后仅补稀疏导入中断恢复及 Netcontrol 旧配置保护，`229ee8b` 的最终 Linux 回归已通过；
[S20M 配置复核 44871847853](https://github.com/BlackHu-art/openwrt_release/actions/runs/44871847853)
也已通过，下载产物确认 15 个应用保留、Netcontrol 选中且来源锁不变，日志确认独立首次启动适配已执行。
两个京东云代表目标的首次完整流程均在 SmartDNS 核心归档下载处失败：
[ImmortalWrt 44871843193](https://github.com/BlackHu-art/openwrt_release/actions/runs/44871843193)、
[LiBwrt 44871845589](https://github.com/BlackHu-art/openwrt_release/actions/runs/44871845589)。
两者均为同一固定提交重新打包后的校验值与旧配方不符。新方案已通过真实下载和内容核对，
原因、固定归档身份及验证方式见[下载兼容说明](../source-download-compat.md)。
实机未验证，不将来源/配置检查等同于固件编译成功。
