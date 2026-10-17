# 京东云 IPQ60xx 编译失败与耗时诊断

对象：[GitHub Actions #96](https://github.com/BlackHu-art/openwrt_release/actions/runs/39003863804/job/117312206779)，提交 `ca5dd72`，配置 `jdcloud_ipq60xx_immwrt`。以下时间均为北京时间，来自该任务的完整日志。

| 时间 | 事件 |
| --- | --- |
| 12:47:14 | 任务启动，runner 分配 4 核、约 15 GiB 内存 |
| 12:55:36 | 缓存未命中，开始 Build Firmware |
| 13:00:35 | 开始 tools/compile |
| 13:14:46 | 开始 toolchain/compile |
| 13:47:16 | 开始 package/compile |
| 13:47:45 | 开始 rust/host-compile |
| 14:37:33 | miniupnpd nftables 变体首次失败 |
| 15:49:25 | 第一轮 world 返回 Error 1，随后自动单线程重试 |
| 16:17:03 | 重试在同一 miniupnpd 补丁处失败，任务退出码 2 |

本次任务总计约 3 小时 30 分钟，Build Firmware 约 3 小时 21 分钟，并非五小时。此前 [10 月 14 日成功任务](https://github.com/BlackHu-art/openwrt_release/actions/runs/38412814943/job/115466584584) 的 Build Firmware 确实用了 4 小时 40 分钟，同样没有命中缓存。

## 失败原因与修复

miniupnpd 已升级为 2.3.11，但 packages feed 保留了旧 `020-descr-filter-fix.patch`。日志明确显示该补丁在 `upnppermissions.c` / `.h` 多处 `Hunk FAILED`。独立源码验证还发现后续 `030` 已被源码吸收、`040` 上下文过期，因此仅删除第一份失败补丁不足以修复。

修复保留 2.3.11 的权限解析器和私网地址修复，按版本和原始补丁哈希移除已合入的 `020` / `030`，刷新 `040` 的上下文，并保留日志、XML 兼容与租约设置。遇到未识别的补丁内容提前报错，避免覆盖新的上游修复。

## 为什么耗时长

1. **冷构建。** 本次 `Cache Dependencies` 明确输出 `Cache not found`。tools 阶段约 14 分钟、toolchain 阶段约 32 分钟，之后才进入软件包构建。缓存目前只有 `.ccache` 与 `staging_dir`，没有 `dl` 和 `build_dir`，不能等同于完整增量编译。
2. **重型构建依赖。** QuickFile 2.0.8 已改为 Rust 源码构建；本仓库的 `fix_rust_compile_error` 强制 `llvm.download-ci-llvm=false`，Rust 主机构建因此还需源码编译 LLVM。Go、Samba、Python 等也带来编译成本。首次并行日志没有各包完成时间，不能把 72 分钟等待全部归因于 Rust。单线程重试中 QuickFile 本体约 3 分 39 秒，Samba 本体约 5 分 14 秒；不能把这些数值当作包含工具链的总成本。
3. **失败反馈过晚。** 首次 miniupnpd 报错后，仍要等待已启动的并行任务退出，约 72 分钟后 world 才返回失败。旧脚本又单线程重试整个 world，额外花约 27 分 38 秒才再次触发同一错误。
4. **缓存不能保证留存。** 检查时仓库缓存列表没有京东云条目，但历史成功任务确实保存过京东云缓存。现有证据只证明该缓存已不在，无法区分配额淘汰、人工删除等原因。失败任务也不会由现有 `actions/cache` 的成功后置流程保存本次缓存。

## 本次落地与边界

- miniupnpd 在完整编译前先执行 prepare，避免过期补丁等到重型软件包构建后才暴露。
- 并行构建从第一次就启用 `V=s BUILD_LOG=1` 保存完整日志；控制台显示简洁进度，失败时输出错误上下文和末尾日志。失败返回原退出码，取消整轮单线程重试。
- 保存阶段耗时、详细构建日志，并在 Actions 失败时上传日志、输出机器资源信息。
- 修复清理旧日志时将 `logs/*` 当作字面文件名的问题。

未通过移除 QuickFile、Samba 或代理功能来缩短时间，也未更改固件功能配置。Rust 的 LLVM 源码构建兼容设置暂时保留：Rust 官方构建代码说明 CI LLVM 包可能因目标不支持、历史包被删除或配置不兼容而不可用，未经 Linux 构建验证直接恢复下载可能引入新失败。后续常规构建提速应针对工具链缓存或已验证的预编译工具链评估；本次不承诺正常构建能缩短到具体时长。

验证包括旧错误复现、官方 2.3.11 源码的完整补丁链检查和脚本回归；尚未执行 Linux 下完整固件交叉编译和设备刷机验证。

## 后续任务 #97：Argon 3.0 安装冲突

[GitHub Actions #97](https://github.com/BlackHu-art/openwrt_release/actions/runs/39017510278/job/117352554249) 使用修复后的提交 `cae14b9`。Build Firmware 从 16:35:23 持续到 19:26:06，耗时 2 小时 50 分 43 秒。本次 `miniupnpd-prepare` 用时 8 秒、退出码 0，随后 miniupnpd 2.3.11 成功生成 IPK 并安装进 rootfs，确认上一处补丁问题已通过。

新的失败发生在 `package/install`：opkg 报告 `luci-app-argon-config` 与 `luci-theme-argon` 的 9 个文件冲突，包括设置页、RPC、菜单、ACL 和品牌资源；继而无法安装旧配置包及其中文翻译，返回 Error 255，最终 world 返回 2。

根因是 [Argon 3.0 上游源码 `539e3e1`](https://github.com/jerrykuku/luci-theme-argon/tree/539e3e1db56b2348c3655615540e45638b797c73) 已集成配置功能和 `argon-config` 翻译，脚本仍同时拉取旧独立配置仓库 `445af53`。上游已提供 `compat/luci-app-argon-config` 空迁移包，供旧包名继续使用；不能再把独立仓库的运行文件安装到新主题上。

修复在 `update_argon_config` 检测上游 `root/usr/share/argon/config-integrated` 标记，确认兼容包存在后清理旧独立配置源码，保留主题内的兼容包让后续 feeds 索引发现。旧版主题继续使用原独立配置源。主题或兼容包缺失时提前报错。主题设置、中文翻译及现有固件功能选择均保留。

验证先复现旧逻辑的重复文件归属，再检查新旧主题、残留源码清理、重复执行和失败保护；`bash tests/run_all.sh` 的 10 个检查脚本全部通过。对上述两份真实上游源码的独立验证确认：日志中的 9 个冲突路径均存在；修复后无重复运行文件，主题源码逐文件哈希未改变，中文翻译仍在。执行该固件固定源码的 feeds 文件扫描规则和原始 `scan.awk`，确认能发现主题及其嵌套兼容包。此结果不等同于完整 feeds 元数据生成、Linux 固件交叉编译或设备运行验证；完整 CI 仍需使用本次修复后的提交另行执行。
