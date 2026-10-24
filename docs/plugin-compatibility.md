# 插件兼容修复与编译入口

SSR 与已选共享核心固定到 `fw876/helloworld@v198.2`；Passwall1 与 Passwall2 均已移除。
共享 Xray 使用 fw876 `26.10.21-r2` 完整配方及十份补丁，要求 Go >=1.27.3；
sing-box 保持 `1.14.3`，其他插件选择不变。旧 SSR 启动/DNS 修复仅用于历史回归。
项目标准 `build.sh` / GitHub Actions 在源码准备阶段应用当前集成调整，
完整范围见 [fw876 集成说明](fw876-core-migration.md)。

当前 AX6600 的 `jdcloud_ipq60xx_immwrt.config` 已启用 SSR Plus、OpenClash 和 AdGuard Home。
`jdcloud_ipq60xx_libwrt.config` 启用 OpenClash/ADG，SSR 需由最终配置选中；
所有使用 `proxy` 片段的机型均不再选择 Passwall1 或 Passwall2；defconfig 后会复核排除项。

固件源码由 `wrt_core/update.sh` 编排本地受管输入和外部来源，再由 `wrt_core/modules/`
应用兼容处理。实际参与构建的本地输入位于 [`wrt_core/managed/`](../wrt_core/managed/README.md)；
`maintenance/plugins/` 继续保存保留插件的 reference-only 审查快照。

## 受管源码与构建接入

[`sources.lock.json`](../wrt_core/managed/sources.lock.json) 固定 30 个顶层源码单元，
记录完整提交、原始路径、Git mode、文件集合和 SHA-256。Argon 内嵌的空配置兼容包
随主题保留，不作为额外独立源码再次复制。

- `custom_feed` 的 27 个本地单元：15 个 fw876 配方，以及 sing-box、luci-app-homeproxy、
  oaf、open-app-filter、luci-app-oaf 和 iStoreX 的七个组件；完整清单见受管来源锁。
- 原 `feeds/luci/themes/` 路径的两个主题：luci-theme-argon、luci-theme-aurora；
  luci-app-aurora-config 沿用 `feeds/luci/applications/` 路径。

`managed_plugins.py` 先验证本地文件集合、哈希和安全路径，再在构建副本中恢复执行权限及符号链接。
Windows 仓库中的 `120000` 链接保存为目标文本，不能把这些文本文件当作已还原的 Linux 链接。
受管输入不从网络回退；其余插件和 recipe 指向的核心源码、发行归档仍按现有来源下载。
HomeProxy、OAF 和主题兼容处理只作用于构建副本，不改写受管原始快照。

刷新来源时需要一起审查源码、锁文件、补丁/compat、fixture 和回归；仅更新
`maintenance/plugins/` 的参考快照不会使本地受管输入发生变化。完整步骤见
[受管源码说明](../wrt_core/managed/README.md)。

## Passwall 移除与 Xray

Passwall1 和 Passwall2 的插件源码、维护清单、独立许可证、下载入口、兼容补丁与
编译选择均已移除。上游主题中无运行代码的兼容样式随主题保留，不会安装这些插件。
本轮不再导入、修复或适配官方 Passwall2。

Xray 继续使用受管的 fw876 `26.10.21-r2` 完整配方及十份补丁，来源和测试核心身份见
[核心记录](../wrt_core/compat/proxy-cores/xray-26.10.21.json)。
`fix_xray_core_compat` 每次核对整个 recipe 子树及十份补丁，随后检查 Go 的
major/minor/patch；缺失文件、额外补丁、未知声明或旧 Go 均拒绝。
`update_golang` 继续先验证 `27.x` 的 Go >=1.27.3，再替换旧源；失败保留旧源并停止准备。

运行时 Xray 通过 SSR「组件更新」从 fw876 更新，并保留完整包修订号；
SSR 主程序在线自升级禁用，以保留项目适配。其他保留插件与核心的更新策略不变。

