# 项目文档索引

本索引供维护者和新聊天接手使用。先确认当前分支、提交与未提交变更，再按任务选择入口。
文档说明预期行为；某次测试、CI 或固件是否成功，必须查看对应提交的执行证据。

## 日常入口

| 任务 | 入口 |
| --- | --- |
| 新电脑获取仓库、恢复测试环境、交接给其他 AI | [维护快速开始](maintenance/quickstart.md) |
| 理解设备配置、模块调用和三种源码目录 | [架构与来源](maintenance/architecture-and-sources.md)、[完整项目布局](project-layout.md) |
| 更新来源、维护补丁、安排验证与提交检查 | [维护流程](maintenance/maintenance-workflow.md) |
| 查看 CI、读取日志、定位常见故障 | [排错与 CI](maintenance/troubleshooting.md) |
| 本地编译与设备清单 | [根编译指南](../README.md) |
| Windows 测试依赖、install/check/run、日志与跳过项 | [Windows 回归说明](windows-testing.md) |

## 当前集成说明

以下文档随实现维护，具体版本和文件身份最终以源码、来源锁和测试入口为准。

- [生产受管源码](../wrt_core/managed/README.md) 与 [生产来源锁](../wrt_core/managed/sources.lock.json)：实际构建输入、完整文件集合及哈希。
- [fw876 SSR 与共享核心集成](fw876-core-migration.md)：当前 v198.2 方案、原始配方与构建副本、测试核心身份、升级及验证边界。
- [fw876 上游修复记录](fw876-upstream-backports.md)：本轮 KCP 层序、Xray UPX 复用的来源、取舍和执行证据。
- [插件兼容性](plugin-compatibility.md)：保留插件的构建接入和兼容处理；Xray 派生修订以 fw876 集成说明及实现为准。
- [OAF、Quickstart、OpenClash 必要修复](maintenance/plugin-backports-2026-10-31.md)：本轮局部回移、来源取舍、构建副本预检及回归入口。
- [归档与下载兼容](source-download-compat.md)：simple-obfs、SmartDNS 与下载错误传播。
- [Kconfig 兼容](kconfig-compat.md)：Qt5/squeezelite 循环依赖与原生解析器验证。
- [Linux 回归工作流](../.github/workflows/test_ssrplus.yml) 与 [完整回归入口](../tests/run_all.sh)：依赖准备、强制门禁和执行顺序。

Passwall1、Passwall2 已从生产输入、维护快照和构建入口移除。SSR 当前使用
`fw876/helloworld@v198.2`；旧 190 系列修复仅保留历史回归。维护工作不能根据旧评估重新引入它们。

## 参考快照与历史记录

| 文档 | 使用边界 |
| --- | --- |
| [插件源码维护区](../maintenance/plugins/README.md) | 参考快照身份、获取方式与许可证；版本表和采集时结论不能替代当前生产来源锁 |
| [SSR v198.2 迁移评估](ssrplus-v198.2-migration-assessment.md) 及 [细节目录](ssrplus-v198.2-details/) | 迁移前代码比较；其中旧生命周期/DNS 迁移建议已由当前方案替代 |
| [SSR 旧兼容说明](ssrplus-compatibility.md) | 旧 190 系列修复背景；当前生产以 fw876 集成说明为准 |
| [2026-10-17 构建诊断](build-diagnosis-2026-10-17.md) | 当次 miniupnpd 失败和耗时证据 |
| [2026-10-21 插件审计](jdcloud-plugin-audit-2026-10-21.md) | 当时配置和来源的审查记录 |
| [2026-10-24 环境耗时调查](build-environment-2026-10-24.md) | 当次 APT 环境准备耗时，不是所有慢构建的原因 |
| [设计记录](superpowers/specs/) 与 [实施计划](superpowers/plans/) | 有日期的目标、决策和执行证据；未完成复选框不能作为已完成事实 |

发现文档与代码冲突时，先记录文件、调用链及当前提交，在对应当前说明中修正；保留历史记录的时间语境。
不要把个人电脑绝对路径、私人聊天、密钥或私人 memory 作为接手所必需的信息。
