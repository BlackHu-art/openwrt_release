# OAF、Quickstart、OpenClash 必要上游修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有来源和配置上回移已审查的局部修复，通过回归后提交推送。

**Architecture:** 原始受管输入、维护快照及来源锁不变；新增有来源记录的补丁，仅修改构建副本。每组适配先验证完整输入、在临时副本准备全部输出，再发布；支持完整重复执行并拒绝源码漂移或不完整状态。

**Tech Stack:** Python 3.11、Bash、Lua 5.1/Lupa、Ruby 3.4、C 主机回归、Git patch。

**Spec:** 本轮用户要求及 [插件兼容说明](../../plugin-compatibility.md)、[维护流程](../../maintenance/maintenance-workflow.md)。

## Global Constraints

- 不改插件来源、固定提交、选择、设备配置或编译配置。
- 不改 `wrt_core/managed/` 原始字节、生产锁或维护快照；修复只进入派生构建副本。
- 保留 OAF 默认关闭、已有 fwx 设置和 ACL；保留 Quickstart 本地后端适配；保留 OpenClash 原有六份补丁。
- 不修改路由器，不纳入 Samba/nginx/fstab 的另一会话维护范围。
- 交付前完成针对性回归、完整 Windows 回归、来源完整性和文档检查；Linux 特有验证的状态单独记录。
- 用户已授权连续实施、验证后提交推送，无须重复请求批准。

## Review Focus

- 后续补丁漂移不能使前置补丁先写入真实构建目录。
- Quickstart 库的短读、空串 EOF 与短写必须真实执行，不能仅匹配源码。
- OAF 网络数据包、分配失败和 HTTP 边界必须通过编译后的生产函数验证。
- OpenClash 下载失败不能替换配置或提前提交 ETag；并发更新不能丢失其他缓存条目。
- 策略组重命名只修改引用目标，保留无关规则文本和现有文件名限制。

## Task 1: OAF 网络处理修复

**Files:** 新增 `wrt_core/oaf_runtime_compat.py`、`wrt_core/patches/oaf-runtime-safety.patch`、`tests/test_oaf_runtime.py` 及独立 C 回归辅助文件。

**Interfaces:** `prepare(oaf_dir, appfilter_dir)` 和等价 CLI；提供只预检模式供已有默认值修正组合调用。

- [x] 执行上游 `kenzok8/small-package@0892bf4fbaa2d4f99fe5e9c1425ced31574c965e` 与本地原始 C 源比较。
- [x] 先执行失败回归：分配失败锁释放、分段数据包、长度/HTTP 边界和 LAN 配置键。
- [x] 回移 C 正确性修复及 `fwx.global.lan_ifname`，排除版本、UI、昵称及白名单行为改动。
- [x] 接入 `update_oaf_deconfig`，验证与现有默认关闭/ACL 修正组合、重复执行和漂移拒绝。

## Task 2: Quickstart 请求与安装修复

**Files:** 新增 `wrt_core/quickstart_compat.py`、`wrt_core/patches/quickstart-runtime-safety.patch`、`tests/test_quickstart_runtime.py` 及独立 fixture。

**Interfaces:** CLI 接受 `luci-app-quickstart` 构建目录；在临时副本装载受管兼容后端，修复通过后发布三个运行文件。

- [x] 核对上游 `kenzok8/small-package@d4611b99118531f49f26a834e5ee6400e201c15a`。
- [x] 先通过 loader → 原 `fix_quickstart` 执行短写、分块响应截断和无效包名失败回归。
- [x] 回移完整发送、chunk/EOF/CRLF 校验及控制器/脚本双层包名验证，保留温度和状态适配。
- [x] 接入原构建入口，验证无效输入无安装副作用、失败传播、幂等和源码漂移时无部分写入。

## Task 3: OpenClash 订阅、ETag 与重命名修复

**Files:** 新增 `wrt_core/openclash_runtime_compat.py`、局部补丁、`tests/test_openclash_updates.py`；扩充 `tests/openclash_fixture.py` 固定完整文件。

**Interfaces:** `prepare --core <wrt_core> --package <package>` 统一预检原有六补丁及新补丁；由 `fix_openclash_compat` 调用。

