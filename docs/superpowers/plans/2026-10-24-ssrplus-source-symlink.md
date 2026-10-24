# SSR 源码软链接兼容修复计划

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. 用户已明确授权直接执行、验证、提交推送和触发指定设备编译。

**Goal:** 修复真实装载后的 `po/zh-cn -> zh_Hans` 被 SSR 准备器拒绝的问题，补齐装载与适配的组合回归。

**Architecture:** 保持 managed 源码以文本存储链接的约定；生产装载恢复真实链接。SSR 准备器按照锁定的文件类型校验链接目标，保留链接并仅对普通文件应用兼容补丁。Linux 测试使用实际装载入口，Windows 测试明确区分文件系统能力限制。

**Tech Stack:** Python 3、Git、Bash、unittest、Windows 测试环境、GitHub Actions Linux 回归。

**Spec:** 本轮用户要求及 [fw876 迁移维护说明](../../fw876-core-migration.md)。

## 约束与审查重点

- 不修改插件来源、选择、设备配置、编译配置或上游 managed 源码。
- 只允许锁内声明且目标匹配的包内链接；普通文件校验保持严格。
- 链接篡改、越界、断链、替换类型及额外链接必须在发布修改前被拒绝。
- 重复适配保持文件内容、权限和链接目标；不得把链接展开成目录或覆盖成文本。
- 生产代码不增加仅用于测试的校验旁路；Linux 组合回归不可因链接能力异常而跳过。

## 实施与验证

- [x] 在 `tests/test_ssrplus_v198.py` 增加组合回归，并通过 Windows 受控文件系统边界测试捕捉与生产日志相同的拒绝，保留红灯证据。
- [x] 修复 `wrt_core/ssrplus_verify.py` 的源文件类型校验、暂存与发布处理，保持 rootfs 成品保护逻辑。
- [x] 更新 `tests/prepare_ssrplus_candidate.py` 和当前版本测试准备入口，覆盖实际装载、适配与重复执行；增加错误链接拒绝用例。
- [x] 运行直接回归和完整 Windows 回归，独立审查最终差异。
- [x] 记录环境准备耗时调查；本轮不改构建环境流程。
- [ ] 提交并推送经本地验证的修复分支，确认该提交的 Linux 完整回归通过后再快进 `master`。
- [ ] 验证本地和远端 `master` 提交一致，触发 `Release WRT`，设备为 `jdcloud_ipq60xx_immwrt`，配置片段使用原默认值。

## 验证记录

本地 Windows 没有创建符号链接的权限，真实链接组合验证必须由 Linux CI 提供；不能用 Windows 文件文本测试替代。

- 修复前先运行 `SourceLinkContract` 中的普通文件拒绝和正确链接接受两项测试：前者错误接受链接文本，后者报 `source must not use symlinks: po/zh-cn`，两项均未通过。
- 修复后定向测试：当前 SSR 27 项（24 通过、3 项真实 POSIX 组合测试在 Windows 明确跳过），构建成品门禁 19 项通过，组件更新 8 项通过。
- 独立审查未发现待修问题，另外复跑源码集成 11 项及构建门禁 19 项，均通过。
- Windows candidate 实测因缺少符号链接权限报告 `WinError 1314`，未生成候选目录，也没有退回普通文本。
- 完整 Windows 回归 `python tests/windows_test_env.py run` 于北京时间 2026-10-24 11:57:29—12:18:50 执行，退出码 0；40 组 unittest 共 535 项，512 通过、23 项平台或可选核心能力跳过，Shell 检查及来源、工作流门禁通过。
- 日志目录为仓库外测试依赖目录的 `runs/20261024-115729-446666/`，包含 `regression.log` 与 `result.json`；环境和复跑方法见 [Windows 测试说明](../../windows-testing.md)。
- 文档本地链接检查通过。此记录随本地验证后的提交保存，目标提交的 Linux CI、主分支推送和编译任务结果以 GitHub Actions 为准。
