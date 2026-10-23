# SSR 190-r11 → fw876 v198.2：核心、依赖、包与构建门禁只读评估

> 历史记录：本文保留 190 系列及 2026-10-22 评估阶段的代码事实、建议和验证结果，文中“当前”指当时基线。生产现已采用固定 fw876 v198.2；旧启动/DNS 修复只留在历史测试中，未按本文建议迁回生产。现行来源、更新策略与验证边界见 [fw876 集成说明](../fw876-core-migration.md)。

审查基线：本项目 HEAD 6d76ce1；fw876 tag v198.2 = 45893d778767f3bdb2fcb6e873cf8f9a667d94d4；kenzok8/small-package 固定快照 3d5609257639ed76aaacdeffe242343d51265fea。没有改编译配置、构建脚本、源码补丁，也没有运行上游源码或目标程序。审查过程中发现其他任务并行修改工作树（包括Xray26.7.11适配），后文单独记载，不将其视为HEAD既有内容。

路径简写：`U/` = `maintenance/plugins/ssrplus/upstream-v198.2/`；`K/<path>:line` = 固定 kenzo Git 对象中的文件及行号，来源为 https://github.com/kenzok8/small-package/tree/3d5609257639ed76aaacdeffe242343d51265fea。kenzo 比较对象不是本次构建已解析安装的事实；实际 feeds 为滚动拉取且另有覆盖步骤。

## 结论与阻塞

不能将 v198.2 的 LuCI 包当作 190-r11 的直接替换。至少有五组迁移阻塞：旧源码白名单/补丁基线；新 Xray 对 Go 1.27 的要求；fw 私有 Xray 功能及共享二进制更新策略；新依赖和默认核心选择；旧门禁的版本/覆盖范围。

### 1. 工具链存在已核实的版本冲突

- 本项目 `wrt_core/update.sh:8-9` 使用 `sbwml/packages_lang_golang` 的 `26.x`；`wrt_core/modules/package_source_updates.sh:4-11` 删除原 feed 的 Go 再克隆该分支。
- 已用 `git ls-remote` 精确解析并下载固定原文到评估临时目录，并将固定引用与内容哈希归档到 `maintenance/plugins/ssrplus/external-evidence.json`：sbwml `26.x` = `14667de14cbe22e0ed379de8b373dce4f04a4cab`，XTLS `v26.10.21` = `1b1647cd9ddf0abc34b981d4611fc03bcac1ca74`。固定Go `golang/Makefile` 第10-11行是 Go 1.26.10；固定 `golang-package.mk` 第218-219行是 `GOENV=off`、`GOTOOLCHAIN=local`。注意浏览器缓存的分支URL曾返回209-210行，归档固定提交文件才是最终行号依据。
- 固定XTLS `go.mod` 第3行要求 `go 1.27`。因此不能依赖Go自动下载新版规避。三文件SHA256分别是：Xray go.mod `7034fa6ca85b9919e634c06c69bde4e181818d8423f7c8d0e44f68ea5c6f5e60`；Go Makefile `4a43deb7f657b89398c084a32b05bd9fb630332b5258617fd0a5ebb37d284d78`；Go golang-package.mk `e65dd807c90c1b273ba1dab65f8442ecddedbc814ea3cb3c4fda7b17410beffd`。原始固定URL和行文本已保存在 `maintenance/plugins/ssrplus/external-evidence.json`。
- 最终生效调用链已按HEAD核对：`build.sh:485`调用update.sh；`repo.sh:68`先进入BUILD_DIR；`update.sh@6d76ce1:155-161`依次 upstream feeds update→custom feed→pre-install fixes→feeds install；pre-install第63行调用update_golang，`package_source_updates.sh:5-11`在目录存在时删旧Go并克隆26.x，失败exit1；后续`feeds.sh:41-42`只刷新索引并install。全项目搜索未发现后续另一处Go来源替换。限制：若前置SSR旧白名单先失败则不会走到Go；若异常SDK没有该目录，update_golang会跳过。正常完整OpenWrt packages feed路径下，26.x覆盖上游Go是实际脚本语义，不是未使用的配置项。
- `U/xray-core/Makefile:64-68` 对所有 ARM64 编译执行 EIP93 Go 源码 overlay；`U/xray-core/patches/190-an7581-eip93-aes-gcm.patch:443-462` 精确匹配 `crypto/internal/fips140/aes/gcm` 代码，缺失/非唯一模式就退出；`U/xray-core/README.eip93.md:7-8` 只说明已检查 Go 1.27。IPQ60xx 虽不启用 AN7581 硬件路径，编译期仍经过 overlay，不能用运行时自动回退解释为已可编译。
- 上游 release 工作流自己也重新取 packages master 的 Go（`U/.github/workflows/release-packages.yml:124-127`），其 SDK 成功或工作流存在不能替代本项目固定 26.x 的构建证据。

