# 插件源码维护区

这里保存第一批五组插件的六份原始参考快照，并追加 SSR Plus+ 的固定版本迁移评估。
本目录是 **reference-only** 维护区，不是固件源码输入；第一批来源记录的是采集时构建脚本的来源。
SSR 专项另外保存 `v198.2` 原始仓库和 `190-r11` 派生比较副本。
Passwall / Passwall2 的部分回归会读取这里的快照，更新后仍需运行对应回归。

本次实际接入固件准备流程的 16 个顶层受管源码单元位于
[`wrt_core/managed/`](../../wrt_core/managed/README.md)，由其自己的
[`sources.lock.json`](../../wrt_core/managed/sources.lock.json) 和 loader 管理。
这与本目录的参考快照锁文件是两个独立用途：更新本维护区不会自动切换构建来源，
也不能把参考快照的版本表当作当前固件版本表。

获取日期：2026-10-22（Asia/Shanghai）。项目基线：`6d76ce124426086bbc5f90a9fcb9fcc0ba3b0a41`。完整来源、提交、Git tree、版本原始字段和内容清单入口见 [sources.lock.json](sources.lock.json)。

## 第一批来源与版本

| 对象及本地目录 | 快照来源（采集时的构建来源） | 本次解析分支 | 上游提交 | 软件包版本字段 |
| --- | --- | --- | --- | --- |
| [SmartDNS 软件包](smartdns/package) | [ZqinKing/openwrt-smartdns](https://github.com/ZqinKing/openwrt-smartdns) | 默认分支 `master` | `cdf0de1d3e64` | `1.2025.47-1` |
| [SmartDNS LuCI](smartdns/luci-app-smartdns) | [pymumu/luci-app-smartdns](https://github.com/pymumu/luci-app-smartdns) | 默认分支 `master` | `581e5e816d92` | `1.2026.48.2-2` |
| [Passwall](passwall/luci-app-passwall) | [Openwrt-Passwall/openwrt-passwall](https://github.com/Openwrt-Passwall/openwrt-passwall)，仅 `luci-app-passwall/` | 显式 `main` | `7cdb8379d428` | `26.10.22-2` |
| [Passwall2](passwall2/luci-app-passwall2) | [Openwrt-Passwall/openwrt-passwall2](https://github.com/Openwrt-Passwall/openwrt-passwall2)，仅 `luci-app-passwall2/` | 显式 `main` | `896c586a27c9` | `26.10.20-1` |
| [OpenClash](openclash/luci-app-openclash) | [kenzok8/small-package](https://github.com/kenzok8/small-package)，仅 `luci-app-openclash/` | 默认分支 `main` | `3d5609257639` | `0.48.002`，未显式声明 release |
| [AdGuard Home LuCI](adguardhome/luci-app-adguardhome) | [ZqinKing/luci-app-adguardhome](https://github.com/ZqinKing/luci-app-adguardhome) | 默认分支 `main` | `36108202f326` | 未显式声明版本/release，以提交标识 |

第一批六份快照合计 530 个上游文件、28,876,252 字节（约 27.54 MiB），不含本目录的说明、清单及补充许可证。OpenClash 包内跟踪的数据和资源文件也保留原样，没有额外下载代理核心。

## SSR Plus+ 专项评估

另行保存的 [SSR Plus+ 维护目录](ssrplus/README.md) 包含 `fw876/helloworld@v198.2` 完整仓库快照（962 文件）与本项目 `190-r11` 还原副本（61 文件）。锁文件新增的 `ssrplus-v198.2` 是评估来源，**不是当前构建来源切换**。两者详细差异、补丁去留及依赖阻塞见 [迁移评估](../../docs/ssrplus-v198.2-migration-assessment.md)。

这里的版本是 Makefile 中的软件包字段，不等于路由器上实际运行的核心版本。SmartDNS 软件包仍由 recipe 指向 `pymumu/smartdns@136c0c2690138d6dedd8b520281aafe49112643f`；本目录没有另行导入其 C 核心仓库。AdGuard Home 保存的是 LuCI 插件，未导入 Go 核心。Passwall、Passwall2、OpenClash 同样不包含所有代理核心的源码。

## 文件记录与存储方式

- `sources.lock.json` 记录来源 URL、构建采用的引用策略、实际分支、完整 commit/tree、原始子目录、本地目录、提交时间、版本表达式及清单哈希。`HEAD` 表示构建使用上游默认分支，本次解析结果另有记录。
- `manifests/<id>.json` 为每个原始文件记录相对路径、Git blob、Git mode、字节数和 SHA-256。清单与源码一同更新，单独改写清单不能作为修复通过的证据。
- `licenses/<id>/` 保存从源仓库根额外带入的许可证，并在锁文件中注明原路径和 blob。它们不混入原始包子树。
- 源码按 Git blob 直接导出，保留原始字节；未使用可能应用 `export-ignore` / `export-subst` 的默认 archive 结果。目录内没有嵌套 `.git`、子模块或 LFS 指针。
- 当前 Windows 无法创建符号链接，第一批六份快照的 5 个 `120000` 文件以 Git 链接目标文本保存；各清单记录 `symlink_target` 和 `storage: git-link-text`。它们不是正常的翻译文件，也不是已经创建的目录链接。SSR 追加快照的链接与权限数量单独记录在其维护说明中。
- 第一批六份快照的 43 个原始 `100755` 文件的可执行属性保存在清单中。维护快照的普通检出不保证恢复 POSIX 执行位。需要运行或移植源码时，优先按锁定提交重新 Git checkout；若从本目录复制，则应按清单恢复执行位和相对符号链接后再使用。
- 本目录 `.gitattributes` 禁止源码换行、编码及内容过滤转换；`.gitignore` 放行被父仓库 `test.sh` 规则忽略的两份原始脚本，以及 SSR 快照中的测试目录。SSR 上游自带忽略规则的额外提交要求见其维护说明。

## 与现有补丁和测试的关系

| 维护对象 | 当前生效逻辑 | 已有测试基线 |
| --- | --- | --- |
| SmartDNS | [update_smartdns](../../wrt_core/modules/package_source_updates.sh)、[优化补丁](../../wrt_core/patches/100-smartdns-optimize.patch) | 尚无独立 SmartDNS fixture；本快照不是已完成的兼容验证 |
| Passwall | [来源表](../../wrt_core/modules/custom_feed.sh)、[fix_passwall_compat](../../wrt_core/modules/plugin_compat.sh)、[apply_passwall_tweaks](../../wrt_core/modules/feed_source_fixes.sh) | 实际 Lua 生成器的 TLS、共享 Xray 配置及生成失败后停止启动回归；未做完整固件运行验收 |
| Passwall2 | [来源表](../../wrt_core/modules/custom_feed.sh)、[fix_passwall_compat](../../wrt_core/modules/plugin_compat.sh) | 实际 Lua 生成器的 TLS、共享 Xray 配置及生成失败后停止启动回归；未做完整固件运行验收 |
| OpenClash | [fix_openclash_compat](../../wrt_core/modules/plugin_compat.sh) 应用五份补丁：原有 WAN 子网、checksum，以及 Ruby AST、dashboard 状态、文件名/目录校验 | [plugin-runtime](../../tests/fixtures/plugin-runtime/README.md) 的下载函数与 [0.48.002 完整文件](../../tests/fixtures/openclash/0.48.002/README.md)；真实 Ruby、JavaScript、Lua 入口回归 |
| AdGuard Home | [update_adguardhome](../../wrt_core/modules/service_fixes.sh) 获取源码后调用 `fix_adguardhome_compat`，应用稳定更新安全与无需更新时不执行 UPX 两份补丁；[三文件 blob 基线](../../wrt_core/compat/adguardhome/source-files.tsv) 在写入前校验 | [plugin-runtime](../../tests/fixtures/plugin-runtime/README.md) 的固定更新器、下载配置及 Lua 控制器；补丁组合、重复执行与源码漂移回归 |

SSRPlus、HomeProxy 等已有固定测试基线继续保留在 `tests/fixtures/`；HomeProxy 的实际构建输入现已另行固定在 `wrt_core/managed/`。原始维护快照与已应用补丁的构建源码可能存在预期差异。源码获取成功和校验一致只说明快照完整，不代表新上游已通过固件构建或路由器运行验收。

当前补丁行为与验证边界见 [插件兼容性说明](../../docs/plugin-compatibility.md)。Xray 配方版本调整的来源与哈希单独记录在 [共享核心版本记录](../../wrt_core/compat/proxy-cores/xray-26.7.11.json)，不改写本维护区的原始源码和来源锁文件。

OpenClash 的 Ruby AST、dashboard 和文件名修复分别适配上游 `ac3c7bf`、`4983173`、`75d34d0`；AdGuard Home 无更新时的 UPX 修复适配 `81a7d33`。OpenClash WAN #5359 / `a4b7073` 暂缓，因自定义 WAN 与默认链共存时可能选错区域，且 fw3 仅枚举 IPv4 区域。维护快照和现有 WAN 子网补丁不代表已修复该问题；来源链接和具体行为见上述兼容性说明。

## 后续更新流程

1. 从锁文件选定一个来源，按 `repository` 和 `requested_ref` 在独立临时目录获取新提交。默认分支必须重新解析，显式 `main` 继续使用 `main`；固定 tag（如 SSR `v198.2`）必须解析并核对对应完整提交，不混入滚动分支内容。不运行下载源码中的脚本。
2. 记录新旧完整 commit、实际分支和目标子树 tree，检查版本字段、许可证、依赖及目录变化。先做差异审查，再决定是否替换本地快照。
3. 按 `upstream_path` 导出完整目标子树的原始 Git blobs，不能只复制改过的文件，否则上游已删除文件会残留。根许可证单独保留，已有本地补丁不混入原始文件。
4. 对所有文件重新记录 mode、blob、大小和 SHA-256，再更新对应 manifest 及其锁文件摘要；同时更新本页版本表。新出现的 Git 链接、子模块或 LFS 指针需要明确处理，不能当作普通内容跳过。
5. 比较导入目录与 Git 文件清单，检查是否被忽略规则漏掉，并验证进入 Git 后仍保持原始字节。新上游如增加 `.gitattributes`，需要重新检查它是否覆盖本维护区的保护规则。
6. 后续若要修复插件，单独更新 `wrt_core/patches/`、相应模块及必要 fixture/回归；维护快照更新本身不改变构建来源、软件包选择或运行行为。

例如，下面的命令可在新临时目录中重新获取当前 Passwall 基线（只获取源码，不执行源码；其他来源使用锁文件对应值）：

```powershell
$sourceReviewPath = Join-Path ([System.IO.Path]::GetTempPath()) ('passwall-review-' + [guid]::NewGuid())
git clone --filter=blob:none --no-checkout --branch main https://github.com/Openwrt-Passwall/openwrt-passwall.git $sourceReviewPath
git -C $sourceReviewPath config core.autocrlf false
git -C $sourceReviewPath sparse-checkout set luci-app-passwall
git -C $sourceReviewPath checkout --detach 7cdb8379d42866af93d996d5afb7d5b2b18eb061
```

这是审查工作树，不应直接替换 `<BUILD_DIR>` 中已有源码；构建准备阶段可能清理该目录。

## 许可证与来源说明

原文件中的版权和许可声明保持不变；这些第三方源码不能统一解释为适用主项目根目录的 LICENSE。

- Passwall / Passwall2：保留各自来源仓库根的 GPLv3 LICENSE，见 `licenses/passwall/` 和 `licenses/passwall2/`。
- SmartDNS 两个包装仓库：当前没有独立 LICENSE/COPYING 文件，Makefile 声明 `GPL-3.0-or-later`；后端 recipe 中的 `PKG_LICENSE_FILES:=LICENSE` 指向后续下载的核心源码文件，并不表示本包装仓库已包含它。
- AdGuard Home LuCI：当前仓库没有独立许可证文件，Makefile 文件头声明 Apache-2.0。现有 [COPYING.AdGuardHome](../../tests/fixtures/plugin-runtime/COPYING.AdGuardHome) 随固定测试文件保留。
- OpenClash：本次选取的聚合源包目录没有独立许可证文件；`licenses/openclash/LICENSE` 是 **small-package 聚合仓库的 Apache-2.0 文件**，不能据此给 OpenClash 重新许可。现有测试基线记录 OpenClash 的 MIT 来源，见 [fixture 说明](../../tests/fixtures/plugin-runtime/README.md) 和 [COPYING.OpenClash](../../tests/fixtures/plugin-runtime/COPYING.OpenClash)。

整个项目的目录职责见 [项目文件布局](../../docs/project-layout.md)。