通用配置矩阵只使用当前 SSR v198 生成器，共 24 份配置；官方 Xray 仅作通用 JSON
配置交叉检查，私有协议验证仍要求精确匹配的 fw876 Linux 核心。
旧 `190-r12` 的历史测试不能代替当前集成验证。`xray-plugin` 是独立软件包，不随本次改版。

## HomeProxy、主题与 iStoreX

HomeProxy 固定官方 `fadaa676104f59ff6ace480a780a258d846d0aec` 的完整包源码，
继续经过 `fix_homeproxy_compat` 的补丁预检、重复执行和未知变化拒绝逻辑，并补齐
`ucode-mod-math` 依赖。现有 sing-box 1.14 兼容、ACL 域名应用和特性缓存补丁仍保留，
未随本地接管移除。恢复 `disable_cache_expire` 到 sing-box DNS `disable_expire` 的有效映射，
缺省、显式 0/1 和保留配置均有回归。翻译和规则数据随该源码提交固定。

Argon 3.1.0 的设置、RPC 和翻译由主题唯一提供。主题内部的空
`compat/luci-app-argon-config` 保留包名与升级兼容；构建移除旧独立配置目录，
缺少集成标记或兼容 recipe 时停止。Aurora 主题 1.4.0 与配置 1.2.5 继续分别安装，
主题沿用 `feeds/luci/themes/`，配置包沿用 `feeds/luci/applications/`，各自源码保持独立。
`theme_compat.py` 在安装 Aurora 构建副本后校验完整初始化脚本，再应用保留配置的迁移：
旧版/缺失 schema 只补缺省值，已有字体、logo、工具栏、颜色及未知字段保留；未来/未知 schema 不降级。
旧颜色和宽度别名只在新键缺失时复制，原键保留。Argon 的 `990_set_argon_primary` 也只补缺失字段，
显式空串、0 和自定义值均保留，且回归覆盖主题自身初始化后再运行仓库初始化的实际顺序。


iStoreX 本地接管七个组件：luci-app-istorex、quickstart、luci-app-quickstart、
luci-app-store、taskd、luci-lib-taskd、luci-lib-xterm。库 `luci-lib-taskd 1.0.26`
满足 iStoreX 的 `>=1.0.15` 和商店的 `>=1.0.19`；`taskd 1.0.3-r2` 满足库的
`taskd >=1.0.3`，这两个包的版本不能混比。taskd 依赖的 `script-utils` 由目标核心的
util-linux recipe 提供，其他标准依赖仍由目标核心和 feeds 解析。

原 `fix_quickstart` 继续处理存储依赖，但其 `istore_backend.lua` 不再由浮动 raw URL 覆盖。
本地兼容文件固定 gist revision `51ae1464e068fadc348c0b577f8ffd338bbd7ee5`，
SHA-256 为 `5eb5e0524a42b62895ee8163d50bf1d78999db7c1321646fdcca3c99c26249e2`。
来源与许可说明保存在锁文件中；保留来源不表示获得了 gist 的额外授权，聚合仓库的
Apache-2.0 文件也不能作为该独立 gist 的许可证明。quickstart 二进制与 istore-ui
发行归档仍按各 recipe 的固定版本和哈希外部下载。

## OAF 7 默认状态与配置边界

本次保持受管 OAF 7 / `fwx` schema，适用前提是用户确认尚未使用 OAF 规则。
`oaf_compat.py` 校验已审查原始字节后，在构建副本中为新安装准备
`fwx.appfilter.enable`、`fwx.macfilter.enable`、`fwx.record.enable` 三项 0，
并保留 `disable_hnat=0`；上游既有文件检查继续保留已有显式 `fwx` 值。
`99_disable_oaf` 仅在三项均为 0 时执行默认停用策略，不重写运行中的 UCI 配置。
在线安装/升级通过一次性 installer PID 与进程出生时间标记抑制紧随其后的自动启动，
标记位于 root 控制的 `/var/run`；保留管理员在升级前已启用的启动项，后续手动 enable/start 不受永久限制。
普通首启（包括保留配置刷机后的首次启动）没有安装上下文，不创建该标记，
仍按原策略在三项均为 0 时停用服务；不能据此承诺保留这种情况下的手动开机启用状态。真实 OPKG/APK postinst 与 rc.common 离线生命周期回归覆盖这些顺序。

