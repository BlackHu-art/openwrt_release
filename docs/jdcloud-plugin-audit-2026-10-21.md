# 京东云 IPQ60xx 插件与上游修复检查

> 历史资料：本文保留检查当时的事实与建议。Passwall1 先前已移除，Passwall2 的源码和构建集成也于 2026-10-24 本轮移除；当前方案见 [fw876 集成说明](fw876-core-migration.md)。

检查时间：2026-10-20 至 2026-10-21。基线：本仓库 `f3e4bac`，设备
`jdcloud_ipq60xx_immwrt`，固定源码
`VIKINGYFY/immortalwrt@3fd1e27a511851b41cf082b067b60099e8e026c4`。

范围是设备配置、`compile_base.config`、`nss`、`proxy` 片段合并后明确选择的
26 个 LuCI 应用、主题、协议包，以及相关代理核心、NSS、Samba4 编译依赖。
对照的是 [10 月 17 日已发布固件清单](https://github.com/BlackHu-art/openwrt_release/releases/download/jdcloud_ipq60xx_immwrt_26.10.17_19.52.37/immortalwrt-qualcommax-ipq60xx.manifest)
和检查时的上游源码。公共 manifest 不等于每个机型的独立 rootfs 清单。
这是构建接入、依赖和已知上游修复检查，不代表所有插件代码均无缺陷。

## 已接入本地构建的修复

| 项目 | 确认的问题 | 本次处理 |
| --- | --- | --- |
| Passwall2、SSR Plus、分区扩容 | 配置为 `y`，但 custom_feed 未导入；SSR Plus 还在清理阶段被移除。发布公共清单也没有这三个包 | 分别从官方 `Openwrt-Passwall/openwrt-passwall2/main`、`fw876/helloworld/master`、`sirpdboy/luci-app-partexp/main` 导入，加入安装前后目录检查 |
| 配置生成 | `make defconfig` 可静默丢弃缺少源码或依赖不满足的已选插件 | 保存 `.config.requested`，比较解析后的 `.config`；明确选择的 LuCI 应用、主题、协议包丢失或从 `y` 降为 `m` 时停止编译，列出包名。遵循配置覆盖顺序，允许 `m` 升为 `y`，排除 `_INCLUDE_` 等功能开关 |
| miniupnpd / UPnP | 上游 `e765fb8` 已刷新补丁，原兼容检查会拒绝新的 040 补丁，造成上次远程构建失败 | 接受经过校验的官方刷新版本，完整保留官方补丁；保留旧版本修复路径和未知内容拒绝机制 |
| libffi / Samba4 | packages 的 `70ac3a8440` 删除了 libffi，固定 NSS 主源码却尚未包含它；Samba4 → `python3/host` → `libffi/host` 的编译依赖因此断开 | 仅在 package 和 feeds 中均无 libffi recipe 时，恢复迁移前官方 3.4.7 recipe；已有上游 recipe 时不覆盖 |
| AdGuard Home | 自动更新只比较“是否相等”，本地较新版本可能降级；更新日志文件尚不存在时 Lua 控制器直接解引用空文件句柄 | 按数字版本比较，只自动升级；保留显式强制更新。日志读取增加不存在判断，保留当前 fork 的 nftables 重定向实现 |
| HomeProxy | 重复启动或旧的异常停止可留下重复策略规则；清理使用了不存在的 LAN 链名称 | 配置的 mark/table 对应规则在启动、停止时清理全部旧副本，路由改用 replace；修正 LAN 链名。保留当前接口选择和其他三个兼容补丁 |
| OpenClash | 非 PPPoE WAN 子网要等 watchdog 才补入绕过集合；下载校验把文件名当作正则，可能匹配错误条目 | 回移启动时填充 WAN 子网和文件名按字面匹配两处修复，继续使用稳定版 0.48.002 |
| 补丁接入 | 稀疏导入的包没有独立 `.git`，在父仓库子目录直接 `git apply` 可能静默跳过包内文件 | 明确计算仓库根目录和包前缀；按真实嵌套目录结构验证补丁应用、重复应用和漂移拒绝 |

修复来源：

- [miniupnpd 官方补丁刷新 e765fb8](https://github.com/immortalwrt/packages/commit/e765fb8870)。
- [libffi 移入主源码 70ac3a8440](https://github.com/immortalwrt/packages/commit/70ac3a8440)；
  [恢复的原始 recipe](https://github.com/immortalwrt/packages/blob/3b7cdf03a6f22e91ae485e1ffdda1062da7a3431/libs/libffi/Makefile)。
- AdGuard Home：[版本比较修复 b86a36e](https://github.com/kenzok78/luci-app-adguardhome/commit/b86a36ec2fc89adf3fa9dd015dd769b4d8f7d129)、
  [日志文件判断 6aad9ba](https://github.com/kenzok78/luci-app-adguardhome/commit/6aad9ba81aed80adf492c06e92aa1c74f18a45f1)。
  以小补丁适配当前 ZqinKing fork，不整包替换。
- HomeProxy：[PR #644](https://github.com/immortalwrt/homeproxy/pull/644) **已关闭、未合并**。
  独立核实问题后适配，额外处理已有多条重复规则；不是宣称官方已合并。
- OpenClash：[WAN 子网 271c263](https://github.com/vernesong/OpenClash/commit/271c263967663a8ed34c881416205391c7582a46)、
  [下载工具修复 4015008](https://github.com/vernesong/OpenClash/commit/4015008110e8a40b41c416677c0e7224635d9379)。
  后者仅回移校验文件名部分，未引入整个 ETag 重写。

## 26 个已选插件逐项结论

表中版本是已有发布清单的版本，源码提交是本次查询结果；不能据此宣称新固件已生成。

| 已选插件 | 已发布版本或源码来源 | 评估与处理 |
| --- | --- | --- |
| AdGuard Home | LuCI `3610820`，ZqinKing fork | 接入上述两项修复；`INCLUDE_binary=n`，实际路由器内核版本不能从此清单推断 |
| HomeProxy | `fadaa676`，官方 master | 已有 sing-box 1.14、ACL 域名、feature-cache 修复；追加策略规则和链清理修复 |
| OpenClash | 0.48.002，kenzok8 镜像稳定源码 | 追加两项小修复；不整包切 dev，也不强制替换路由器上的 Mihomo |
| Passwall | 26.10.16-r2；构建直接取官方 main | 官方 `93669b0072` 已含 `ae258e4da4` 的启动返回值 / ready.lock 修复，现有拉取流程会自动获取，无需重复本地补丁 |
| Passwall2 | 原发布公共清单缺失 | 补齐官方 main 源码，检查时 `300ea00e`、26.10.20；包含启动 ready.lock 和订阅节点更新修复 |
| SSR Plus | 原发布公共清单缺失 | 补齐官方 helloworld master；检查到 `2abdc9aa`，LuCI recipe 190-r3。采用官方源码，不以聚合源自定义版本号更大作为替换依据；SSR check/local/redir/server 由现有核心 recipe 提供 |
| 分区扩容 partexp | 原发布公共清单缺失 | 补齐官方 `236187cf`，2.0.5；带磁盘显示列表修复。检查默认脚本仅注册权限/刷新 RPC，无自动分区扩容操作 |
| Samba4 | LuCI `17f97c0`，ImmortalWrt feeds | 补齐 libffi 主源码迁移兼容；没有更换 Samba 服务配置 |
| UPnP | LuCI `17f97c0`，miniupnpd 2.3.11 | 合入已核实的补丁刷新兼容，保留已有租期调整 |
| Argon 主题 | 3.0.0-r20261016；官方 `915602d2` | 现有流程会取得最新界面修复；完整检查新源码仍有集成配置标记与兼容包 |
| Argon 配置 | 3.0.0-r20261016 | 保留之前的包文件冲突修复，使用主题自带兼容包，不再重复安装旧独立配置包 |
| Aurora 主题 | 1.4.0；官方 `84c27b66` | 已使用官方来源，最新发布对应修复可由现有流程获取，无额外回移 |
| Aurora 配置 | 1.2.5；官方 `a5299ce0` | 同上 |
| SmartDNS | UI 1.2026.48.2，核心 1.2025.47 | 确认 UI 与核心代际不一致，见下方暂缓项；本次保留现有核心与 DNS 默认配置 |
| QuickFile | LuCI 1.0.0；官方 `13f1a61d` 的程序版本 2.0.8 | 当前脚本直接拉取官方源码，并选择 JDCloud 的 aarch64 二进制；未发现需要额外回移的已核实修复 |
| Diskman | 0.2.13；官方 `c20df1d4` | 已接官方磁盘处理更新，并保留当前 ntfs3 适配 |
| eMMC Health | 1.1.3；官方 `f17cbea8` | 已接最新版；保留移除旧 `luci-js-deps` 依赖的兼容处理 |
| Athena LED | NONGFAH `f8eeb311` | 按 RE-CS-02 的单机型包列表加入；全局为 `m`，公共 manifest 缺失不能解释为漏编 |
| iStoreX | 0.6.6-r1；kenzok8 指定路径 | 路径最新同步 `23b28b06`；来源已接入，本次不替换商店配置 |
| OAF | 7.0-r1；kenzok8 指定路径 | 路径最新同步 `fa997d50`；保留 open-app-filter 和现有默认配置适配 |
| 自动重启 autoreboot | ImmortalWrt LuCI feed | 正常导入；近期已核查提交中没有需要单独回移到本项目的专用修复 |
| 无线定时 wifischedule | ImmortalWrt LuCI feed | 同上 |
| 统计 statistics | ImmortalWrt LuCI feed | 同上 |
| 终端 ttyd | ImmortalWrt LuCI / packages feeds | 正常导入，未增加未经验证的终端行为修改 |
| Relay 协议 | ImmortalWrt LuCI feed | 正常导入，保留现有选择 |
| WireGuard 协议 | ImmortalWrt LuCI feed | 正常导入，保留现有选择 |

共享核心也已核对：sing-box recipe 为 1.14.3，Xray 为 26.3.27，
与检查时官方最新稳定发行一致。Passwall2 的当前生成器已有 1.14 版本判断，
没有仅凭与 HomeProxy 相似的字段名就复制 HomeProxy 补丁。
新增三个插件会增加依赖和固件体积，最终依赖解析、编译和每机型镜像尺寸仍需 CI 验证。

## 明确暂缓或未改变的内容

- **SmartDNS 47 → 48.x**：已确认当前 ZqinKing 核心 recipe 停在 47，
  官方 OpenWrt recipe 为 48.2，独立核心最新稳定发布为
  [Release48.4](https://github.com/pymumu/smartdns/releases/tag/Release48.4)。
  当前又叠加自定义过期缓存、nftset 和启动顺序补丁，升级涉及 DNS 行为；
  本次没有把 UI 版本差异直接当作具体故障，也没有未经配套验证就改解析链。
  这项仍待单独验证新核心、自定义补丁、生成配置及实际解析行为。
- HomeProxy #673 的 VPN 接口选择变化：影响路由策略，缺少对应 VPN 症状和配置依据，
  保留之前的取舍；#671 的 Snell/ACME 大改还包含与已核对 sing-box 类型不兼容的字段，不整体合入。
- OpenClash dev 的完整 ETag 缓存重写、OIX 专用订阅处理和新增 GSO 开关：
  不作为已经证实适用于当前配置的小修复合入；尤其没有改变当前 GSO 默认值。
- AdGuard Home 父仓库的大规模 UI/服务重写：保留当前 fork 的 nftables 特有处理，
  只回移确认的问题；没有操作现有路由器、DNS 链或服务。
- Docker、EasyTier、Lucky、MosDNS 界面、PBR、SQM 界面、WOL、VLMCSd 保持现有未选状态。
  个别核心可能仍会作为其他插件的依赖选入，不能将“未选界面”理解为完全没有相关核心包。

## NSS 与编译边界

`nss,proxy` 片段和固定源码提交保持不变。已发布 manifest 中可见
`kmod-qca-nss-drv`、NSS DP/ECM、PPPoE、bridge、VLAN 等模块及 NSS firmware，
因此当前方案确实包含 NSS。旧片段里的每个符号不一定都在最终 Kconfig 生效，
固件包含 NSS 也不能证明每条代理流量都被硬件加速；本次不改动这一套选择。

保留原有简洁编译输出：正常构建不恢复 `V=s` 全量刷屏，
出错时的详细日志收集和提示仍由原构建步骤处理。

## 验证记录与限制

- 修改前已复现：插件源码缺失、HomeProxy 重复 route add、
  AdGuard Home 自动降级、OpenClash 文件名正则误匹配。
- `tests/run_all.sh` 的 15 个入口全部通过，包含新增配置选择、feed 接入、
  服务补丁、HomeProxy 路由清理、libffi 迁移检查，以及原有日志、Docker 和工作流测试。
- HomeProxy 两个源码基线均覆盖四份补丁的全部 16 种已应用子集、重复应用、
  未知源码拒绝；路由测试覆盖 IPv4/IPv6、TProxy/TUN、旧重复规则和其他 mark/table。
- 完整、重新获取的 AdGuard Home / OpenClash 源码：补丁应用、再次应用及完整 Shell 语法检查通过。
  Lua 日志守卫已检查源码和补丁，未执行真实 LuCI 控制器。
- 实际官方仓库通过生产稀疏同步函数成功导入三个新增插件；
  最新 Argon 源码通过现有兼容包选择逻辑。
- 官方 miniupnpd 2.3.11 tarball 的 SHA256 已核对；旧补丁栈修复及 `e765fb8`
  官方刷新栈分别在干净源码上完整应用通过。
- 本机没有可用 Linux 固件编译环境；上述不替代远程完整固件编译、安装大小、
  真机 DNS/透明代理/NSS 转发验证。依赖源码和分支也会继续变化，
  本地补丁遇到无法匹配的上游变更会停止构建并指出补丁名称。

这些改动已接入工作区构建脚本，尚未提交、推送或触发新的远程编译。
