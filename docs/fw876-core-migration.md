# fw876 SSR 与共享核心集成

当前构建将 SSR Plus+ 与实际选择的配套核心统一到
`fw876/helloworld@v198.2`，固定提交
`45893d778767f3bdb2fcb6e873cf8f9a667d94d4`。Passwall1 已先前移除，
Passwall2 的源码、维护快照与构建集成本轮也已移除。SSR 来源、配套核心、
sing-box、OpenClash 和其他保留插件保持原方案。

本文记录当前源码集成及验证要求。先前迁移的本机回归记录见
[实施与验证记录](superpowers/plans/2026-10-23-fw876-core-migration.md)；Linux CI、
固件交叉编译与路由器验收需分别查看实际执行结果。
2026-10-22 的 [迁移评估](ssrplus-v198.2-migration-assessment.md)
保留当时的代码事实，其中保留旧启动/DNS 修复的建议已被本次明确范围替代。

## 固定源码与版本

生产输入位于 [受管源码目录](../wrt_core/managed/README.md)，
[来源锁](../wrt_core/managed/sources.lock.json) 保存每个包的完整文件集合、
Git blob、mode、SHA-256、来源与许可证记录。以下 15 个顶层配方来自同一固定提交：

| 配方目录 | 原始版本与 release | 用途 |
| --- | --- | --- |
| luci-app-ssr-plus | 198-r2 | SSR 主程序与组件更新入口 |
| xray-core | 26.10.21-r2 | SSR 使用的定制核心 |
| chinadns-ng | 2025.08.09-r1 | DNS 组件 |
| dns2socks | 2.1-r2 | 已选 DNS/代理配套组件 |
| dns2tcp | 1.1.2-r3 | SSR 必需 DNS 组件 |
| lua-neturl | 1.2.1-r1 | Lua URL 解析；上游归档版本为 1.2-1 |
| microsocks | 1.0.5-r1 | SOCKS 配套组件 |
| mosdns | 5.3.4-r1 | SSR 已选 DNS 组件 |
| shadowsocks-rust | 1.25.0-r3 | 已选 Shadowsocks 客户端/服务端 |
| shadowsocksr-libev | 2.5.6-r13 | 已选 ShadowsocksR 组件 |
| simple-obfs | 0.0.5-r2 | 已选混淆组件 |
| tcping | 1-r1 | 连接探测工具 |
| v2ray-plugin | 5.49.0-r1 | 已选 Shadowsocks 插件 |
| ipt2socks | 1.1.4-r1 | SSR 透明代理配套组件 |
| upx | 5.2.1-r1 | Xray 的 host 编译依赖，不因此选择目标机 UPX 包 |

SSR 从项目旧 `190-r12` 切换到 fw876 `198-r2`。Xray 由旧的官方基础配方
加版本升级补丁，切换为 fw876 `26.10.21-r2` 完整配方及十份定制补丁；
两者即使显示相同核心版本号，也不能视为同一产物。其余表列版本是此次固定输入，
不是对旧滚动来源或已安装设备版本的推测。

15 个配方共 914 个包内文件；导入时按
[原始清单](../maintenance/plugins/manifests/ssrplus-v198.2.json)
逐项核对大小、SHA-256、Git blob，并另存上游根许可证。完整原始仓库仍留在
[维护区](../maintenance/plugins/ssrplus/README.md)，构建只读取经过单独锁定的受管副本。
未选择的 fw876 可选核心不随完整维护快照导入生产。

## 唯一来源与更新入口

构建先验证受管源，再恢复权限与符号链接。外部 sparse/root 同步在联网前拒绝任何
受管同名包；标准 feeds 的冲突配方被移除。tcping 准备入口只做本地完整性校验，
不再从 Passwall 在线覆盖。MosDNS 核心来自 fw876，LuCI MosDNS 的原来源、配置处理
和未选状态保持不变。

运行时共享 Xray 的唯一内置在线更新入口是 **SSR Plus → 组件更新**，
使用 fw876 的发行包并保留完整包修订号，例如 `26.10.21-r2`。
相同核心版本的 `r2`、`r3` 仍可能对应不同补丁，检查更新时不能丢掉该修订号。
构建来源固定与运行时主动检查 fw876 新发行版是两个阶段，在线更新不改写仓库来源锁。

SSR 主程序的内置在线自升级禁用，防止直接安装上游原包后丢失
本项目的共享核心管理适配。主程序升级应使用本项目重新准备和验证的软件包或固件。
这个约束针对插件提供的更新流程，不代表系统包管理器无法由管理员手工替换软件。

## SSR 集成范围

