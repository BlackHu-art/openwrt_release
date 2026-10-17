# 编译指南

本仓库用于按设备配置自动拉取 OpenWrt / ImmortalWrt / LiBwrt 源码、应用自定义补丁与软件包配置，并输出固件到 `firmware/` 目录。

![截图](./tu.png)

## 1. 环境准备

推荐使用 Ubuntu LTS 或其他主流 Linux 发行版。OpenWrt 编译对磁盘空间、内存和文件系统大小写敏感性有要求，建议预留充足磁盘空间并在原生 Linux 文件系统中编译。

## 2. 安装编译依赖

```bash
sudo apt -y update
sudo apt -y full-upgrade
sudo apt install -y dos2unix libfuse-dev
sudo bash -c 'bash <(curl -sL https://build-scripts.immortalwrt.org/init_build_environment.sh)'
```

容器构建还需要已安装并可正常运行的 Docker。

## 3. 获取源码

```bash
git clone https://github.com/ZqinKing/wrt_release.git
cd wrt_release
```

## 4. 编译用法

### 交互式选择

直接运行脚本会列出当前 `wrt_core/compilecfg/*.ini` 与 `wrt_core/deconfig/*.config` 同时存在的设备配置，并提示选择构建模式：

```bash
./build.sh
```

### 直接指定设备

```bash
./build.sh <设备配置名> [debug|container|container_debug|config_preview]
```

构建模式说明：

| 模式 | 命令示例 | 说明 |
| --- | --- | --- |
| 默认 | `./build.sh x64_immwrt` | 拉取源码、应用配置、下载依赖并完整编译固件。 |
| `debug` | `./build.sh x64_immwrt debug` | 执行到 `make defconfig` 后停止，用于检查配置，不产出固件。 |
| `container` | `./build.sh x64_immwrt container` | 使用 Docker 容器执行完整构建，减少本机环境差异。 |
| `container_debug` | `./build.sh x64_immwrt container_debug` | 在 Docker 容器中执行 debug 流程并进入交互 shell。 |
| `config_preview` | `./build.sh x64_immwrt config_preview` | 只预览配置片段组合，不拉取源码、不写构建目录。 |

可通过环境变量临时追加或移除配置片段：

```bash
ADD_CONFIG_FRAGMENTS=docker_deps ./build.sh gemtek_w1701k_immwrt config_preview
REMOVE_CONFIG_FRAGMENTS=proxy ./build.sh x64_immwrt config_preview
```

GitHub Actions 的手动构建也提供 `add_fragments` 与 `remove_fragments` 输入项，语义与上述环境变量一致。

编译完成后，脚本会从 `<BUILD_DIR>/bin/targets/` 收集固件文件到仓库根目录的 `firmware/`。每次完整构建前会清理旧的目标固件文件，`firmware/Packages.manifest` 会被移除。

## 验证

```bash
bash tests/run_all.sh
```

正常构建的控制台只显示阶段、软件包进度、耗时及错误/警告摘要。失败时再输出前 5 处匹配错误的上下文和日志末尾 80 行；GitHub Actions 中放在 `Failure details` 分组内。错误上下文优先展示编译、补丁和安装错误，避免已恢复的镜像下载错误占满摘要。

完整详细输出仍从首次执行起保存在 `<BUILD_DIR>/logs/download.log`、`miniupnpd-prepare.log`、`compile.log` 和 OpenWrt 各软件包日志中。`build-times.tsv` 按“阶段、耗时秒数、退出码”记录结果。选用 miniupnpd 时先执行 prepare，尽早发现补丁失配；构建失败直接返回失败，不再自动将整个 world 改为单线程重试。GitHub Actions 成功或失败都会上传 `build-logs-*`，保留 7 天。

miniupnpd 2.3.11 的旧补丁兼容修复与真实源码验证方法见 [测试基线](tests/fixtures/miniupnpd/README.md)。2026-10-17 京东云构建的失败及耗时分析见 [构建诊断](docs/build-diagnosis-2026-10-17.md)。

## 5. 支持设备

设备配置名来自 `wrt_core/compilecfg/` 和 `wrt_core/deconfig/` 中同名文件。当前支持：

