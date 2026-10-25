# SmartDNS 固定来源修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留 SmartDNS，修复包装仓库默认分支更新后无法通过已审核配方校验的问题。

**Architecture:** 沿用 ZqinKing/openwrt-smartdns，在浅克隆后获取并检出已审核提交 `cdf0de1d3e64984ea2c56ec873f233495ddb1de0`，核对实际 HEAD 后再执行现有兼容处理。原始维护快照、核心/WebUI 提交、哈希及 LuCI 来源保持不变。

**Tech Stack:** Bash、Git、Python unittest、GitHub Actions。

**Spec:** 用户要求“继续处理编译失败，不要移除”；对应失败为 [40170792954](https://github.com/BlackHu-art/openwrt_release/actions/runs/40170792954)。

## 约束

- 不移除 SmartDNS，不更改任何插件选择或设备编译配置。
- 不升级到上游新配方 48.4，不绕过配方、源码或归档校验。
- 不修改参考快照原始字节及其他插件的来源。

## 审查重点

- 默认分支前进后仍获取并实际检出固定提交。
- fetch、checkout、rev-parse 失败或 HEAD 不符时不执行后续适配和 LuCI 更新。
- 固定提交中的配方异常仍被原校验拒绝。
- 验证使用真实 Git 仓库，不能只靠复制旧 Makefile 的替身。
- 本地回归通过与 Linux 门禁、完整固件编译结果分别报告。

## 实施与验证

- [x] 在 `tests/test_smartdns_compat.py` 增加固定来源及错误传播用例，先确认新用例失败。
- [x] 在 `wrt_core/modules/package_source_updates.sh` 添加固定提交获取、检出和身份检查。
- [x] 运行 SmartDNS 定向回归，以及同一远端固定提交的真实获取验证。
- [x] 更新下载兼容和维护文档中的构建来源说明。
- [x] 运行 Windows 完整回归、文档链接检查、`git diff --check`，审查最终差异。
- [x] 按本会话既有交付要求提交推送，在 Linux 回归通过后触发京东云编译，核对启动状态。

## 执行证据

- 红阶段：原有 20 项通过，新增 5 项按预期失败；修复后定向回归 25/25 通过。
- 从实际远端默认 HEAD `b4a7fa1dba3ffe0c9cb17ab32c492277007cd660` 获取并检出旧提交成功，Makefile SHA-256 为 `e0e6589e5031683536bda4665dcbf928cde0fe45c228f74b7ebaab02be342907`，与维护快照完全一致。
- 临时构建目录实际执行生产 `update_smartdns`，包括两个原始远端仓库、固定提交检出、兼容适配、优化补丁和 CC 修改，结果通过。该检查不代表目标架构交叉编译通过。
- 独立差异审查未发现阻塞问题；未放松原配方或失败后不继续执行的断言。
- Windows 完整回归于 2026-10-25 15:18–15:42（北京时间）完成，入口退出码 0；Python 用例 593 项，其中 566 项通过、27 项既有平台跳过，Shell 检查通过。Linux 必需下载与网络命名空间门禁由提交后的 CI 单独验证。
- 维护文档入口 13 文件的本地链接检查、额外 5 个变更文档链接检查及 `git diff --check` 均通过。
- 修复提交 [`acdf6b3`](https://github.com/BlackHu-art/openwrt_release/commit/acdf6b39dcaecb08c8e59265ede35332a69f126c) 已推送到 `master`。对应 [Linux 回归 40173794007](https://github.com/BlackHu-art/openwrt_release/actions/runs/40173794007) 成功：Python 用例 627 项，626 项通过、1 项 Windows 专用测试跳过；真实 SmartDNS 归档下载、错误哈希拒绝、fw876 DNS/IPv6 命名空间检查通过。
- 已通过 API 触发 [京东云编译 40174060027](https://github.com/BlackHu-art/openwrt_release/actions/runs/40174060027)，核对构建提交为 `acdf6b3`、型号为 `jdcloud_ipq60xx_immwrt`，未添加或移除配置片段。记录时状态为运行中，不代表完整固件或真机验证成功。
