# SSR Plus+：190-r11 → v198.2 迁移评估

评估日期：2026-10-22。结论：**v198.2 值得作为新的维护基线，但不能直接替换当前包。应保留本地的并发控制、失败恢复和订阅兼容目标，围绕新版流程重新实现；不要整包复制旧 init/subscribe，也不要把 fw 的全部核心包覆盖到现有 feeds。**

本次已取得完整固定源码、还原当前版本并完成源码比较和补丁语义审查。没有接入新版构建，没有修改本任务范围外的编译配置、生产补丁、设备配置或核心来源。

## 1. 固定比较对象与范围

| 对象 | 固定身份 | 本地位置 |
| --- | --- | --- |
| 项目基线 | `6d76ce124426086bbc5f90a9fcb9fcc0ba3b0a41` | 本项目 Git 提交 |
| 当前上游基线 | `fw876/helloworld@2abdc9aa9e19607774dc9789709212b70b8607c6`，`190-r3` | 原始测试 fixture 与还原输入 |
| 当前修复版 | 上述完整包 + 本项目 25 份补丁 + runtime，`190-r11` | [current-190-r11](../maintenance/plugins/ssrplus/current-190-r11/) |
| 新评估基线 | tag `v198.2` → `45893d778767f3bdb2fcb6e873cf8f9a667d94d4`，`198-r2` | [upstream-v198.2](../maintenance/plugins/ssrplus/upstream-v198.2/) |
| 当前核心来源比较快照 | `kenzok8/small-package@3d5609257639ed76aaacdeffe242343d51265fea` | 固定 Git 对象；实际构建仍会滚动拉取及执行覆盖步骤 |

这里比较的是确切 `v198.2`，不是后来滚动变化的 `dev`。完整新仓库有 **962 文件、14,357,069 字节**；其中 LuCI 包 84 文件。完整仓库包含其实际跟踪的源码、构建配方和补丁，不表示已经下载所有配方引用的外部源码、工具链或核心二进制。

当前包还原副本有 **61 文件、2,179,146 字节**：原始包 59 文件，加上 runtime 和生成清单。使用真实 `fix_ssrplus_compat` 函数生成，两次执行返回 0，第二次所有文件字节保持一致。五项准备输入及 25 个补丁的哈希与项目基线提交一致。它不是从路由器或成品包提取的运行状态。

目录内容对比（不把文件模式与内容变化混为一项）：

| 从 → 到 | 新增 | 删除 | 内容改变 | 内容相同 |
| --- | ---: | ---: | ---: | ---: |
| 原始 190-r3 → 当前 190-r11 | 2 | 0 | 10 | 49 |
| 原始 190-r3 → v198.2 LuCI | 30 | 5 | 32 | 22 |
| 当前 190-r11 → v198.2 LuCI | 30 | 7 | 32 | 22 |

每个路径和检查结果见 [comparison-evidence.json](../maintenance/plugins/ssrplus/comparison-evidence.json)。上游完整 commit/tree 和逐文件身份见 [来源锁文件](../maintenance/plugins/sources.lock.json) 及 [原始清单](../maintenance/plugins/manifests/ssrplus-v198.2.json)。

## 2. 25 份补丁逐项处置

“保留”指保留行为保障，不等于原 patch 能直接应用。“部分覆盖”只删除已被上游等价实现的部分；旧修复链仍保留为 190 系列历史输入和回归基线。

所有补丁位于 [wrt_core/patches](../wrt_core/patches/)，顺序来自 [patches.list](../wrt_core/compat/ssrplus/patches.list)。

