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
- 并行构建从第一次就启用 `V=s BUILD_LOG=1`，失败返回原退出码，取消整轮单线程重试。
- 保存阶段耗时、详细构建日志，并在 Actions 失败时上传日志、输出机器资源信息。
- 修复清理旧日志时将 `logs/*` 当作字面文件名的问题。

未通过移除 QuickFile、Samba 或代理功能来缩短时间，也未更改固件功能配置。Rust 的 LLVM 源码构建兼容设置暂时保留：Rust 官方构建代码说明 CI LLVM 包可能因目标不支持、历史包被删除或配置不兼容而不可用，未经 Linux 构建验证直接恢复下载可能引入新失败。后续常规构建提速应针对工具链缓存或已验证的预编译工具链评估；本次不承诺正常构建能缩短到具体时长。

验证包括旧错误复现、官方 2.3.11 源码的完整补丁链检查和脚本回归；尚未执行 Linux 下完整固件交叉编译和设备刷机验证。