### 2. v198.2 依赖 fw 定制 Xray，不是仅需要一个名为 xray 的程序

`U/xray-core/Makefile:4-5` 为 26.10.21-r2，kenzo 快照 `K/xray-core/Makefile:4-5` 是 26.3.27-r1，且 kenzo `xray-core` 目录仅 Makefile，没有这十个补丁。fw 十项（均在 `U/xray-core/patches/`，各文件第2行为主题）：

| 补丁 | 能力/行为 |
|---|---|
| 100-restore-allow-insecure.patch | 恢复显式 allowInsecure |
| 110-add-anytls-proxy.patch | AnyTLS 入站/出站 |
| 120-restore-vmess-alterid-outbound.patch | 恢复旧 VMess alterId 出站认证 |
| 130-add-naive-proxy.patch | Naive 入站及 Chromium/Cronet 出站 |
| 140-add-shadowsocksr-proxy.patch | SSR 入站/出站 |
| 150-add-tuic-proxy.patch | Mihomo TUIC v4/v5 入站/出站 |
| 160-add-snell-proxy.patch | Snell 入站/出站 |
| 170-add-shadowtls-transport.patch | ShadowTLS 传输 |
| 180-add-kcptun-transport.patch | Kcptun 传输 |
| 190-an7581-eip93-aes-gcm.patch | AN7581 专用 AES-GCM 混合加速 overlay |

第190项运行时仅允许 AN7581/EN7581，排除 AN7583/其他DT、已有ARM AES及FIPS（补丁50-61行），并在错误时回退；这不是本项目其他设备的性能保证。Makefile12-13行许可证也扩展为 MPL-2.0/GPL-3.0-or-later/MIT 及第三方许可证清单，应随整套源码保持。

新 LuCI `U/luci-app-ssr-plus/root/etc/init.d/shadowsocksr:898-907` 的 `first_type` 优先找 `/bin`、`/usr/bin`、`/usr/libexec`，只检查可执行存在。`normalize_xray_protocol_nodes:1231-1245` 会将 AnyTLS/Hysteria2/Trojan 类型改为 Xray 格式。`gen_config.lua:202-218` 有 Xray 版本检测，并在552-566、828行等处分版本输出；但“版本号够新/二进制存在”不证明 fw 十补丁已在二进制中。

### 3. Passwall/Passwall2 共用核心必须纳入迁移