| # | 补丁名（省略 `ssrplus-` / `.patch`） | 处置 | 必须处理的语义与新版差异 |
| --- | --- | --- | --- |
| 1 | startup-lock | 保留目标，重写 | 整次 start/stop/restart 串行、锁失败退出、后台关闭锁 FD；保留新 HTTP/Mihomo/IPv6 清理，消除锁内递归 restart |
| 2 | dns-transaction | 部分覆盖，主体重写 | 保留私有生成、真实 dnsmasq 验证、原子发布及失败恢复；新 family nftset/域名白名单应保留，旧 Netflix/oversea 代码不搬回 |
| 3 | updater-validation | 部分覆盖，主体重写 | 上游新增 IPv6 列表校验；仍需下载限制、检查 HTTP/内容、独占锁、原子提交与回滚；把 ip6_data 纳入事务 |
| 4 | persistence | 部分覆盖，主体重写 | metadata 多行处理已覆盖；仍需失败保留旧快照、完整导出检查、同目录暂存与原子替换 |
| 5 | availability | 部分覆盖，主体重写 | 保留有时限解析、有效缓存和只读 preflight；新版 load_config、Clash 缓存、YAML、IPv6 filter 会写状态，需重划准备/提交边界 |
| 6 | subscription | 部分覆盖，整体重写 | 空下载保留已部分覆盖；完整组验证、checked UCI、并发冲突保护与同步激活仍需保留，并覆盖 YAML/JSON marker/groupHash/临时直连规则 |
| 7 | monitor-scheduler | 部分覆盖，重写 | switch 已改一次 restart，但未检查失败；统一生命周期修复 DNS/KCP，保留新线程与模式 7，补齐模式 6 双监听检查 |
| 8 | persistence-lifecycle | 部分覆盖，重写 | 保留 SSR 私有表、独立锁、安全进程身份及失败不提交指纹；结合新 schema/IPv6 策略恢复，不能搬旧 IPv4-only restore |
| 9 | package | 重写 | 保留 `+flock`；新依赖行和安装权限重新审查；建立独立 198 系列本地身份，不把原版 198-r2 当作已修复产物 |
| 10 | dns-forwarding | 主能力覆盖，保留保护部分 | GFW nft DNS 引导和启动后快照刷新已覆盖；准备阶段不改实时集合、地址族校验、插入/刷新失败传播仍需适配 |
| 11 | custom-ports | 上游完整覆盖，停用重复补丁 | 新 init 已从 global 读取 dports/custom_ports；保留行为回归 |
| 12 | release-r5 | 不迁移到 198 | 仅旧 190 release 递增，保留历史 |
| 13 | firstboot | 与 15 合并重写 | 保留非破坏性 initialize、锁、模板验证、0644/原子发布及失败重试；保留新版模板节和迁移逻辑 |
| 14 | release-r6 | 不迁移到 198 | 仅旧 release 递增 |
| 15 | initialization-order | 与 13 合并 | 保留最终顺序，不重演 r6 错序；r6/r7 修的是本地历史回归，不能声称上游 reset 存在同一缺陷 |
| 16 | release-r7 | 不迁移到 198 | 仅旧 release 递增 |
| 17 | subscription-auto | 停用原 hunk，另做策略兼容 | 原“缺 ss_type 补 ss-rust”语句已不存在；但新版删除旧偏好且优先 Rust，旧显式选择/按链接传输选 Xray 的契约未保留 |
| 18 | ss-parser | 部分覆盖，拆分迁移 | Xray SS 主凭据算法已覆盖；空 userinfo 拒绝、SS/Trojan/VLESS query 只解码一次仍需保留 |
| 19 | release-r8 | 不迁移到 198 | 仅旧 release 递增 |
| 20 | transport-config | 部分覆盖，拆分迁移 | SS/Trojan finalmask 和 Trojan serviceName 已覆盖；TLS Host、raw HTTP 字段、QUIC 键大小写、Base64 字面加号等仍需修复 |
| 21 | release-r9 | 不迁移到 198 | 仅旧 release 递增 |
| 22 | ss-password | 保留，可复用该 hunk | 上游仍猜测并二次解码 Base64 内密码；这是唯一能直接通过新版正向文本检查的旧补丁，但还需新 JSON/YAML 回归 |
| 23 | release-r10 | 不迁移到 198 | 仅旧 release 递增 |
| 24 | node-references | 保留狭义兼容，重写接入 | 只处理历史错误密码的精确旧指纹；不能充当 190→198 全量迁移。新类型/组身份/Mihomo聚合及启动时改写引用另需迁移策略 |
| 25 | release-r11 | 不迁移到 198 | 仅旧 release 递增 |

合计：**16 份保留全部或部分目标并适配，2 份原补丁停用，7 份旧版本递增补丁不进入新链**。第 17 项停用原 hunk 仍留下核心选择兼容工作，不能把它算作“上游已完整解决”。

完整修改块、调用链、行号与回归条件分为三份附录：

- [启动、DNS、更新器与 nft 持久化](ssrplus-v198.2-details/lifecycle-review.md)：9 项补丁。
- [订阅、初始化与节点引用](ssrplus-v198.2-details/subscription-review.md)：8 项、47 个 hunks；另有 [结构化覆盖清单](../maintenance/plugins/ssrplus/subscription-coverage.json)。
- [核心、包依赖与构建门禁](ssrplus-v198.2-details/core-review.md)：第 9 项、7 份版本补丁及共享核心影响。

## 3. 迁移前必须解决的差异