后端与 LuCI 重复的同名 ACL 合并到后端包，由一个文件所有者提供全部已审查权限。
使用者仍需按主 README 的流程手动 enable/start appfilter，之后界面才可使用控制面。
本次不承诺旧 OAF 6 的 `appfilter` 规则自动迁移到 `fwx`，也未验证旧规则的语义转换。

## QuickFile 外部源码检查

QuickFile 不在上述 30 个受管单元内，仍从 sbwml/luci-app-quickfile 获取源码。
当前已核对提交 `13f1a61d962e3a7790f7ab9898543be2ee5835cb` 的核心为 `2.0.8-r1`，
官方 `quickfile-src-2.0.8.tar.xz` 实测 SHA-256 与 recipe 的
`05596624c46331418296a86a4f0a457a9b5f8ff2d9bd81e0f4e8cb6a3933b7db` 一致。
LuCI recipe 依赖 luci-nginx 和 quickfile；核心通过 rust/host、rust-package.mk
及目标架构规则编译，并安装 `PKG_INSTALL_DIR/bin/quickfile`。

旧 `ARCH_PACKAGES` sed 对该 recipe 没有匹配对象，只是静默 no-op，不能作为已证明的
编译失败根因。现在删除旧架构改写，`quickfile_verify.py` 在候选源码替换已有目录前检查
Rust 构建和安装结构；不符合该结构的旧预编译 recipe 会被拒绝，失败向调用阶段传播。
这属于结构检查，不是固定整个上游提交或为未知代码背书；Rust 源码归档仍按 recipe 哈希外部下载。
固定 fixture 和测试范围见 [QuickFile 基线说明](../tests/fixtures/quickfile/README.md)。

## SSR Plus

SSR 原始包固定为 `fw876/helloworld@v198.2`，由受管 loader 复制到构建树。
`stage_pre_install_source_fixes` 调用 `fix_ssrplus_compat`，应用
[当前 v198 补丁清单](../wrt_core/compat/ssrplus/patches.list)，补齐必需依赖、
安装权限、Xray 配置及更新入口适配；主程序在线自升级禁用，避免丢失项目适配。
原始受管包保持上游字节，源码准备幂等并拒绝未知改动。

旧启动锁、DNS 事务、运行辅助脚本和 190 系列补丁已移入
[历史测试目录](../tests/fixtures/ssrplus-legacy/README.md)。生产不调用这些实现，
v198 上游启动、DNS、IPv6 与防火墙路径由当前源码测试单独验证。
旧版的并发、事务恢复或初始化承诺不能直接套用到新版本。

源码来源清单、包版本、安装文件内容与权限继续进入 IPK/APK 和 rootfs 门禁；
按设备 rootfs 仍检查实际制镜像目录。用户配置不作为不可变安装内容哈希。
SSR 自身组件选择显式保持已有能力，新增必需依赖单独声明；其他插件和设备选择不变。
详细来源、更新策略和验证边界见 [fw876 集成说明](fw876-core-migration.md)。

## OpenClash

从当前 `kenzok8/small-package` 获取包，在 feeds install 前调用
`fix_openclash_compat`，在已审查的 `0.48.002` 源码上应用以下六份补丁：