- `wrt_core/modules/custom_feed.sh:164-166,200,202-204` 显示核心由 kenzo 导入，Passwall/Passwall2 从各自主仓 main 导入，SSR LuCI 从 fw master 导入。没有按插件隔离 Xray 包名。
- `maintenance/plugins/passwall/luci-app-passwall/Makefile:148`、Passwall2 Makefile42/50行均选择同一个 `PACKAGE_xray-core`。
- Passwall `luasrc/passwall/com.lua:69-75`、Passwall2 `luasrc/passwall2/com.lua:49-55` 的 Xray 更新来源为 `XTLS/Xray-core`，默认路径 `/usr/bin/xray`；各 api.lua 的1507/1522行把下载的二进制移动覆盖 app_path。
- 因而升级共用 Xray 会同时影响这三个插件，且以后从 Passwall 内更新可覆盖 fw 定制核心，丢失上述补丁功能。推荐在迁移设计中明确选择：统一使用并固定 fw 定制 Xray，调整各插件更新来源/禁用替换；或重命名包与二进制并显式隔离 SSR 路径。不能在同名包相互覆盖下宣称兼容。
- `wrt_core/modules/feed_source_fixes.sh:14-18,29-32` 会删除系统 packages 的 xray、mihomo 等；导入必须保证唯一供应方和正确目录。当前 custom feed 拉取 `mihomo-meta`（custom_feed.sh206行），并未导入 fw 的 `mihomo`，也未把 kenzo `mihomo` 放入 base list。不能默认 `mihomo-meta` 能满足 `PACKAGE_mihomo` 的Kconfig选择或路径，应检查最终 metadata/PROVIDES/安装路径。
- 保留 sing-box 1.14.3 来源和本地 HomeProxy 修补：fw 树没有 sing-box，不能整套覆盖 custom_feed 后丢失它。当前 HomeProxy 1.14 兼容补丁在 feed_source_fixes.sh45行起，独立于 SSR。

## LuCI Makefile 迁移

对照 `tests/fixtures/ssrplus/2abdc9aa/Makefile` 与 `U/luci-app-ssr-plus/Makefile`：

- 版本从190-3升到198-2；旧本地版本链最终才是190-r11。
- 新增必需 `luci-compat`、`ipt2socks`、`lyaml`（新Makefile32-35行）；去掉旧基线直接依赖的coreutils/base64、jq、tcping、ssr-check，去掉若干原生核心选项。迁移时按实际脚本使用保留旧补丁新增依赖，不能将旧整行依赖原样覆盖新行。
- 特别是新 init 870-876行仍使用 flock，但新Makefile没有flock依赖；本地第9补丁的 `+flock` 必须保留/重做，且最终配置门禁也要求它。
- 旧默认 aarch64/x86 选 Xray/SS Rust，新Makefile81-104行分别默认 Shadowsocks client/server NONE、V2ray-core NONE。只有启用 `INCLUDE_Xray` 才select xray及coreutils-timeout（109-112行）。仅 `CONFIG_PACKAGE_luci-app-ssr-plus=y` 不保证得到可用Xray；共用Passwall恰好拉入核心不是SSR自身显式契约。
- 新增 HTTP 代理默认在aarch64/arm/i386/loongarch64/riscv64/x86_64启用并选择3proxy（123-126行）；Mihomo默认i386/loongarch64/riscv64/x86_64（128-132行），GeoData默认i386/x86_64并选择v2ray-geoip/geosite（134-138行）。应明确配置这些选项和空间预算，避免默认行为漂移。
- 原生 V2ray、Hysteria、Tuic、Trojan、Shadowsocks-libev、DNS2SOCKS/DNSPROXY、Redsocks2 等选项移除/简化，不能把旧config符号保留就当作继续生效。当前唯一直接选 SSR 的设备配置 `wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config:87` 只写主包，没有完整能力清单。
- 后端选项名称保留，新Makefile59、72行进一步绑定 !firewall4/firewall4，当前项目仅支持nft修补路径的门禁应保留。
- 新Makefile182-219行自定义install并chmod ssr-monitor/rules/switch及hotplug。迁移后的manifest需核对安装权限；不能只看源码文本。

## 核心配方对照与最小导入范围

下表的版本是固定快照配方，不是已编译运行结果；除了fw Xray，不建议为了SSR把无关包一并切源。各fw版本行可直接引用 `U/<package>/Makefile`；kenzo行号见括号。

