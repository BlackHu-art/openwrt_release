# 必要上游修复与跨电脑维护知识库实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan. Keep tasks and verification evidence current below.

**Goal:** 移植当前配置需要的 fw876 修复，并让新电脑仅依靠仓库即可定位维护入口、恢复测试环境和理解验证边界。

**Architecture:** 保留 `fw876/helloworld@45893d778767f3bdb2fcb6e873cf8f9a667d94d4` 原始受管输入，以有来源记录的构建副本补丁移植 KCP 层序和 Xray UPX 复用。知识库作为现有文档的入口和操作指南，历史诊断继续保留。

**Tech Stack:** Bash、Python unittest、Lua 5.1/Lupa、GNU Make、Markdown。

**Spec:** 本次用户授权同步必要修复并整理跨电脑维护知识库；前一轮审查选择 KCP 层序及 Xray 打包优化。无需增加插件或升级整套 dev 来源。

## 约束与审查重点

- 不改变插件选择、设备配置、核心下载来源或原始固定提交。
- KCP 参考 `31b180df838e456bb36036bb8791f569af0fd661`；保留当前新格式适配，将 security/seed 放在 header 前。
- Xray 打包参考 `20756eaad8aa61ce7168dad90b56db2d7c81063c`；只移植 Xray 部分，构建副本修订号 r3，原始快照和测试用 r2 核心身份保留并说明。
- 不引入未选 Mihomo 的改动、Hysteria2 realm UPnP 新功能或上游未定义 `node` 的回归。
- 验证未知源码拒绝、重复准备、UPX 失败传播、重复打包复用和重建重新压缩。
- KCP 配置解析通过与客户端/服务端互通分开记录；Windows 主机回归不能代替 Linux 网络命名空间和固件实机验收。
- 文档使用仓库相对链接和可替换路径，不依赖本机绝对路径、聊天记录或私人记忆。

## 任务

- [x] KCP：先修正回归预期并观察失败，再更新现有适配补丁；覆盖伪装头、空/非空 seed、自定义 finalmask，增加真实核心本地互通验证。
- [x] Xray：先加入真实 Make 打包行为回归并观察重复压缩问题，再以完整原始/派生配方校验实施补丁；保留十份核心补丁和 Go 门槛。
- [x] 文档：建立 `docs/README.md` 及维护知识库，修正 README 克隆入口，串联新电脑准备、来源刷新、补丁维护、测试与 CI 排错。
- [x] 整合：来源完整性、相关回归、Windows 完整回归、文档链接与 `git diff --check`；独立审查后修正发现的问题。

## 执行记录

- 起点：`f5fcc2b`；复用已有 `codex/fw876-core-migration` 工作区。原有未跟踪 `__pycache__` 不作为本次提交内容。
- 本计划不自动发布固件或触发远端编译。测试结果与限制在完成后补入。

### 已完成的定向验证（2026-10-25）

- Windows `tests/windows-tests.ps1 -Action check`：通过；flock 2.40.2、GNU Make 4.4.1、官方 Xray 26.10.21、Ruby 3.4.9、Node 22.23.4。
- KCP 红绿：当前 v198 生成器的 24 组矩阵在旧补丁下有 18 组顺序失败；调整测试 peer 的回环目标放行后，仅在独立进程中恢复旧客户端层序，同一正例再次 5 秒超时；修复后 srtp + 非空 seed 完成 4124 字节双向回显，逆序负例仍失败。
- `tests/test_ssrplus_core_transports.py`：14 项通过；`tests/test_shared_xray_compat.py`：7 项通过；`tests/test_ssrplus_v198.py`：27 项，跳过 3 项 Windows 不支持的 POSIX 实际装载检查。使用专用 Windows 测试环境及其 `XRAY_TEST_BINARY`。
- UPX 红绿：原始配方两设备与一次重打包压缩 3 次，重建累计 4 次；修复后分别为 1 次、2 次。真实 GNU Make 执行配方宏，Go 编译和 UPX 为替身，另覆盖失败、重试、原始输出保持。
- `tests/test_xray_core_compat.py`：29 项通过；`tests/test_proxy_compat_pipeline.py`：4 项通过；`tests/test_fw876_sources.py`：4 项通过；`managed_plugins.py check`：30 包通过。
- CI 触发路径回归：先因缺少 `wrt_core/xray_core_compat.py` 的触发项失败，补齐 push/PR paths 后通过。
- `python tests/check_doc_links.py`：13 篇维护文档的本地路径通过；另外验证缺失、非便携绝对路径、越界链接会失败，代码块示例不误报。锚点和外部 URL 不在该检查范围。
- 独立审查未发现阻断问题；另独立执行 4 项 GNU Make 打包测试通过。配置、原始受管目录和来源锁无 diff。

### 完整回归与验证边界（2026-10-25）

- Windows 完整回归：`powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action run`，13:12:32–13:36:23（UTC+8），退出码 0；日志保存在 `<DepsDir>/runs/20261025-131232-456840/` 的 `regression.log` 和 `result.json`。
- 43 组 unittest 共 588 项：561 项通过，27 项按平台或测试核心能力跳过；入口中的 shell 回归通过。另有原生 Linux Kconfig 检查跳过，不能计为通过。
- 27 项跳过包括 POSIX 文件模式/符号链接、Linux 进程与锁/dnsmasq、luac/BusyBox、fw876 Linux ELF、两版 Mihomo 实际核心以及 Linux CI 强制执行的真实下载。没有添加跳过条件以绕过本次修复验证。
- 独立复核固定 Xray 26.10.21 的 `sockopt_linux.go`、`system_dialer.go` 与 finalmask 拨号链：普通用户设置 `SO_MARK` 失败仅记录日志，非 `BindError` 不终止 UDP 拨号；现有十份 fw876 补丁不修改该路径。因此 KCP 本地互通测试保留完整生成的 outbound，无需提权或删去 mark。此项为源码确认。
- 本机未执行 Linux fw876 ELF、POSIX 网络命名空间、真实 Go/UPX 交叉编译或路由器验收。Linux CI 已接入官方与 fw876 两种核心的 KCP 互通检查，实际通过以对应提交的运行结果为准。

### 首轮 Linux CI 暴露的平台差异与修正

- 提交 `6756b86` 的 [Linux 回归 40166228551](https://github.com/BlackHu-art/openwrt_release/actions/runs/40166228551) 在 Xray 配方的两项失败无写入断言处失败：导入 `managed_plugins` 新增了 `compat/__pycache__`。该轮在此终止，不能据此前置步骤通过声称完整回归或网络命名空间检查通过。
- Windows 包装器预设 `PYTHONDONTWRITEBYTECODE`，遮蔽了上述副作用。测试现显式移除子进程中的该变量；两项先按原实现复现失败，再由 helper 在导入本地模块前禁用字节码缓存后通过。保留完整目录快照断言，没有忽略缓存文件。
- 修正后定向复跑：Xray 配方 29 项、实际装载组合 4 项、fw876 来源 4 项全部通过；文档链接和 `git diff --check` 通过。后续 Linux 完整结果以修正提交关联的 Actions 运行记录为准。