- [x] 比较原作者 `373d0023c7006fee3bb66c90f40355ef02e2d682`、`4015008110e8a40b41c416677c0e7224635d9379`、`2cd5ad9847b1debcb65b9843925041305aa3c2b3`。
- [x] 先执行真实 shell/Lua/Ruby 失败回归，覆盖配置保留、核心非零、空配置、ETag 时机/并发、引用重命名和单值 groups。
- [x] 仅移植必要逻辑；保留已有 checksum/文件名保护，排除路由优先级、多 WAN、Tailscale 和 dev 新功能。
- [x] 在 scratch 中规范化并校验完整受保护文件，再顺序应用全套补丁，验证完整重复执行与未知/部分状态拒绝。

## Task 4: 统一接入、验证及交付

**Files:** 修改 `wrt_core/modules/feed_source_fixes.sh`、`wrt_core/modules/plugin_compat.sh`、`tests/test_managed_build.py`、`tests/run_all.sh`、回归 CI 路径过滤及当前维护说明。

- [x] 更新真实 loader/构建入口组合回归和测试清单；不改变编译工作流输入或设备选择。
- [x] 依次执行三组针对性测试、既有相关测试及完整 `tests/windows-tests.ps1 -Action run`。
- [x] 运行 `managed_plugins.py check`、`verify_upstream_sync.py`、`check_doc_links.py`、`git diff --check`；检查来源/配置的 Git 差异为空。
- [x] 独立检查完整 diff 与回归覆盖，修复审查发现的问题。
- [x] 记录实际命令、通过/失败/跳过和验证边界，准备精确暂存清单。

交付顺序：完成暂存审计后提交推送，核对远端提交身份及 Linux CI。提交和远端结果以 Git 记录、对应 Actions 运行和本轮交付消息为准。

## 执行记录

- 基线：`296231a9b3884f86f5c6b6d76b07f0615e459b3b`，主仓库 `master` 干净。
- 实施分工：三个互不修改共享入口的插件子任务；主任务负责调用链接入、完整验证、文档及交付。
- Windows 已有 Ruby/Node/Make/flock/Xray 依赖校验通过；发现现成 VS Build Tools C 编译器，可用于 OAF 主机 C 回归，无需下载新工具链。

- 针对性验证：OAF 18 项、Quickstart 21 项、OpenClash 29 项（含 64 种原有补丁完整组合）通过；主任务另核验真实构建入口与原有文件名保护。
- 独立审查复现并推动修正：过滤后空策略组需再次核心校验；ETag 不得根据年龄删除仍持有的锁。修正后五项定向复验通过。
- 另修正 OpenClash 发布时沿用旧 mtime 导致 prepare 缓存无法失效的问题；两项回归验证内容变化更新时间、重复准备保持时间，以及发布失败恢复原字节、权限和时间。独立复核无剩余阻断项。
- Windows 新增 venv 内 python3 同字节入口及路径校验，避免 Bash 调用系统应用别名；32 项工具回归及真实环境检查通过。
- 完整 Windows 入口于 2026-10-31 21:03:39～21:29:34 执行，`result.json` 与 `regression.log` 均确认退出码 0；46 组 unittest 共 663 项，其中 643 通过、20 项平台跳过。16 个 Shell 入口中 15 个通过，Linux Kconfig 原生检查按平台跳过。
- 本次通过 `windows_test_env.py run` 执行同一 `tests/run_all.sh`，另设置两个已校验 Mihomo 路径及 `OPENCLASH_REQUIRE_MIHOMO=1`；运行记录标识为 `20261031-210339-079610`。新增 OAF、Quickstart、OpenClash 67 项均无跳过。
- 30 个受管包完整性、上游同步不变量、14 份文档本地链接和 `git diff --check` 通过；来源、选择、设备配置及固件编译工作流无差异。Linux 特有下载、链接、核心和 namespace 检查由推送后的原有 CI 补验；不把主机回归当作固件交叉编译或路由器验证。
- 首次推送 `160bf3e` 的 Linux CI 在 OAF 主机 harness 编译失败：替身误用 `char *l4_data`，真实 `fwx.h` 为 `unsigned char *`，MSVC 接受而 GCC 拒绝混合指针减法。仅纠正替身及其边界返回类型，新增真实头文件契约回归；该契约先失败后通过，OAF 18 项在 MSVC 下通过。生产源码、补丁及断言不变，后续完整 Linux CI 核验最终提交。
