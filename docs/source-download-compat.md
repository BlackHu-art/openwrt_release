# 源码归档与下载兼容

2026-10-24 的[京东云构建 40062153515](https://github.com/BlackHu-art/openwrt_release/actions/runs/40062153515) 已通过 SSR 源码准备，在 simple-obfs 下载归档校验时失败。本文记录两个兼容修复及复验方式。

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

SmartDNS 配方来自现有 `ZqinKing/openwrt-smartdns`；维护快照 `cdf0de1d3e64984ea2c56ec873f233495ddb1de0` 的 Makefile 与本次核验的上游内容一致。配方使用 `VERSION` 传递 WebUI 提交号，而当前下载框架只读取 `SOURCE_VERSION`。实际命令变为 `--version=""`，Git 回退拉取默认 `main`，生成错误版本的真实源码归档。

独立读取固定提交的 Git tree/blob，并分别核对 `git archive`、GitHub codeload 与 GNU tar/gzip 重建：

| 项目 | 保留的固定源码 | 失败时下载的默认 main |
| --- | --- | --- |
| 提交 | `3261c18b1b93d841e86d9e727557109ae71d71cd` | `1c06fee693434ec7c71f06010d3f87416baba9f0` |
| 文件数 | 109 | 114 |
| gzip 字节数 | 724404 | 730252 |
| SHA-256 | `4401734712dd034eb1088ce440d1bc64d053dfcd6f63f66c08cd48ab68593042` | `88adb092ed7b0dc22b3964249f4969870d3b462c4d924aceb18784c0f664f16e` |

因此原始 `MIRROR_HASH` 正确，不能改成错误默认分支的哈希。固定源码 tree 为 `190f76f34cfda865389b27e8f69887aa6a64edc3`，时间戳为 `1766583635`，151 个归档条目；GNU tar SHA-256 为 `a203faeeb55271853270e0e84907d29d4e32043cf1bc86f4e45a4e78ff92816f`。GNU gzip 使用 `-nc`，没有文件名或当前时间信息。

[`smartdns_compat.py`](../wrt_core/smartdns_compat.py) 在 `update_smartdns` 克隆完成后、现有补丁和 CC 修正前执行，只在构建副本修正提交字段，并在已有 `CONFIG_PACKAGE_smartdns-ui` 为 y/m 时注册 WebUI 下载。主程序来源、提交、下载规则和所有插件配置保持不变。原始维护快照不修改；未知 Makefile 漂移明确失败，错误经源码准备阶段传播。

[`test_smartdns_download.py`](../tests/test_smartdns_download.py) 用真实 `download.mk` 展开原配方，复现空提交号和未选 UI 仍下载；修正后验证 unset/n/y/m，以及主程序下载提交保留。Linux 必需门禁执行 y/m 的真实干净下载、逐成员 Git blob 核对、独立归档字节比较，以及错误哈希拒绝。测试不执行 Rust/Node 编译或目标架构交叉编译。

```bash
REQUIRE_SMARTDNS_DOWNLOAD=1 python3 tests/test_smartdns_download.py -v
```

框架和源码身份详见 [SmartDNS 下载 fixture](../tests/fixtures/smartdns-download/README.md)。循环依赖修复另见 [Kconfig 兼容说明](kconfig-compat.md)。
