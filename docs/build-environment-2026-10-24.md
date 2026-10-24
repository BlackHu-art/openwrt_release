# 2026-10-24 京东云构建环境耗时调查

本次 `jdcloud_ipq60xx_immwrt` 发布任务总耗时约 3 小时 51 分钟，
其中环境准备占 3 小时 42 分钟。主要时间消耗在 Ubuntu 软件包下载，
与 SSR 回归测试或软链接校验无关。

- [失败任务 39989251302](https://github.com/BlackHu-art/openwrt_release/actions/runs/39989251302)
- [构建任务及原始日志](https://github.com/BlackHu-art/openwrt_release/actions/runs/39989251302/job/120537982845)
- [对应提交 ac82971](https://github.com/BlackHu-art/openwrt_release/commit/ac82971d0bee5223632203daa3ff0c7a726d7a51)

本记录依据 GitHub Actions API 的阶段时间与构建日志。
下表时间均为北京时间（UTC+8），日期为 **2026-10-24**。

## 阶段耗时

| 阶段 | 开始—结束 | 耗时 |
| --- | --- | --- |
| SSR 回归门禁 | 00:44:19—00:47:32 | 3 分 13 秒 |
| 构建 runner 初始化 | 00:47:37—00:48:15 | 38 秒 |
| Free Disk Space | 00:48:15—00:51:01 | 2 分 46 秒 |
| Build System Setup | 00:51:01—04:33:14 | **3 小时 42 分 13 秒** |
| Checkout | 04:33:14—04:33:18 | 4 秒 |
| Pre Clone | 04:33:19—04:33:24 | 5 秒 |
| Cache Dependencies | 04:33:24—04:33:57 | 33 秒 |
| Build Firmware | 04:33:59—04:34:53 | 54 秒，失败 |

整个任务从 00:44:14 到 04:34:57，共 **3 小时 50 分 43 秒**。
`Build Firmware` 在源码准备阶段报告：

```text
SSR artifact verification failed: source must not use symlinks: po/zh-cn
```

这是环境准备完成后的独立兼容问题；此前没有进行数小时的固件编译。

## APT 下载证据

[当时的工作流](https://github.com/BlackHu-art/openwrt_release/blob/ac82971d0bee5223632203daa3ff0c7a726d7a51/.github/workflows/release_wrt.yml#L85-L93)
通过 `curl` 下载并执行 ImmortalWrt 的通用
`init_build_environment.sh`。日志中的实际命令与结果如下：

| 命令 | 安装范围 | 日志记录的下载量、耗时与均速 |
| --- | --- | --- |
| `apt full-upgrade -y` | 升级 120 包、新装 10 包，含 Azure 内核及模块 | `Fetched 493 MB in 1h 13min 38s (112 kB/s)` |
| `apt install -y ack antlr3 asciidoc ... xmlto ...` | 新装 307 包，包含 TeX、Java 和文档处理依赖 | `Fetched 660 MB in 2h 16min 34s (80.6 kB/s)` |
| `apt install -y golang-1.25-go` | 新装 Go 与配套源码包 | `Fetched 41.3 MB in 6min 0s (115 kB/s)` |

三段下载累计 **3 小时 36 分 12 秒，占环境准备时间的 97.3%**。
慢速下载记录均指向 `http://azure.archive.ubuntu.com/ubuntu`。

最长相邻日志间隔发生在 01:00:30—01:41:16：日志先记录下载
`linux-modules-7.0.0-1017-azure`（148 MB），随后才进入下一包，间隔约
40 分 47 秒。`texlive-bibtex-extra`（79.1 MB）、
`texlive-lang-greek`（79.2 MB）等包也分别出现约 20 分钟、19 分钟的下载区段。
这些间隔与 APT 自身汇总的低下载速率一致。

## 原因与证据边界

本次 runner 位于 Azure `westus`，Ubuntu 镜像路径持续低速。
同一任务中，`apt.llvm.org` 的 30.7 MB 下载达到 105 MB/s，
Yarn 的 896 kB 下载达到 12.1 MB/s，GitHub 源码拉取只需数秒。
因此证据指向该 runner 到 Ubuntu 镜像的传输路径；
**无法仅凭日志区分镜像负载、限速或具体网络链路故障**，也不能保证下一次仍然低速。

调查时读取的
[上游初始化脚本](https://build-scripts.immortalwrt.org/init_build_environment.sh)
包含全系统 `full-upgrade`，通用依赖安装没有设置
`--no-install-recommends`。这些行为与本次日志中的命令吻合，
使低速镜像传输的影响被大量系统升级和额外依赖进一步放大。
远端脚本没有固定版本，实时内容不应视为本次执行脚本的完整历史快照；
本次执行行为以上述日志为准。

脚本没有下载重试循环，日志也未出现网络失败后的反复重试。
下载初始化脚本及网络检测不到 1 秒，清理磁盘不到 3 分钟，
均不是本次长耗时的主要来源。

## 后续优化建议

1. 单独维护 CI 所需的主机依赖清单，避免每次对临时 runner 执行全系统升级。
2. 评估使用 `--no-install-recommends`，显式保留编译必需依赖，减少 TeX 等额外包；
   改动后应验证完整固件构建，不能仅凭安装命令成功判断依赖齐全。
3. 给下载增加明确超时、有限重试和分段耗时日志；持续有数据传输的低速请求
   未必触发普通连接超时，必要时单独设置阶段总时长上限。
4. 若复现同一镜像低速，再比较候选镜像的实际包下载速度，依据测量选择回退方案。

**本轮只记录原因，未改变构建主机准备流程、插件来源、插件选择或编译配置。**