| 厂商 / 平台 | 设备 | 配置名 |
| --- | --- | --- |
| 京东云 | 雅典娜(02)、亚瑟(01)、太乙(07)、AX5(JDC版) | `jdcloud_ipq60xx_immwrt` |
| 京东云 | 雅典娜(02)、亚瑟(01)、太乙(07)、AX5(JDC版) - LiBwrt | `jdcloud_ipq60xx_libwrt` |
| 京东云 | 百里 / AX6000 | `jdcloud_ax6000_immwrt` |
| 阿里云 | AP8220 | `aliyun_ap8220_immwrt` |
| 阿里云 | AP8220 - LiBwrt | `aliyun_ap8220_libwrt` |
| Linksys | MX4200v1、MX4200v2、MX4300 | `linksys_mx4x00_immwrt` |
| Link | NN6000v2 | `link_nn6000v2_immwrt` |
| 奇虎 | 360v6 | `qihoo_360v6_immwrt` |
| 红米 | AX5 | `redmi_ax5_immwrt` |
| 红米 | AX6 | `redmi_ax6_immwrt` |
| 红米 | AX6 - LiBwrt | `redmi_ax6_libwrt` |
| CMCC（中国移动） | RAX3000M | `cmcc_rax3000m_immwrt` |
| 斐讯 | N1 | `n1_immwrt` |
| 兆能 | M2 | `zn_m2_immwrt` |
| 兆能 | M2 - LiBwrt | `zn_m2_libwrt` |
| Gemtek | W1701K | `gemtek_w1701k_immwrt` |
| Supergateway | S20M | `supergateway_s20m_immwrt` |
| x86 | X64 | `x64_immwrt` |

示例：

```bash
./build.sh jdcloud_ipq60xx_immwrt
./build.sh aliyun_ap8220_libwrt
./build.sh redmi_ax6_libwrt container
```

## 6. 配置来源

每个设备由两类文件共同定义：

- `wrt_core/compilecfg/<设备配置名>.ini`：定义源码仓库、分支、构建目录、默认配置片段、可选提交哈希和容器 SDK 镜像。
- `wrt_core/deconfig/<设备配置名>.config`：定义 OpenWrt 目标平台、设备和软件包配置。

不同设备会使用不同上游源码，例如 `VIKINGYFY/immortalwrt`、`immortalwrt/immortalwrt`、`LiBwrt/openwrt-6.x`、`padavanonly/immortalwrt-mt798x` 或本仓库维护的特定分支。`BUILD_TARGET_SDK` 未配置时，容器构建默认使用 `immortalwrt/sdk:openwrt-25.12`。