| 包 | kenzo固定快照 | fw v198.2 | 建议/影响 |
|---|---|---|---|
| xray-core |26.3.27-r1 (4-5)|26.10.21-r2 (4-5)|必需审定定制能力与Go1.27，共用核心 |
| xray-plugin |1.8.24-r1 (8-9)|1.8.24-r1 (8-9)|同版本，不因SSR整体切源 |
| hysteria |2.13.0-r1 (8-9)|2.13.0-r1 (8-9)|相同版本，SSR新路径偏Xray，仍可能被其他插件使用 |
| sing-box |1.14.3-r1 (8-9)|缺失|保留当前来源及HomeProxy修补 |
| v2ray-core |5.55.0-r1 (8-9)|5.49.0-r1 (8-9)|fw更旧，勿整树覆盖降级 |
| v2ray-plugin |5.49.0-r1 (9-10)|5.49.0-r1 (9-10)|同版本 |
| shadowsocks-rust |1.25.0-r1预编译 (9-19,68)|1.25.0-r3源码Rust (10-22,35)|相同版本但构建供应链改变；fw要求musl+RUST_ARCH_DEPENDS |
| tuic-client |2.0.0_pre7，Itsusinn预编译 (8-16,48,62)|1.7.2，Itsusinn源码Rust (9-21)|不同版本/构建方式；配置ABI不能按名字视为兼容 |
| shadow-tls |0.2.25-r1预编译 (7-8,39,51)|0.2.25-r1 Rust源码 (8-19,31)|新引入rust host负担，aarch64/arm/x86_64 |
| naiveproxy |154.0.8037.49-4预编译 (8,69-70)|同版源码Chromium (8,21,60-98)|gn/host+LLVM24+PGO，资源/宿主要求大幅改变 |
| mihomo |1.19.32-r1 (8-19)|1.19.32-r2+upx (4-17)|fw放/usr/libexec/mihomo（28/52行），当前custom_feed未导入这个包 |
| chinadns-ng |2025.08.09-r1 (6-7)|2025.08.09-r1 (8-9)|预编译映射/架构集不同；kenzo带+ipset，fw不带；核对nft参数 |
| ipt2socks |1.1.4-r3 (8-9)|1.1.4-r1 (8-9)|更低release；新LuCI必需，现有kenzo供应可先保留再验证 |
| dns2tcp |1.1.2-r2 (8-9)|1.1.2-r3 (8-9)|小release差异应比补丁，不能只按版本决定 |
| dns2socks |2.2-r1 kenzo (8-12)|2.1-r2 SourceForge (8-12)|fw是回退；新LuCI不再默认拉入 |
| dns2socks-rust |0.2.7-r1 (9-10)|0.2.6-r1 (9-10)|fw更旧，非当前base列表，勿顺带引入 |
| dnsproxy |0.86.0-r1 (8-9)|0.83.0-r1 (8-9)|fw更旧，非当前base列表，勿顺带引入 |
| mosdns |5.3.4-r1 (8-9)|5.3.4-r1 (8-9)|本项目实际随后由sbwml/v5覆盖(custom_feed.sh201)，保持该契约 |
| shadowsocksr-libev |2.5.10-r1 kenzo tar+libopenssl-legacy (4-8,29)|2.5.6-r13 bundled源码 (10-11,31)|不同源码分支+OpenSSL legacy依赖，勿回退共用SSR客户端 |
| shadowsocks-libev |3.3.6-r1 (16-17)|3.3.5-r13 (16-17)|fw更旧且包分拆/依赖不同，不是新LuCI首选 |
| simple-obfs |0.0.11-r1 kenzo (9-13)|0.0.5-r2 shadowsocks固定commit (9-15)|不是单调更新，保留其他插件契约 |
| tcping |0.5 kenzo (8-12)|1 jlyo (8-22)|项目会再下载Passwall包Makefile（feed_source_fixes.sh254-263），不能把snapshot称最终来源 |
| lua-neturl |1.2-1 (8-13)|1.2-1 (8-13)|需与订阅解析测试使用的实际Lua库保持一致 |

建议第一阶段只迁移经审查的新LuCI、本项目适配补丁、fw Xray及其upx host依赖；若选择Mihomo能力，再明确导入fw mihomo及数据依赖。保留其余现有包来源。fw完整目录留作对照，不进入批量覆盖脚本。

### 新构建约束