生产准备只应用 [当前补丁清单](../wrt_core/compat/ssrplus/patches.list)
所列的 v198 集成调整，包括所需依赖、安装权限、当前 Xray 配置及更新入口适配。
保留新来源检查、准备幂等、IPK/APK、公共 rootfs 与按设备 rootfs 校验；
未知来源、缺失清单、内容或权限不一致都会中止对应检查。

旧启动锁、DNS 事务、运行辅助脚本与 190 系列修复链已经移至
[历史测试目录](../tests/fixtures/ssrplus-legacy/README.md)。生产模块不引用或安装该目录。
保留这些历史回归用于解释旧问题，不将其通过结果计作 v198 运行验证。
当前启动、DNS、IPv6 与防火墙行为使用 v198.2 上游实现，并由新测试单独覆盖；
本次没有重新引入旧生命周期/DNS 修复，也不承诺旧行为保障仍然存在。

SSR 自身组件选项和必需依赖显式保持已有能力与未选组件状态，
避免 v198.2 的新默认值隐式增删核心。除移除 Passwall1/Passwall2 外，其他插件和设备选择不变。

### 构建副本中的翻译软链接

上游 `po/zh-cn -> zh_Hans` 是锁定源码的一部分。仓库以目标文本保存它，
实际构建由 `managed_plugins.py stage` 恢复符号链接。SSR 适配器必须按锁定
类型和目标验证并保留该链接；仅复制仓库文本不等于验证真实构建输入。
组合回归必须覆盖实际装载后适配及重复执行，同时拒绝类型替换、目标漂移、
越界和额外链接，并保证拒绝前不发布部分修改。

2026-10-24 的构建在适配器拒绝合法翻译链接时退出；修复与验证记录见
[软链接兼容修复计划](superpowers/plans/2026-10-24-ssrplus-source-symlink.md)。
同次任务环境准备耗时 3 小时 42 分钟，APT 下载占 97.3%，见
[环境准备耗时调查](build-environment-2026-10-24.md)。

## Xray 与工具链门槛

simple-obfs 的固定上游配方另有[归档哈希兼容处理和实际下载回归](source-download-compat.md)。原始受管配方、来源提交和插件选择保留，仅在构建副本固定本包 XZ 归档格式及经独立重建确认的校验值；下载失败会在进入完整编译前终止。

[Xray 构建检查](../wrt_core/modules/xray_core_compat.sh) 校验完整原始配方、
EIP93 说明和全部十份补丁，拒绝文件缺失、额外补丁和内容漂移。
每次执行还检查 Go 的唯一数字版本字段，要求 Go ≥1.27.3。旧官方 Xray 升级补丁不再用于生产。

fw876 Xray 依赖 `golang/host`、`upx/host`；shadowsocks-rust 使用标准 `rust/host`。
启用 Xray 内置 Naive outbound 时，原配方会下载固定哈希的 Cronet Clang；
这不要求导入未选择的独立 NaiveProxy 或其 `gn/host`。

## 验证入口与边界

[tests/run_all.sh](../tests/run_all.sh) 包含来源完整性、构建来源唯一性、Xray 配方门槛、
SSR v198 实际源码和生成器回归；通用配置矩阵仅保留 SSR 的 24 份生成配置。
[Linux 工作流](../.github/workflows/test_ssrplus.yml) 还要求固定 fw876 核心与
当前 v198 DNS/IPv6 网络命名空间检查；旧 190 生命周期检查有单独的历史标识。
测试入口和 CI 配置说明预期门禁，不能作为一次已完成执行的证据。

fw876 测试包为 `xray-core_26.10.21-r2_x86_64.ipk`，归档 SHA-256 为
`790fd76aacedfb5ec75721470323050fe119de546b354c9fbfce0560acd49153`，
提取 ELF SHA-256 为
`8275f03f7715326c6de6b3e25e1f4fa6991738002ac33e620f114437b76236aa`。
下载器校验归档、Package/Version/Architecture 字段及 ELF 哈希，来源证据见
[核心凭据](../wrt_core/compat/proxy-cores/xray-26.10.21.json)。

Windows 已有的官方 Xray 测试核只做通用配置交叉检查，不能证明 fw876 私有协议可用。
Linux 定制核心由 `FW876_XRAY_TEST_BINARY` 指定，CI 设置
`REQUIRE_FW876_XRAY_TEST_CORE=1`，缺少或身份不符时失败。
Windows 上下载并核对 Linux ELF 不等于执行该 ELF；POSIX 权限、符号链接和真实
nft/dnsmasq 行为也应以 Linux 执行结果为准。

完整固件交叉编译、最终发布产物、保留配置升级及路由器上的 DNS/IPv6/UDP、
握手和数据转发仍需独立验证。本次迁移未操作路由器；用户已授权在验证通过后提交推送，
并通过原有发布工作流触发 `jdcloud_ipq60xx_immwrt` 编译。
