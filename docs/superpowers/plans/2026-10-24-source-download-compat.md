# 源码归档与下载失败传播修复计划

> 执行方式：按用户直接修复指令并行实施独立模块，测试先行，完整回归和独立审查后提交推送。

**目标：** 修复京东云构建 40062153515 的 simple-obfs 归档哈希不兼容，以及顶层下载目标掩盖子任务失败的问题。

**架构：** 保留 fw876 原始受管源码，在构建副本实施严格校验输入的兼容转换；修正 OpenWrt 下载命令的错误传播，保留其下载顺序和工具依赖。

**技术：** Python、Bash、GNU Make、Git 源码归档、Linux CI。

**依据：** 用户本轮授权及失败构建原始日志；固件源码 `VIKINGYFY/immortalwrt@3fd1e27a511851b41cf082b067b60099e8e026c4`。

## 约束

- 不修改插件来源、固定提交、插件选择、设备配置和编译配置。
- 不修改 `wrt_core/managed` 原始配方与锁文件；不跳过归档校验。
- simple-obfs 固定主提交 `486bebd9208539058e57e23a12f23103016e09b4`，libcork 固定子模块提交 `f02984545061c924808e4b9ea7cc6749a41f1979`。
- 不将 Windows fixture 或配置解析结果称为目标固件/路由器运行验证。

## 实施与验收

- [x] 独立获取固定主仓库与子模块，对照 Git tree 的路径、文件内容及模式，重建归档并确认哈希；先记录原配方失败。
- [x] `wrt_core/simple_obfs_compat.py` 和 `tests/test_simple_obfs_compat.py`：实际 stage 后固定本包 XZ 格式并调整已验证的归档哈希，覆盖重复执行、原始文件不变、未知输入拒绝。
- [x] `wrt_core/update.sh`：在生产准备路径调用归档兼容转换。
- [x] `wrt_core/download_compat.py`、`wrt_core/modules/build_steps.sh` 和下载回归：真实 Make 执行上游 download recipe，覆盖四个子任务失败、成功、后续不再执行、未知结构拒绝及幂等。
- [ ] 实际下载回归：调用固定 OpenWrt 下载框架，完成源码获取、子模块身份校验和归档哈希验证，错误校验值必须失败。
- [x] 接入现有完整测试入口和 Linux 强制 CI；Windows 完整回归及差异检查。
- [ ] 独立审查后推送验证分支，确认同一提交 Linux CI 通过，快进推送 master，再触发 `jdcloud_ipq60xx_immwrt`。

## 审查重点

- 归档哈希不能仅照抄失败日志；独立重建证据应与生产下载路径一致。
- 顶层 download 不得在前序失败后执行后续目标，也不得进入 prepare/compile。
- 镜像尝试失败后成功恢复不应误判为总失败。
- 未识别源码或 Make recipe 必须拒绝转换；不允许部分写入或绕过验证。
- Linux 实际网络下载必须执行；可复用通过完整性验证的本地缓存，但要覆盖干净重建。

**归档格式决定：** 独立重建确认主仓库与子模块的 279 个普通文件、321 个归档条目，tar SHA256 为 `369a65861e5046a1fc2be77f6426bd2ea262afabbcbbef679cf7898ce434248b`。多线程 XZ 格式精确重建 `da5af…0035`。进一步发现 Ubuntu 系统 xz 5.4.5 与恢复的 host xz 5.8.3 默认格式不同，因此适配同时给本包导出 `XZ_OPT=-T0`，避免无缓存首次下载失败；该设置不修改全局工具、来源或固件编译配置。

**定向验证记录：** 原始下载 recipe 的真实 GNU Make 回归先出现 6 个预期失败，修复后 5 项通过；simple-obfs 哈希适配先 RED 后通过，增加 XZ 格式验证后 12 项通过。最终定向复验另含来源 4 项、CI 门禁 4 项和构建步骤 Shell 回归。Windows 测试环境新增固定 GNU Make 4.4.1-3，真实 install/check 已通过。完整测试与交付结果以本次后续执行及提交 Checks 为准。

**Windows 完整验证：** 2026-10-24 15:03:46 至 15:27:54（UTC+8）执行 `python tests/windows_test_env.py run`，退出码 0；533 项 unittest 通过、24 项平台相关跳过，Shell 回归通过。运行期间新增的两个 XZ 传播用例已包含在最终 12 项 simple-obfs 定向复验中。锁宏另经真实 Make/shell/flock 预检通过；Linux 实际下载及完整门禁将在验证分支执行，未以 Windows 结果替代。
