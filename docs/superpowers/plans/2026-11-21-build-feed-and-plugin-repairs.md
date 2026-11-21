# Build Feed and Plugin Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复不配套的固件/feed 输入，覆盖实际失败配方，并合入已审查的插件上游修复。

**Architecture:** 使用完整固件提交及按底座选择的 feed 锁，在生成 feed 索引前固定来源。
保留现有兼容适配器的完整输入检查，在构建副本回移必要修复，实际插件选择不变。

**Tech Stack:** Bash、Python 3.11、OpenWrt feeds/Kconfig、unittest、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-11-21-build-feed-and-plugin-repairs-design.md`

## Global Constraints

- 保留 LAN `10.0.0.1`、18 个设备、Argon/Aurora、插件/fragments 和现有五个 IPQ60xx 固件 pin。
- 保留移除 Passwall/CUPS、京东云 Docker 排除、Go >=1.27.3。
- 保留来源和派生补丁分离、未知输入拒绝、失败退出码和完整成品检查。
- 主线在当前 checkout 的 `codex/fix-feed-compat-20261121` 分支执行；上游核对可并行，只修改明确分配的文件。

## Review Focus

- 旧底座拉取新 Rust 配方：锁定兼容 feed，测试实际索引输入包含的接口。
- master/25.12 等分支配方不同：使用真实来源样本，不能只接受一个完整文件哈希。
- 已有 feed 或配置漂移：重跑核对 commit/来源，未知或重复 feed 在写入前拒绝。
- 补丁组合及重复运行：已修复副本不重复写入，未知或部分应用不能留下半套结果。
- 回归通过但真实构建失败：Linux 来源准备/defconfig 和代表目标编译独立记录。

---

### Task 1: Lock compatible core/feed inputs

**Files:** `wrt_core/feeds.lock.json`, `wrt_core/feeds_lock.py`, `wrt_core/modules/feeds.sh`, `wrt_core/compilecfg/*.ini`, `wrt_core/pre_clone_action.sh`, `build.sh`, `tests/test_feeds_lock.py`, CI/test entry points.

**Interfaces:** Preserve `update.sh REPO_URL REPO_BRANCH BUILD_DIR COMMIT_HASH DOCKER_STACK_SELECTED`.
The feed adapter consumes a local Git build tree plus the checked-in lock, writes the selected feeds configuration before update, and verifies fetched HEADs afterward.

- [x] Record immutable core/feed commits and provenance for every supported profile, preserving explicit pins.
- [x] Add failing behavior tests for exact locked fetches, unknown origins/cores, duplicate/missing entries, idempotence and stale checkout rejection.
- [x] Implement atomic configuration preparation and post-fetch verification, integrate before/after the existing feeds update.
- [x] Include lock identity in config preview/cache identity; preserve requested package selections.
- [ ] Run focused tests and actual representative source preparation/defconfig under Linux.

### Task 2: Reviewed Qt5/squeezelite variants

**Files:** `wrt_core/kconfig_compat.py`, `tests/fixtures/kconfig-compat/`, `tests/test_kconfig_compat.py`, `docs/kconfig-compat.md`.

- [x] Capture the actual master and maintenance-branch recipes with source commits/hashes.
- [x] Add failing tests using each real variant, preserving Kconfig feature semantics and package versions/dependencies.
- [x] Extend exact reviewed-input handling; preserve all-input validation before any writes.
- [x] Verify original/fixed loops, repeated application, unknown drift, partial input and failure propagation.

### Task 3: Selective upstream fixes

**Files:** Existing plugin adapters/patches and their tests; `wrt_core/modules/service_fixes.sh`; CI setup helper/workflows if the reviewed fix applies; `docs/maintenance/upstream-repairs-2026-11-21.md`.

- [x] Inventory selected plugin sources; review new commits, mark already integrated and incompatible changes.
- [x] For each accepted fix, first reproduce the affected behavior; implement the smallest backport with exact provenance and repeat/unknown-input tests.
- [x] Cover fw876 SSR runtime dependency selection, Xray Cronet linker allowance, OpenClash cache persistence, and direct netfilter dependency form when confirmed applicable.
- [x] Preserve source locks and selected functionality; refresh complete existing theme sources without importing new devices or incompatible UI migrations.
- [x] Document each reviewed source and explicit validation boundaries.

### Task 4: Integrated verification and delivery

- [x] Run focused tests, complete regression, production source integrity, all-profile config preview, document links and diff checks.
- [x] Obtain fresh whole-change review and resolve actionable findings.
- [ ] Run Linux required CI on the exact final revision; inspect failed checks and fix confirmed issues.
- [ ] Validate representative ImmortalWrt/LiBwrt builds without publishing firmware releases; report run IDs and actual outcomes.
- [ ] Report changed behavior, included upstream fixes, source identities and unverified real-device behavior.
