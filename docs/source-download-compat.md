# 源码归档与下载兼容

2026-10-24 的[京东云构建 40062153515](https://github.com/BlackHu-art/openwrt_release/actions/runs/40062153515) 已通过 SSR 源码准备，在 simple-obfs 下载归档校验时失败。本文记录相关兼容修复及复验方式。

## 来源和归档身份

原始受管配方仍是 `fw876/helloworld@45893d778767f3bdb2fcb6e873cf8f9a667d94d4`，源码指向 `shadowsocks/simple-obfs@486bebd9208539058e57e23a12f23103016e09b4`，libcork gitlink 为 `f02984545061c924808e4b9ea7cc6749a41f1979`。版本仍为 `0.0.5-r2`，插件来源、提交、选择和编译配置不变。

原始 `PKG_MIRROR_HASH` 为 `7a0154d2de18373e52783d1b64cf5204471049c2d2c64f0b3323d7f430aa4275`。失败日志显示：镜像文件不匹配后，按固定提交重新拉取主仓库与子模块，两次生成相同的新哈希。清缓存不能解决这个问题。

独立核验没有采用日志中的归档作为输入，而是重新获取两个固定 Git 提交，以 Git tree / blob 校验路径、内容、模式和子模块身份，再独立组装 GNU tar：

- 279 个普通文件，321 个归档条目；归档根目录 `simple-obfs-0.0.5`。
- 时间戳为主提交的 `1566028858`，目录模式 `0755`，文件模式来自 Git；所有 owner/group 为 0。
- 当前下载框架移除根 `.git` 与 `.gitmodules`，保留子模块 `libcork/.git` 指针文件；独立清单按实际框架精确核对该行为。
- 未压缩 tar SHA256：`369a65861e5046a1fc2be77f6426bd2ea262afabbcbbef679cf7898ce434248b`。
- XZ 多线程容器格式 `-7e -T0`，218444 字节，SHA256：`da5af052265fbfba7a11ee4195257f9bc13f44d054d8fdcbace0639360870035`，与 CI 两次干净重建一致。

归档字节与打包方式有关：单线程 XZ 会产生 `be5d0534ee8d373b741c9d543ecadfa79662ade5626c5d3ab33e804a60836950`。本次构建恢复了 OpenWrt host xz 5.8.3，而 Ubuntu 24.04 系统包实际为 5.4.5，两者默认线程格式不同。构建副本仅为本包导出 `XZ_OPT=-T0`，使有无 host 工具缓存都使用同一归档格式；不修改全局下载函数或固件编译配置。独立重建关闭 Git 的 Windows 自动换行转换。Windows 上的独立重建不能替代 Linux 下载流程执行。

[`simple_obfs_compat.py`](../wrt_core/simple_obfs_compat.py) 只在构建副本修改这个已验证的哈希并固定本包的 XZ 容器格式。适配前检查原始包和构建包的完整文件集合、配方及补丁；未知变化拒绝，重复执行不重写。原始受管源码和来源锁保留上游字节，不使用 `skip` 或关闭校验。

## 下载失败传播

固定固件源码 `VIKINGYFY/immortalwrt@3fd1e27a511851b41cf082b067b60099e8e026c4` 的 `include/toplevel.mk` 使用分号串联四组下载，前面的失败可能被最后成功的命令覆盖。本次 `package/download` 失败后仍执行 `target/download`，最终 `make download` 返回 0，进入完整编译。

[`download_compat.py`](../wrt_core/download_compat.py) 在下载前精确识别该上游块，给每个递归 Make 命令追加 `|| exit $$?;`。下载顺序、并发数、SDK 分支及 flock/zstd 前置依赖保留；未知、重复或额外下载 recipe 会被拒绝。真实失败退出码经 [`build_steps.sh`](../wrt_core/modules/build_steps.sh) 传播，不进入后续 prepare/compile。镜像尝试失败后成功恢复不会被错误判为总失败。

本次环境准备约 5 分 31 秒，下载阶段 76 秒但错误返回 0，编译阶段 8058 秒后失败。Rust host 本身成功完成，用时约 7610 秒；长时间等待来自已启动的并行编译任务，并不是 Rust 编译错误。

## 回归和复跑

- [`test_simple_obfs_compat.py`](../tests/test_simple_obfs_compat.py)：真实装载、生产调用、幂等、漂移拒绝和原始源码保护。
- [`test_download_compat.py`](../tests/test_download_compat.py)：真实 GNU Make 执行固定上游块，复现旧行为；验证四组下载各自失败时退出、后续目标和 compile 未执行，以及成功、镜像恢复、未知规则和重复执行。
- [`test_simple_obfs_download.py`](../tests/test_simple_obfs_download.py)：获取并校验固定框架的真实 `download.mk`、下载程序和镜像清单；原始配方必须失败，适配后干净下载必须成功，故意错误哈希仍必须失败。独立获取 Git blob，逐文件核对下载产物，并独立重建为相同归档。

Linux CI 设置 `REQUIRE_SIMPLE_OBFS_DOWNLOAD=1` 并执行完整入口，缺少必需下载工具或框架内容漂移会失败。在具备 GNU make、Git、Perl、curl、flock、GNU tar、xz、Python 3 的 Linux 环境，可单独执行：

```bash
REQUIRE_SIMPLE_OBFS_DOWNLOAD=1 python3 tests/test_simple_obfs_download.py -v
```

测试为包下载建立最小构建变量和包编译目标替身，并在临时 fixture 中清空公共镜像列表，保证每次实际走固定 Git 来源的重新打包，避免公共镜像以后补齐旧包导致原哈希失败用例失效。生产镜像列表和来源保持不变。源码配方、下载规则、下载程序、Git 获取、归档和哈希检查均实际执行。它不进行目标架构交叉编译或路由器启动测试。Windows 完整复跑见 [Windows 测试说明](windows-testing.md)。

## SmartDNS WebUI 固定提交传递

[构建 40076155141](https://github.com/BlackHu-art/openwrt_release/actions/runs/40076155141) 的 simple-obfs 下载已经成功，随后在 SmartDNS WebUI 下载失败。此次下载失败正确终止流程，没有继续进行固件编译。

SmartDNS 配方来自现有 `ZqinKing/openwrt-smartdns`；在这次下载问题核验时，维护快照 `cdf0de1d3e64984ea2c56ec873f233495ddb1de0` 的 Makefile 与当时上游内容一致。配方使用 `VERSION` 传递 WebUI 提交号，而当前下载框架只读取 `SOURCE_VERSION`。实际命令变为 `--version=""`，Git 回退拉取默认 `main`，生成错误版本的真实源码归档。

独立读取固定提交的 Git tree/blob，并分别核对 `git archive`、GitHub codeload 与 GNU tar/gzip 重建：

| 项目 | 保留的固定源码 | 失败时下载的默认 main |
| --- | --- | --- |
| 提交 | `3261c18b1b93d841e86d9e727557109ae71d71cd` | `1c06fee693434ec7c71f06010d3f87416baba9f0` |
| 文件数 | 109 | 114 |
| gzip 字节数 | 724404 | 730252 |
| SHA-256 | `4401734712dd034eb1088ce440d1bc64d053dfcd6f63f66c08cd48ab68593042` | `88adb092ed7b0dc22b3964249f4969870d3b462c4d924aceb18784c0f664f16e` |

因此原始 `MIRROR_HASH` 正确，不能改成错误默认分支的哈希。固定源码 tree 为 `190f76f34cfda865389b27e8f69887aa6a64edc3`，时间戳为 `1766583635`，151 个归档条目；GNU tar SHA-256 为 `a203faeeb55271853270e0e84907d29d4e32043cf1bc86f4e45a4e78ff92816f`。GNU gzip 使用 `-nc`，没有文件名或当前时间信息。

[`smartdns_compat.py`](../wrt_core/smartdns_compat.py) 在 `update_smartdns` 获取并核对下述固定包装提交后、现有补丁和 CC 修正前执行，在构建副本修正 WebUI 提交字段，并在已有 `CONFIG_PACKAGE_smartdns-ui` 为 y/m 时注册 WebUI 下载。它不升级主程序版本或源码提交。原始维护快照不修改；未知 Makefile 漂移明确失败，错误经源码准备阶段传播。

[`test_smartdns_download.py`](../tests/test_smartdns_download.py) 用真实 `download.mk` 展开原配方，复现空提交号和未选 UI 仍下载；修正后验证 unset/n/y/m，以及主程序下载提交保留。Linux 必需门禁执行 WebUI y/m 的真实干净下载、逐成员 Git blob 核对、独立归档字节比较，以及错误哈希拒绝；核心归档覆盖范围见下节。测试不执行 Rust/Node 编译或目标架构交叉编译。

```bash
REQUIRE_SMARTDNS_DOWNLOAD=1 python3 tests/test_smartdns_download.py -v
```

框架和源码身份详见 [SmartDNS 下载 fixture](../tests/fixtures/smartdns-download/README.md)。循环依赖修复另见 [Kconfig 兼容说明](kconfig-compat.md)。

## SmartDNS 包装来源固定

2026-10-25 的[构建 40170792954](https://github.com/BlackHu-art/openwrt_release/actions/runs/40170792954/job/121101615745) 在源码准备阶段报出 `SmartDNS build source has unreviewed drift: Makefile`。同日北京时间 14:38，上游提交 [`b4a7fa1`](https://github.com/ZqinKing/openwrt-smartdns/commit/b4a7fa1dba3ffe0c9cb17ab32c492277007cd660) 将默认分支配方升级为 48.4。此前浅克隆取得移动后的 HEAD，严格校验主动拒绝了尚未审查的新配方；这不是 WebUI 归档哈希错误，也不是移除 SmartDNS 的理由。

[`update_smartdns`](../wrt_core/modules/package_source_updates.sh) 继续使用原 `ZqinKing/openwrt-smartdns` 仓库，在克隆后 fetch 并 checkout 已审查的完整提交 `cdf0de1d3e64984ea2c56ec873f233495ddb1de0`，核对实际 HEAD 后才执行兼容脚本、优化补丁和 CC 修正。获取、检出或身份核对失败时终止准备，不回退到默认分支。该提交保持核心配方 `1.2025.47-r1`、核心源码 `136c0c2690138d6dedd8b520281aafe49112643f` 及上文 WebUI 归档身份。SmartDNS 保留，LuCI 仍从原 `pymumu/luci-app-smartdns` 来源获取，插件选择和编译配置不变。

未来升级需要一起审查包装提交 pin、原始维护快照及清单、核心和 WebUI 归档身份、兼容脚本基线、优化/CC 补丁与相应回归。不能只移动 pin、接受新哈希或跳过严格校验；来源准备通过也不代表 Rust/Node、目标架构编译或路由器运行已经通过。

## SmartDNS 核心使用固定 codeload 归档

2026-11-21 两个完整京东云构建
[ImmortalWrt 44871843193](https://github.com/BlackHu-art/openwrt_release/actions/runs/44871843193)
和 [LiBwrt 44871845589](https://github.com/BlackHu-art/openwrt_release/actions/runs/44871845589)
均在核心 `smartdns-1.2025.47.tar.zst` 下载时停止，尚未进入固件编译。
原配方要求 `5ef82ea81d5f627f52171e3b487331ecdd270554555cbff3d291590e19f4658d`，
镜像均未提供文件；按原固定提交检出并打包后，两者实际得到
`d7e1490986c80730b63b9eb086f3962704db5634c1f23d7fdc47efd171996f4b`。
此前必需下载测试只实际获取 WebUI，核心仅检查命令展开，未覆盖这条失败路径。

独立读取核心提交 `136c0c2690138d6dedd8b520281aafe49112643f` 的全部 445 个 Git blob，
以 GNU tar 1.35 / zstd 1.5.7 重建，得到与失败日志完全相同的 `d7e149…`。
原包装仓库的生产脚本使用未固定版本的 snapshot SDK 打包工具，没有记录其版本；
原始生产任务日志已过期，因此无法确定原 `5ef82e…` 的具体打包环境。
本次没有把日志中的新哈希直接写回 zstd 配方，也不把差异错误归因于已经证明的单一版本变化。

采用已合并的上游
[`1db3543cfaa397cd1115b0479416f73062711a63`](https://github.com/pymumu/openwrt-smartdns/commit/1db3543cfaa397cd1115b0479416f73062711a63)
中的核心归档获取方式，直接下载完整提交对应的 codeload tar.gz，按固定 `PKG_HASH` 校验。
仅回移归档方式，不采用该上游提交附带的核心 / WebUI 升级。
包装原始快照 `cdf0de1…`、核心版本 `1.2025.47-r1`、核心提交 `136c0c2…`、
WebUI `3261c18…` 与其原有 gzip 哈希、优化补丁和编译器设置均保留。

固定核心归档身份：

| 项目 | 已独立核对的值 |
| --- | --- |
| 下载来源 | [codeload 完整提交归档](https://codeload.github.com/pymumu/smartdns/tar.gz/136c0c2690138d6dedd8b520281aafe49112643f) |
| 本地归档名 | `smartdns-136c0c2690138d6dedd8b520281aafe49112643f.tar.gz` |
| SHA-256 | `fd7bfb126ba15764d89a3a57efbea67602105a7bf394f81b7b5dd81693ddc5cb` |
| gzip 字节数 | 859558 |
| Git tree | `4f7381b2b6778f5f6b96d7e2dbdf7167753d2b52` |
| 内容 | 445 个文件，546 个归档条目，无子模块或符号链接 |
| 时间戳 | `1769178721`，所有条目对应固定提交时间 |

核对不依赖归档中的自报哈希：预期路径、内容和可执行属性直接从固定 Git 对象读取。
codeload 的模式使用 Git archive 默认 `tar.umask=0002`，普通文件为 0664，可执行文件 / 目录为 0775；
所有 uid/gid 为 0，名称为 root，PAX comment 对应完整 Git 提交。
`PKG_BUILD_DIR` 同步指向归档实际根目录，真实优化补丁可以在该目录正常定位全部源文件。

新的 `SmartDnsCoreDownload` 纳入现有 `REQUIRE_SMARTDNS_DOWNLOAD=1` 必需入口：
分别使用五个旧 IPQ60xx 所用 `3fd1e27a` 和 LiBwrt `000a4e74` 的真实下载框架进行干净下载，
逐文件比较全部 Git blob、模式与元数据，检查解包目录，并依次实际应用优化和运行修复补丁；
随后故意提供错误 SHA-256，要求实际下载器报告已下载字节的正确哈希并拒绝发布文件。
原 WebUI 选择 / 固定提交 / 真下载检查继续执行。原始维护文件不修改，完整配方漂移检查仍生效。

本地 macOS 实际 HTTP 下载与完整内容核对已通过；使用原生编译的文件锁辅助程序进行这一额外实验，
不代表 Linux 门禁已通过。最终 Linux CI 和完整固件构建结果需要分别确认。

同一核心提交也接入三项运行修复。退出时先完成服务端清理再释放客户端资源。
反复设置主 DNS 时，已有的同一 DHCP 选项不再追加。停止时只删除 SmartDNS 自己添加并记录的选项，
旧版本没有记录的条目会保留。界面显式关闭过期缓存时，启动脚本生成 `serve-expired no`，
核心按该设置处理缓存、响应有效时间和 IPv4／IPv6 择优。未配置该选项时沿用核心默认值。
回归运行生产函数及初始化脚本中的相关逻辑，通过受控边界复现旧问题并核实修复后的行为。
[退出顺序](https://github.com/pymumu/smartdns/commit/b6139a199232140447aff6c4ec111c222ac84993)、
[DHCP 选项](https://github.com/pymumu/smartdns/commit/21c940edc65520849ba03544c5cf8d9cf326e680)、
[过期缓存](https://github.com/pymumu/smartdns/commit/1006f640d50f1e2951e13d3e740813cc76a6739e)、
[设置传递](https://github.com/pymumu/smartdns/commit/fbe166d7249ef2ad360cc719def8f2f9eb93e55c)。