S20M 支持同步自构建上游 [`90a9591`](https://github.com/ZqinKing/wrt_release/commit/90a9591817720d7876e95b8df51e895d643eba19)，使用 `padavanonly/immortalwrt-mt798x-6.6` 的 `openwrt-24.10-6.6` 分支。配置已按该源码的设备定义修正为 `mediatek/filogic` 子目标，并加入单设备构建、发布与批量发布入口。

构建时会按顺序组合配置：

1. 设备专用 `.config`
2. `compile_base.config`
3. `wrt_core/deconfig/fragments/<name>.config` 中的有效配置片段

默认片段由 `compilecfg/*.ini` 的 `CONFIG_FRAGMENTS` 指定：

- 所有设备默认包含 `proxy`。
- IPQ60xx / IPQ807x 设备默认额外包含 `nss`。
- 只有已显式选择 Dockerman 或明确适合运行 Docker 的设备默认包含 `docker_deps`，用于预置手动安装 Docker 所需的运行依赖，避免 NAND 空间紧张或无 USB 设备被默认加入 Docker 依赖。
- 京东云的 IPQ60xx（ImmortalWrt、LiBwrt）和 AX6000 配置不再编译 Docker、Dockerman 及容器运行时，也不默认加载 `docker_deps`。

`ADD_CONFIG_FRAGMENTS` 会在默认片段后追加，`REMOVE_CONFIG_FRAGMENTS` 会从最终片段中移除对应配置片段。移除只表示“不追加这个 fragment”，不会反向修改设备 `.config` 或 `compile_base.config` 中已经写明的配置。

## 7. 三方插件

三方插件主要通过 feeds 机制加入，其中 small-package 源自：

```text
https://github.com/kenzok8/small-package.git
```

相关增删和同步逻辑位于 `wrt_core/update.sh` 编排的 `wrt_core/modules/` 静态阶段。配置片段只选择 Kconfig，不负责 clone 仓库、修改 feeds 或安装 feeds。

Argon 3.x 已内置主题设置和 `argon-config` 翻译。构建检测到上游的 `config-integrated` 标记后，移除旧版独立配置插件源码，使用主题仓库内的空兼容包保留 `luci-app-argon-config` 包名，避免文件和翻译包冲突。旧版主题仍配套独立配置插件；集成版缺少兼容包时会提前停止构建。

HomeProxy 从官方仓库更新后、最终 feeds 索引刷新和安装前，会应用 [PR #673 第一提交 `7c6ded7`](https://github.com/immortalwrt/homeproxy/commit/7c6ded7b99953c7148f3f4a2edf69a592a4f424e) 的 sing-box 1.14 配置兼容修复，并在包的 `LUCI_DEPENDS` 中补齐 `ucode-mod-math`，使选用 HomeProxy 的固件和生成的安装包都包含正确依赖。未引入该 PR 第二提交的接口选择改动。

已兼容上游 [`fadaa676`](https://github.com/immortalwrt/homeproxy/commit/fadaa676104f59ff6ace480a780a258d846d0aec)：上游已迁移 sniff 配置并移除 `sniff_override`、`independent_cache` 的界面和迁移残留，构建时自动选择新版剩余补丁，继续移除 `disable_expire` 和 resolver 中无效的 `action`，保留 300ms sniff 超时。旧版源码仍使用原补丁。翻译和规则数据更新随官方仓库拉取，无需另行复制。

同时应用以下固定提交的上游补丁：

- [PR #641 `1a32fca`](https://github.com/immortalwrt/homeproxy/commit/1a32fca68ecddf129f7a29e254b6cfdfc3cb3d84)：让仅修改 ACL 域名列表也能触发应用/重启，补齐代理域名路由，并通过 dnsmasq 将直连域名解析结果写入 nft 集合。现有 TUN 链未读取该动态直连集合，此补丁不代表 TUN 模式的完整修复。
- [PR #672 `10f4244`](https://github.com/immortalwrt/homeproxy/commit/10f4244d2e3775b29207c180c3adca1257e1f79f)：缓存 sing-box 版本和构建特性，减少 LuCI 首次页面加载时的探测开销。安装或首次启动时预热缓存，二进制身份变化时重新探测，内核模块与工具能力仍实时检查。

补丁保存在 `wrt_core/patches/homeproxy-*.patch`。构建时从两个兼容补丁版本中选择一个，再预检 ACL 和特性缓存补丁，全部通过后才修改源码；已应用的补丁逐份跳过。遇到无法匹配的上游源码变化会停止构建，需检查并更新补丁，避免静默编出有兼容问题的 HomeProxy。

## 8. 项目结构说明

- `build.sh`：主编译入口，负责设备选择、模式选择、配置组合、容器构建和固件收集。
- `firmware/`：完整构建后的固件输出目录，由脚本自动创建和刷新。
- `wrt_core/build_container.sh`：容器内构建入口。
- `wrt_core/update.sh`：源码更新、feeds 调整、软件包同步和补丁应用主流程。
- `wrt_core/pre_clone_action.sh`：GitHub Actions 预克隆辅助脚本。
- `wrt_core/compilecfg/`：设备构建元信息 `.ini`。
- `wrt_core/deconfig/`：设备和共享默认配置 `.config`。
- `wrt_core/deconfig/fragments/`：可组合配置片段。
- `wrt_core/modules/`：模块化脚本，包括仓库准备、网络重试、feeds/custom_feed、源码修正、LuCI 修正、服务修正、验证、Docker、CUPS 等静态职责模块。
- `wrt_core/patches/`：补丁、默认设置、Wi-Fi 初始化、NSS 诊断、PBR 规则和其他构建时注入文件。

## 9. OAF（应用过滤）功能使用说明

使用 OAF（应用过滤）功能前，需先完成以下操作：

1. 打开系统设置 → 启动项 → 定位到「appfilter」
2. 将「appfilter」当前状态从已禁用更改为已启用
3. 完成配置后，点击启动按钮激活服务