- `openclash-wan-subnets.patch`：保留原有 WAN 子网修复。
- `openclash-checksum-filename.patch`：对照
  [91d7370](https://github.com/vernesong/OpenClash/commit/91d73707a6bcd0f8ec96a57095d72b1b4357cbe7)，
  按完整 basename 精确匹配 SHA-256 清单，处理路径前缀、星号、CRLF 和大写哈希。
  文件内容不匹配时拒绝；没有有效校验值时保留上游的警告并跳过校验行为。
- `openclash-ruby-ast.patch`：回移
  [ac3c7bf](https://github.com/vernesong/OpenClash/commit/ac3c7bf13ddc7faa6c2b82739d9bce8934c1342d)，
  接受 Ruby 3.4 的数值、正则等 AST 节点及仍受方法白名单约束的无括号调用，继续拒绝危险调用。
- `openclash-dashboard-switch.patch`：回移
  [4983173](https://github.com/vernesong/OpenClash/commit/4983173bb2ff403e64a9b7754ca160c514b36301)，
  切换成功、失败和删除操作的状态写入实际点击的 dashboard 卡片。
- `openclash-filename-safety.patch`：回移并适配
  [75d34d0](https://github.com/vernesong/OpenClash/commit/75d34d00482833f0a1ad939d7fc1647c98984fed)，
  在 Lua 与 JavaScript 入口统一文件名规则，保留中文和空格，拒绝路径、shell 特殊字符、
  点号开头、空白名称及超长名称；新建和重命名只允许插件指定目录。
  覆写模块与重启标记改用名称摘要，避免不同名称经字符替换后串用标记。

- `openclash-tun-stack.patch`：缺省 IPv4/IPv6 TUN 栈改为 `mixed`，显式设置保持不变。
  核心注册到 procd 前检查最终运行 YAML（包括覆写与 quick-start 缓存）；若所选 `mips` 未被当前核心支持，
  清晰报错并停止该次启动，不改写 UCI、不开启 respawn 循环。已支持 `mips` 的新核心继续正常启动。
  依据 [官方模式/流量指南 §8.2](https://github.com/vernesong/OpenClash/blob/dev/.github/skills/openclash-user-guide/08-settings-mode-traffic.md)
  并通过旧/新官方 Mihomo 的实际配置解析复核。

标准构建每次刷新 custom feed 后应用补丁。既有五份补丁的任意完整子集（32 种历史组合）
均可补齐，包括原始源码、原有两份完整补丁和完整补丁状态。
更早不同版本的 checksum 补丁、不完整 hunk 状态或无法通过补丁上下文校验的源码变化会停止构建，需重新审查。
OpenClash 此处校验补丁上下文，并非 SSR、ADG 所采用的完整受保护文件 blob 校验。

WAN 上游修复 [#5359 / a4b7073](https://github.com/vernesong/OpenClash/commit/a4b7073)
暂不回移：自定义 WAN 区域与默认链共存时可选错区域，且 fw3 分支仅枚举 IPv4 区域，
存在遗漏纯 IPv6 区域的风险。现有 WAN 子网补丁保留，不据此声称上述问题已经修复。

## AdGuard Home

feeds install 后，`wrt_core/modules/service_fixes.sh` 的 `update_adguardhome`
获取 `ZqinKing/luci-app-adguardhome`，随即调用 `fix_adguardhome_compat`。
该入口依次应用 `adguardhome-update-safety.patch` 和 `adguardhome-noop-update.patch`。
第一份补丁修复更新器与默认下载链接：

- 默认先下载 GitHub 指定稳定标签，再尝试官方稳定镜像。
- 旧固件保留的 `links.txt` 自定义配置仍可使用；稳定更新跳过其中已知的
  beta、edge 和 GitHub 预发布标签地址。
- 稳定 API 标签必须符合 `vX.Y.Z`，每个下载候选执行 `--version` 并与目标
  精确比较。坏归档、错误版本或无法运行的候选继续尝试下一镜像。
- 所有候选无效时，在停止或替换现有核心之前失败；成功日志显示已验证的版本。
- 自动更新不降级；同数字版本的正式版高于预发布版，手工 force 保留原有语义。

默认链接变化只影响新配置；运行时检查也覆盖被固件升级保留的旧链接配置。

第二份补丁适配回移 kenzok78 的
[81a7d33](https://github.com/kenzok78/luci-app-adguardhome/commit/81a7d330896027b82b4d13f368ebcdc8b0237d21)：
已安装核心等于或新于目标版本、无需更新时，即使配置了 UPX，也不停止服务、压缩或替换现有核心。
真正下载候选及显式 force 更新继续保留原有 UPX 行为。

这两份补丁的上下文有重叠，入口先在临时副本中逆序归一化完整补丁，再按
[三文件基线](../wrt_core/compat/adguardhome/source-files.tsv) 检查 `update_core.sh`、`links.txt`
和 `AdGuardHome.lua` 的原始 Git blob，最后顺序应用补丁并发布受保护文件。
原始源码、单份完整补丁和两份完整补丁状态均可收敛；未审查漂移、残缺补丁或缺失清单在实际源码写入前拒绝。
重复执行保留相同文件的字节和修改时间，用户配置不在这三个受保护程序文件中。

## 验证与适用范围

受管输入检查、loader 的权限/链接恢复、实际模块接入、OAF 默认状态和 QuickFile
结构拒绝已加入专项回归入口。测试入口描述覆盖范围，不表示本轮全套回归已经执行并通过；
完整交叉编译、最终 IPK/APK/rootfs 内容和路由器功能仍需单独验收。

`tests/run_all.sh` 包含保留插件的专项回归及现有完整回归；Passwall2 专项回归已随其集成移除。
Xray 配方回归覆盖源码与补丁哈希、版本及 Go 门槛、重复执行和失败时不写入原配方；
源码准备阶段回归另外验证实际接入顺序。
OpenClash 回归执行真实 Ruby AST/覆写入口、模板 JavaScript 和 Lua 文件入口；
ADG 回归覆盖无需更新时不触碰核心、实际下载及 force 控制、四种完整补丁状态、重复执行与漂移拒绝。
`.github/workflows/test_ssrplus.yml` 在 Linux 上执行该入口，并在隔离网络
命名空间验证当前 v198 DNS/IPv6 规则；190 系列生命周期另设历史 fixture 检查。
标准固件构建及发布工作流继续依赖测试门禁。
CI 配置 Ruby `3.4`、Node.js `22`，并强制要求 Ruby 3.4 AST、Node.js、真实 Xray 与旧/新 Mihomo 核心检查；
相关插件补丁、兼容基线和测试所读维护快照的变更纳入测试工作流触发范围。

共享 Xray 通用配置回归通过 `XRAY_TEST_BINARY` 调用官方核心的 `run -test`。
[官方下载器](../tests/fetch_xray_test_core.py) 保留 Windows/Linux 固定哈希；
[fw876 下载器](../tests/fetch_fw876_xray.py) 另校验定制发行包、包身份和 ELF 哈希。
Linux CI 设置 `FW876_XRAY_TEST_BINARY` 与 `REQUIRE_FW876_XRAY_TEST_CORE=1`，
私有协议检查缺少正确核心时失败。Windows 的官方核心通过不能替代该项。
这些配置解析检查不启动代理监听，不能证明真实 TLS 握手或数据转发成功。
Windows 使用官方 `stdin:` 加载完整生成 JSON，Linux 继续验证文件加载；两者均包含非法协议拒绝对照，
不将本机临时文件访问问题误判为生成器或核心兼容问题。

测试执行实际准备后的程序，下载、服务和外部网络边界在测试中替换。
当前 SSR v198 测试读取新的受管源码；保留的首次初始化、旧订阅事务与生命周期测试
明确属于 190 系列历史覆盖，其 `flock` 依赖不能理解为生产恢复了旧锁方案。
完整 Windows 依赖安装与检查见 [本地测试说明](windows-testing.md)。
Windows 本地验证不能替代 Linux 可执行权限、符号链接、fw876 定制核心执行及 nft/dnsmasq 检查。
以上测试入口描述不代表本轮完整回归、固件交叉编译或路由器实机验收已经通过。

## NSS 固件选择

共享 `nss` 片段不再硬编码已被 VIKINGYFY 新 recipe 移除的 11.4 选择项。
当前 LiBwrt NSS feed 仍提供该选项，因此其设备配置保留原有 11.4 请求；其他来源遵循各自 recipe。
这不替换 NSS 驱动或预编译模块，也不构成 Linux 6.12/6.18 的交叉编译验收。
