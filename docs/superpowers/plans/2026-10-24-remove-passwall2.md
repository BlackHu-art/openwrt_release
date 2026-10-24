# 移除 Passwall2 实施计划

> 按用户直接移除指令执行；分工处理生产入口、回归和文档，完整验证后沿用提交推送与京东云重编流程。

**目标：** 删除不再使用的 Passwall2 插件、维护源码及专用适配，保持 SSR 和其他插件原有来源与选择。

**架构：** 从配置、导入、安装校验和预安装适配中移除 Passwall2；共享核心继续由 fw876 受管输入提供，保留完整配方与 Go 门槛；保留 SSR 的真实生成器、生产装载和错误传播测试。

**技术：** Bash、Python、Lua、Kconfig、GitHub Actions。

**依据：** 用户本轮移除要求；构建 `40074582173` 在 Passwall2 专用核心更新补丁匹配阶段失败。

## 约束与审查重点

- 不更换 SSR 或其他插件的来源、固定提交及核心配方；仅移除 Passwall2 的选择。
- 删除维护快照、清单、独立许可证和来源锁条目；其他上游原始源码保持不变。
- 保留上游 feed 中同名包清理以及 defconfig 后的显式排除检查，防止被重新选入。
- 主题上游源码中无安装作用的 Passwall2 样式与历史审查记录不属于插件源码，不为清零关键词而改动。
- SSR 共享测试的通用 Shell 工具应独立于被删除的 Passwall2 测试；保留 SSR 24 份通用协议配置及 fw876 专属核心测试。
- 区分本机/CI 回归、实际下载、固件编译与路由器实机运行结果。

## 步骤

- [x] 核对失败日志和生产引用；新增移除验收并确认 RED。
- [x] 清理 `custom_feed.sh`、`verify.sh`、`update.sh`、`plugin_compat.sh`、`xray_core_compat.sh`，调整 `check_selected_plugins.py` 与 `proxy.config` / 京东云原显式选择。
- [x] 删除 `maintenance/plugins/passwall2`、对应 manifest/license/lock 条目与三份 `wrt_core/patches/passwall2-*.patch`；更新 Xray 验证记录。
- [x] 重整 `tests/`，保留 SSR 配置生成、装载、核心门槛及失败传播；清理 CI 专用路径和当前维护文档。
- [ ] Windows 受影响回归、Linux 完整门禁、独立审查和差异/链接检查。
- [ ] 提交验证分支并执行 Linux 完整门禁，同一提交通过后快进主分支、推送并触发 `jdcloud_ipq60xx_immwrt`。

**验证分工：** 本轮 Windows 定向执行源码移除、装载、核心门槛、SSR 生成器以及通用 Shell 工具相关用例；Linux 执行完整 `tests/run_all.sh`、实际下载和 DNS/IPv6/nftables 命名空间检查。受管核心和其他源码原始字节、非 Passwall2 配置选择另做零差异核验。

**独立审查：** 当前无未解决 P1/P2。已核对其余插件来源记录与受管核心原始字节未变、其他配置选择未变；移除回归 4 项和包选择回归 8 项通过。此前失败仅发生在 Passwall2 补丁匹配，本次构建尚需继续验证下载和后续编译阶段。

**本机最终复验：** 11 组受影响套件合计 94 项，89 通过、5 项 Linux/POSIX 限定跳过，退出码 0；固定 Windows venv、Lua51、GNU Make、Git Bash 和官方 Xray 均由测试环境助手注入。另通过真实 custom feed 本地导入、上游约束、Shell LF、入口路径检查、109 个文档链接及 `git diff --check`。完整 Linux 门禁与固件任务结果以同一提交的 Actions 为准。
