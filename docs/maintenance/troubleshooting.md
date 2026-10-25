# 排错与 CI

先确认失败运行的 head SHA、设备、输入参数、run attempt 和首个失败步骤。网页不是必要入口；
可安装 GitHub CLI 后使用下面的只读命令，私有资源按 CLI 提示登录，不把令牌写入仓库。
参数说明见官方手册：[run list](https://cli.github.com/manual/gh_run_list)、
[run view](https://cli.github.com/manual/gh_run_view)、[run download](https://cli.github.com/manual/gh_run_download)。

```powershell
gh run list --repo BlackHu-art/openwrt_release --workflow test_ssrplus.yml --limit 10
gh run view <run-id> --repo BlackHu-art/openwrt_release
gh run view <run-id> --repo BlackHu-art/openwrt_release --log-failed
gh run view <run-id> --repo BlackHu-art/openwrt_release --json headSha,event,status,conclusion,jobs
gh run download <run-id> --repo BlackHu-art/openwrt_release --pattern 'build-logs-*' --dir .ci-logs
```

把 `<run-id>` 换为实际 ID；查看重跑时同时核对 attempt，必要时给 `gh run view` 指定 `--attempt`。
`.ci-logs` 是临时本地目录，不提交日志。日志制品通常保留 7 天，过期后 API 成功也不能恢复已删除内容。
没有 `gh` 时，可在 PowerShell 读取公共 GitHub API：

```powershell
$ciHeaders = @{ Accept = 'application/vnd.github+json' }
$ciRuns = Invoke-RestMethod -Headers $ciHeaders -Uri 'https://api.github.com/repos/BlackHu-art/openwrt_release/actions/workflows/test_ssrplus.yml/runs?per_page=10'
$ciRuns.workflow_runs | Select-Object id,run_attempt,head_sha,event,status,conclusion,html_url
```

下载日志/API 可能要求认证；认证失败、限流和过期制品应分别记录，不能当成没有执行过 CI。
这些命令是操作模板，文档本身不代表某次远端检查已通过。

## 哪些动作会触发什么

| 工作流 | 触发方式与作用 |
| --- | --- |
| [test_ssrplus.yml](../../.github/workflows/test_ssrplus.yml) | 匹配 paths 的 push/PR 自动运行，也支持手动与其他工作流调用；当前为全项目回归门禁，名称不代表仅测试 SSR |
| [build_wrt.yml](../../.github/workflows/build_wrt.yml) | 手动指定设备与可选 fragments；先通过回归，再构建，固件上传为 Actions artifact |
| [release_wrt.yml](../../.github/workflows/release_wrt.yml) | 手动或被调用；先通过回归，再构建并发布 GitHub Release，另含旧发布清理逻辑 |
| [release_wrt_all.yml](../../.github/workflows/release_wrt_all.yml) | 手动批量调用单设备发布流程；每个设备仍受回归门禁约束 |

普通 push 不自动开始完整固件编译；仅改文档也可能不命中回归 paths。
手动构建/发布时必须核对执行 ref、`model`、`add_fragments` 和 `remove_fragments`。
发布会写入远端 Release 和标签，不能把它当作读取 CI 的排错操作。

## 根据阶段找证据

| 现象 | 检查入口与处理方向 |
| --- | --- |
| Windows 找不到工具、运行失败、依赖路径不一致 | 先执行 `-Action check`；按 [Windows 说明](../windows-testing.md) 修复后显式 install；不要取消哈希/必需依赖检查 |
| Windows 通过而 Linux 的“失败无写入”断言出现 `__pycache__` 差异 | Windows 包装器设有 `PYTHONDONTWRITEBYTECODE`；应在子进程移除该环境变量后复现。要求无写入的适配脚本须自行禁止本地模块导入缓存，不能忽略快照中的新增文件来通过测试 |
| 来源校验、权限或 SSR 翻译链接拒绝 | 看 [受管来源](../../wrt_core/managed/README.md) 和 [fw876 链接说明](../fw876-core-migration.md)；区分原始输入文本与实际 Linux 链接，不用普通复制绕过 loader |
| 补丁不匹配、未知源码或部分应用 | 记录目标来源 SHA 和失败补丁，比较完整基线与适配后文件；按 [维护流程](maintenance-workflow.md) 重新审查 |
| 下载哈希错误，或下载失败后继续编译 | 看 [归档与下载兼容](../source-download-compat.md)；先确认提交字段、归档格式和真实失败退出码，不根据错误默认分支改哈希 |
| defconfig 出现 Qt5/squeezelite 循环或包被重新选入 | 看 [Kconfig 说明](../kconfig-compat.md)、`.config.requested`、最终 `.config` 和选择检查；不能忽略循环后直接发布 |
| 环境准备很慢 | 对比当次 APT/网络日志及阶段时间；[历史耗时调查](../build-environment-2026-10-24.md) 仅说明一次 APT 瓶颈 |
| 编译失败或控制台摘要不足 | 下载对应 `build-logs-*`，结合 `download.log`、`miniupnpd-prepare.log`、`compile.log`、包日志与 `build-times.tsv` 定位首个实际错误 |

`<BUILD_DIR>/logs/` 保存完整阶段日志，控制台只显示摘要；镜像下载失败后恢复可能不是最终失败原因。
[2026-10-17 诊断](../build-diagnosis-2026-10-17.md) 和旧 SSR 记录用于理解历史问题，不能直接套用到新来源。
CI 配置、源码解析、主机回归均不能代替完整固件、保留配置升级和路由器 DNS/IPv6/UDP 实测。