### 3.1 新 Xray 与当前 Go 版本冲突

v198.2 的 Xray 配方是 `26.10.21-r2`，其固定源码 `go.mod` 要求 **Go 1.27**。项目 `update_golang` 正常路径会替换为 `sbwml/packages_lang_golang;26.x`，本次固定解析到 **Go 1.26.10**；打包环境设置 `GOTOOLCHAIN=local`，不会自动下载 Go 1.27。

此外，fw 对所有 ARM64 构建执行的 EIP93 overlay 精确修改 Go 内部 AES-GCM 实现，仅记录审过 Go 1.27。IPQ60xx 在运行时不使用 AN7581 硬件加速，仍不能绕过这个编译步骤。

证据已固定为提交和内容哈希：[external-evidence.json](../maintenance/plugins/ssrplus/external-evidence.json)，包括 [Xray go.mod](https://github.com/XTLS/Xray-core/blob/1b1647cd9ddf0abc34b981d4611fc03bcac1ca74/go.mod)、[Go 配方](https://github.com/sbwml/packages_lang_golang/blob/14667de14cbe22e0ed379de8b373dce4f04a4cab/golang/Makefile) 和 [工具链策略](https://github.com/sbwml/packages_lang_golang/blob/14667de14cbe22e0ed379de8b373dce4f04a4cab/golang-package.mk)。当前未尝试编译，版本约束冲突来自实际构建路径和固定源码。

### 3.2 定制 Xray 与其他插件共用核心

fw 随包包含 10 项 Xray 补丁，涉及 allowInsecure、旧 VMess alterId、AnyTLS、Naive/Cronet、SSR、TUIC、Snell、ShadowTLS、Kcptun 及 EIP93。它不是同版本官方 Xray 二进制的同义替代；某功能存在于核心补丁也不等于每条 LuCI 订阅分支都会生成它。

Passwall、Passwall2 与 SSR 当前共用 `xray-core`。前两者的核心更新器默认从 `XTLS/Xray-core` 下载并覆盖 `/usr/bin/xray`，可能把 fw 定制实现换回普通官方实现。后续必须选择统一维护并约束更新来源，或为 SSR 隔离包名、路径和更新机制；当前还没有实施其中任一方案。

也不应整树切换核心来源：fw 中一些包比现有 kenzo 快照更旧，部分从预编译下载改成 Rust/Chromium 源码构建；新 Xray Naive 默认涉及 Cronet、LLVM24、x86_64 Linux 宿主及架构条件。完整逐包表见核心附录。

### 3.3 核心选择及旧配置策略已改变

固定 v198.2 的订阅器不再读旧 `ss_type`；启动和 LuCI 编辑路径会删除旧偏好，Rust+Xray 同装时优先 Rust，未保留当前“带传输参数的 SS 自动用 Xray”的选择规则。旧 libev/Xray/auto/custom 显式偏好如何对应新版，需要单独处理。

新版本还会调整节点类型与分组身份、把部分订阅聚合为 Mihomo 总节点，并在启动时将 SOCKS5/HTTP 代理选择写成 `same/nil`。因此保持 SID 不等于保持旧的全部路由和代理策略。旧 Netflix/oversea 行为已经移除或转换，不能原样恢复对应补丁。

### 3.4 事务对象扩展到 UCI 之外

v198.2 更新订阅时还会写 `/etc/ssrplus/clash/<group>.mihomo.yaml`、JSON 格式 `{md5,hash,url}` marker，并管理转换 URL/groupHash 和临时直连规则。只迁移旧 UCI journal 会遗漏这些状态：节点回滚后，同一路径的 YAML 可能已经是新内容。

新事务必须先校验和暂存，激活成功后再推进所有持久状态；失败时恢复正确的 UCI、YAML、marker 和临时规则，同时保护并发用户修改。新合法 Mihomo 总节点可能是 `127.0.0.1:0`，旧统一端口校验需要按节点类型改写。

另发现 SSD/SIP008 原始 table 可能被 AnyTLS 预解析 table 分支当作成品节点使用，绕过格式解析，形成丢节点或 nil hashkey 的静态可达风险。此项尚未动态复现，列为重写订阅时必须新增的回归，而非已经证明的实机故障。

### 3.5 构建选择与来源校验必须一起迁移

新的主包选择并不保证自动选入 Xray；新增 `lyaml`、`ipt2socks`、`luci-compat`、HTTP 代理和 Mihomo/GeoData 选项需要明确。当前 `mihomo-meta` 也不能仅凭名称视为满足新版 `PACKAGE_mihomo`。

当前 12 个受保护源文件与 v198.2 **全部不同**。生产 helper 对原始新包的隔离试验按预期拒绝，且未改变包内任何文件。迁移应建立独立新来源清单、fixture、补丁集合和本地版本身份，继续拒绝未知漂移；不要关闭已有检查。

现有 IPK/APK、普通 rootfs 与按设备 rootfs 验证框架可以保留，但需扩展定制核心的来源、配方/补丁和能力检查。旧门禁只核对所选 LuCI 文件，不能证明 `/usr/bin/xray` 包含 fw 定制功能。

## 4. 后续实施顺序与验收条件

1. **先定核心和工具链方案。** 固定 LuCI、Xray、Go 及可选 Mihomo 来源；处理共用核心更新；明确新默认选项和旧配置保留策略，保留 190 系列 fixture。
2. **先迁移基础生命周期。** 新建初始化/启停锁、只读准备、DNS 发布、私有 nft 持久化与失败清理骨架，覆盖 IPv6 和新缓存，不整段复制旧脚本。
3. **迁移订阅事务及身份。** 合并 YAML/marker/临时规则恢复，拆出已被上游覆盖的 parser hunks，保留密码字节和精确身份保护，另写 190→198 的类型/分组/引用迁移。
4. **重建测试输入和门禁。** 旧测试继续保留；新增 v198.2 真订阅器/生成器和新 fixture。检查最终 JSON/YAML、真实 UCI 行为、核心能力、依赖、安装模式及每设备 rootfs。
5. **先单包、后固件、再测试设备。** Linux 上先编译核心及 LuCI，运行核心配置校验和原有网络命名空间测试，再构建目标固件。测试设备覆盖保留配置升级、并发更新、断网/超时、失败回滚、DNS/IPv6/UDP及共享核心共存。

关键验收应包含：DNS 发布失败仍可用；无效订阅组完整保留；YAML 写入成功但 UCI/激活失败可以恢复；`+`/`%2B` 等密码进入最终核心配置后保持字节；旧引用指向相同合法节点或有明确迁移结果；后台进程不继承锁；停止后不会恢复陈旧 nft 规则。仅有旧测试通过或新版软件包编译成功不够。

## 5. 已完成的验证与限制

- 固定 tag 与提交一致；所有 962 个上游文件按原始 Git blob 导出并记录 mode、大小和 SHA-256；原始许可证保留。
- 当前包由真实项目 helper 还原；第二次执行返回 0，61 个文件字节一致；输入哈希核对项目基线。
- 25 份补丁分别对干净 v198.2 正向、反向 `git apply --check`：仅 #22 正向通过，全部反向失败。这只是文本检查，不作为“功能缺失/已实现”的判定。
- 12 个旧源文件 blob 均与新源不同；实际生产来源检查拒绝新版，试验前后原包字节相同。
- 新源码、派生源码及清单使用临时 Git index 检查提交后的字节保持，不改真实 index。上游唯一需要强制加入的忽略文件及 Windows 链接/权限处理见 [维护说明](../maintenance/plugins/ssrplus/README.md)。
- [独立验证结果](../maintenance/plugins/ssrplus/verification-results.json) 复核了 1023 个新旧源码 blob；在临时 index 按清单恢复 mode 后，新上游 tree 精确还原为 `fe37ff9ab420e178544ff2c7402b34c387f32b44`。Windows 普通暂存的执行位/链接退化有 52 处，清单完整保留原始模式，不代表当前磁盘已具备 POSIX 可执行/链接语义。
- 没有执行上游启动/更新脚本，没有应用任何迁移补丁到生产源码，没有运行完整回归、交叉编译、真实核心连接或设备升级测试。静态审查不能据此证明新版或当前版长期稳定。

## 6. 与同时进行的工作区修改分开记录

评估期间，HEAD 仍是 `6d76ce1`，但工作区另行出现 Passwall/Sing-box 及 Xray `26.7.11` 兼容补丁、测试和调用入口。这些不是本次评估写入，也未被本任务覆盖。还原使用的 25 个 SSR 补丁和五项输入已核对固定基线哈希。

新增 Xray 适配若完成，会把当前工作树候选从 kenzo `26.3.27` 提升到 `26.7.11`；它仍不是 fw `26.10.21` 加十补丁。观察到的新 helper 校验精确旧/新配方 blob，并要求 Go 至少 1.26，因此既没有解决 Go 1.27 要求，也会对 fw 新配方形成额外拒绝点。未来实施应基于届时最终提交重新核对这部分，不能直接套用本报告中的旧调用行号。