- Xray `XRAY_CORE_NAIVE` 默认y（U/xray-core/Makefile83-93）：aarch64/arm/i386/x86_64/mipsel/riscv64/loongarch64，musl或glibc，arm需v7+FPU；要求x86_64 Linux构建宿主。38-59行下载固定LLVM24 Cronet Clang并指定lld，45行针对arm/i386/mipsel/loongarch64调整链接。禁用此选项只保留Naive入站；Naive出站会报需要Cronet构建（130补丁477行）。
- Xray/mihomo都需要upx/host，并安装时使用`--lzma --best`（Makefile105 / mihomo52）；不能只拷贝xray Makefile而漏host工具包与构建资源。
- shadowsocks-rust/tuic/shadow-tls从kenzo预编译切fw源码时引入Rust host与Cargo依赖；本项目target_fixes.sh297-300仅修`download-ci-llvm`，不是Rust版本兼容证明。
- 上游release矩阵只覆盖 x86_64、aarch64_generic、aarch64_cortex-a53 的24.10.6/25.12.3 SDK（U/.github/workflows/*.env），且把大量可选包关闭（release-packages.yml148-171）。不能推广为本项目所有ImmortalWrt/LibWrt设备、架构和全功能配置已验证。

## 本地第9及版本补丁处置

| patches.list序号 | 文件 | 迁移结论 |
|---|---|---|
|9|ssrplus-package.patch|重写：保留flock依赖和本地构建身份；丢弃旧190-3→4上下文。该补丁7-9行和15-18行是关键 |
|12|ssrplus-release-r5.patch|仅190-r4→r5身份，存为旧基线升级兼容证据；不直接套198 |
|14|ssrplus-release-r6.patch|同上，r5→r6 |
|16|ssrplus-release-r7.patch|同上，r6→r7 |
|19|ssrplus-release-r8.patch|同上，r7→r8 |
|21|ssrplus-release-r9.patch|同上，r8→r9 |
|23|ssrplus-release-r10.patch|同上，r9→r10 |
|25|ssrplus-release-r11.patch|同上，r10→r11 |

这些版本补丁各12-13行都是PKG_RELEASE递增，并保留190上下文。应建立独立v198.2适配基线和新本地release，旧25补丁链留作历史/旧包输入归一测试，不把所有旧补丁硬重命名套用，也不把198-2冒充本项目已修复产物。

## runtime/helper、源码清单与门禁迁移清单

1. `wrt_core/compat/ssrplus/runtime.sh` 不是可随意删除的旧残留：4-16行的同inode锁/信号清理，27-56行的失败DNS恢复，59-65行的prepare-only与daemon关闭FD9，85-135行的DNS暂存/本机dnsmasq校验/一次rename发布，137-165行的本插件进程识别与preflight后restart，是本地已定义的行为保障。新init仍有旧锁`exec1000/flock/unlink`（870-876行），且不存在这些helper调用。需要将保障适配到新生命周期，不能单复制runtime文件就称保留。新上游全局killall（3281/3293）还需要与Passwall共存测试。
2. `source-files.tsv:1-12`是12个旧上游Git blob：init/gfw2ipset/update.lua/ssr-rules/subscribe.lua/ssr-monitor/ssrplusupdate.sh/ssr-switch/Makefile/uci-defaults/template/gen_config.lua。`plugin_compat.sh:81-102`仅复制这12文件、逆序撤旧补丁、匹配精确blob后重套补丁；新源必然不满足旧白名单。应新增v198.2独立清单/fixture，仍拒绝未知漂移。增补新生成器、核心更新器、pppoe hotplug等新增关键root文件的审计覆盖，范围由对应功能review确认。
3. `plugin_compat.sh:111-121`默认source commit仍是2abdc9aa，repair-version硬编码190-r11；`.ssrplus-upstream-commit`只验证40hex而不是审核过的固定commit。迁移必须同时固定拉取引用、源码blob与manifest版本，不能只改manifest里的字符串。
4. `ssrplus_verify.py:51-78,94-110`通用manifest/文件hash/权限框架可保留。`161-167`版本比较是通用归一化，190-11仅注释，不是硬编码阻塞；应更新注释及fixture期望即可。真正旧版本硬编码在helper与测试。
5. 现有manifest只保护所选LuCI root文件，并验证LuCI包名/版本，不能证明xray/mihomo二进制版本、补丁、下载来源或能力。迁移要增加依赖核心来源/recipe+patch哈希、已构建core包及实际rootfs路径检查；无需把可变/etc/config/shadowsocksr硬绑为安装哈希。
6. `ssrplus_build.sh:5-19`要求firewall4、dnsmasq-full、dnsmasq_full_nftset、flock、SSR nft后端全y并拒iptables，这些契约应保留；额外核对选择的xray/mihomo及必要host工具/新依赖。旧模块22-80行检查IPK/APK和root-/per-device target-dir仍有价值，尤其本项目IPQ60xx启用per-device（设备config4-11行）。
7. `build.sh:494-496`在make defconfig后校验最终配置，`build_steps.sh:83`在构建后验产物；不要把它们绕过。`check_selected_plugins.py`只是补充选择检查，不替代新核心能力/来源校验。
8. `tests/test_ssrplus_compat.sh:12,30-41,111,158`有旧commit、独立blob、190-r11和release11硬编码；build_gate.py86/92、artifacts.py64/158/331等同样固化版本。必须保留旧fixture回归并为新基线增加对应期望，而不是让测试完全从被测补丁自动生成可信值。
9. `.github/workflows/test_ssrplus.yml:41-63`当前为Ubuntu24.04、Lua5.1/Lupa、DNS/nft隔离网络命名空间；构建/release工作流依赖ssrplus-gate（build_wrt.yml43-47；release_wrt.yml61-65）。保留依赖链。新lyaml和Mihomo路径会需要新增测试依赖/真实配置校验；现有CI没有编译/执行fw定制Xray，不能用旧回归PASS证明核心兼容。

## 实施验证顺序（后续授权迁移用）

1. 固定v198.2/source/core/toolchain提交；产出独立新baseline、补丁保留矩阵和依赖提供方表，保留旧190-r11 fixture。
2. 解决Go1.27、Cronet/UPX/ARM64 overlay，并选择共享或隔离的Xray策略；明确Mihomo/3proxy/GeoData默认值。
3. 将本地锁、事务、错误恢复、首启、引用修复等语义移植到新流程，新增核心能力与共享更新回归；重做flock/本地release补丁。
4. 临时Linux SDK/实际目标上运行make defconfig并检查所有必要符号，分开编译Xray、Mihomo(如选)、SSR LuCI；用生成配置对fw Xray做`run -test`、对Mihomo做配置校验。验证Passwall/Passwall2生成配置仍接受，以及他们的更新不会换掉定制二进制。
5. 保留现有DNS/nft/firstboot/订阅/引用/产物污染回归，扩展到新文件与多核选择。验IPK/APK、rootfs和per-device rootfs的版本/权限/manifest/core来源。
6. 最后才进入可回滚测试设备做升级保持配置、启停/并发更新/故障注入、DNS恢复、共享核心共存、UDP/IPv6和真实订阅试验。当前只读静态评估没有完成这些运行/构建验证。

## 审查期间出现的并行工作树变更

在HEAD仍为6d76ce1时新增未提交 `wrt_core/modules/xray_core_compat.sh`、`wrt_core/compat/proxy-cores/xray-26.7.11.json` 和对应测试/补丁；update.sh新增Passwall适配并在update_golang之后调用fix_xray_core_compat。不是本评估任务写入。

- 新helper7-9行固定目标26.7.11及kenzo原配方/已补配方blob，16-19行拒绝其他Makefile，23-43行核对Passwall最低核心版本，46-60行核对Go>=1.26；它没有升级Go来源到1.27。
- 因此“当前HEAD核心基线26.3.27”仍正确；若其他任务最终完成，当前工作树候选会是26.7.11。两者都不是fw26.10.21十补丁实现。且该新helper会在接入fw recipe时直接按未知blob拒绝，需要另行设计其与SSR升级的统一来源策略。
- 此并行修改意味着最终报告的源码行号应在交付前再次确认；本报告对旧链的精确引用明确标了HEAD，新增项以本次观察工作树为准。

返回 [迁移评估总表](../ssrplus-v198.2-migration-assessment.md)。
