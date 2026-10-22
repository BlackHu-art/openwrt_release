# SSR v198.2 订阅、初始化与引用迁移只读评估

范围：patches.list 第 6/13/15/17/18/20/22/24 项，共 47 个 hunks。对照当前 190-r11 还原源码与 fw876/helloworld 固定 commit `45893d778767f3bdb2fcb6e873cf8f9a667d94d4`（v198.2）。没有执行上游脚本、修改仓库代码或运行全测试。下列 `U:` 路径相对 `maintenance/plugins/ssrplus/upstream-v198.2/luci-app-ssr-plus/`；`C:` 相对项目目录 `maintenance/plugins/ssrplus/current-190-r11/`。所有结论是逐 hunk 与上下游调用路径核对，不是 apply 结果推断。

## 结论矩阵

| # | 补丁 | 结论 | 分项风险 |
|---|---|---|---|
| 6 | subscription | 保留安全目标，整体重写；上游仅覆盖空下载保留等小部分 | 高：事务状态新增 YAML、转换URL/groupHash、订阅子项、临时防火墙绕过；旧回滚范围不足 |
| 13 | firstboot | 与15合并重写，保留非破坏性 checked initializer | 中：初始化锁、原子发布、失败重试、保留用户配置及新默认节 |
| 15 | initialization-order | 保留最终顺序约束，合并13；无需重演历史错序 | 中：本地r6引入的错序回归，不能写成上游reset的同一缺陷 |
| 17 | subscription-auto | 原删除hunk已无对象，可移除；自动选择和显式偏好契约必须另行处理 | 高：上游主动删除旧ss_type，且Rust优先不再根据SS传输参数选Xray |
| 18 | ss-parser | 部分覆盖：Xray SS主凭据算法覆盖；空userinfo拒绝和所有once-decode仍保留/重写 | 中高：合法凭据和路径被改写或畸形节点发布 |
| 20 | transport-config | 部分覆盖：SS/Trojan finalmask、Trojan serviceName覆盖；其他字段修复仍需保留 | 中高：最终核心JSON字段不匹配，订阅成功但连接错误 |
| 22 | ss-password | 保留，目标内层密码解码缺陷仍在 | 中高：原生SS密码字节改变，迁移后会重新引入已修问题 |
| 24 | node-references | 保留狭义历史身份兼容目标，但不能充当190→198配置迁移；适配新状态模型 | 高：类型/组hash变化、Mihomo聚合、SID引用与运行策略变化 |

## 6 subscription：全部6个hunk

1. 订阅进程锁（patch行3）：U:root/usr/share/shadowsocksr/subscribe.lua:7-26 仍直接打开 LuCI cursor，无进程独占锁。应保留在打开任何UCI cursor之前上锁和进程退出释放、不unlink inode的目标。
2. 私有 native UCI savedir、共享delta拒绝、checked finish（patch行23）：上游同处仍使用共享LuCI cursor。需移植native cursor/journal，但finish必须统一清理新增direct_bypass（U:subscribe.lua:3018-3036）；不可直接os.exit绕过其cleanup。
3. MD5写入返回值（patch行104）：U:subscribe.lua:2085-2092 已改JSON `{md5,hash,url}`，仍不检查writefile结果。要保留检查，但保留新结构和URL→group映射，不能写回纯MD5而破坏 read_old_groupHash（2058-2080）。
4. 主体parse/execute/rollback（patch行113）：上游2650-2652已对**空下载** loadOldNodes，2653-2656保留未改变组；并有单订阅更新的未选择组保留（2567-2576）。这些不是完整事务替代：2675-2685在解析前删旧marker并写新marker，2688先插入空nodeResult，2912仍对任何带grouphashkey或hashkey的旧节点全局diff；非空错误页面、全过滤、无有效节点等仍不具备本地“组解析成功才能参与diff、失败组保留”的保证。需保留组验证、端口范围、共享delta、字段级并发冲突回滚，且合入上游新订阅子项、AnyTLS/Snell、Mihomo、目标订阅选择逻辑。
5. checked节点创建、碰撞及字段写入（patch行578）：U:subscribe.lua:2957-2974复用一次临时sid的suffix，不检查add/delete/section/tset/set结果，不检查生成cfgid碰撞；应按新生成路径保留校验。旧hunk附带的domain_resolver/domain_strategy已不见于v198.2订阅与生成器，应按新DNS架构审查，不应机械加入失去消费者的旧字段。
6. selection与节点同次提交、同步restart、失败恢复、成功后MD5、非零退出（patch行622）：U:subscribe.lua:2978-3001先commit，随后分次global选项commit及后台stop/start/restart，不检查结果；3022-3034错误恢复也后台执行后直接报成功。核心目标均未覆盖。需与移植后的init失败返回契约一起验证。

新增事务边界：

- U:subscribe.lua:2864-2871直接覆盖 `/etc/ssrplus/clash/<groupHash>.mihomo.yaml` 再创建UCI总节点。即使加入原UCI journal，失败时恢复节点也可能仍指向已换内容的同一路径。需要YAML先验证、stage、原子发布及可恢复旧文件，纳入失败注入测试。
- U:subscribe.lua:2580-2585普通模式hash(url)，Mihomo模式hash(fetch_url)，模板、转换参数及模式变更会改变组身份；旧marker删除也应推迟到成功激活，不能只journal当前组。
- U:subscribe.lua:927-941合法本地Clash总节点使用server=127.0.0.1、port=0；旧parse_group对所有节点的loopback/端口过滤不可无条件套用新总节点，否则会拒绝正常Mihomo节点。应按节点类型验证真实契约。
- U:subscribe.lua:2707-2729识别SSD/SIP008原始table；2768-2771却先把所有table直接当result，绕过processData(szType,v)。这是为Anytls预解析table新增的支路（2736-2757），不等价于本地table格式支持。普通SIP008缺hashkey，后续2889写nil索引；普通SSD使用port而非server_port，会在2795被判无效。重写应先识别szType，再接纳已解析table；加入三种格式混合测试。此结论来自静态可达路径，未执行上游代码。

最强反例：A订阅返回非空错误页/全过滤，B有效，上游已前移marker并允许空组参与删除；或生成Mihomo YAML后commit/restart失败，UCI回滚但YAML仍是新内容。合法对照：A失败完整保留、B可独立成功，失败组marker不推进，激活失败完整恢复旧UCI+YAML且保留并发未写字段。

## 13 firstboot（5hunks）与15 initialization-order（2hunks）

13的命令注册、原子模板安装函数、锁包装入口三hunks目标均未被上游覆盖：U:root/etc/init.d/shadowsocksr:85-87只注册reset/clash_cache，3322-3329 reset先stop再删除配置并cp模板；没有initialize。13的defaults插入/删除reset两个hunks，以及15把调用移至原reset位置两个hunks，应合并成一个最终实现：已有非空配置先执行上游保留配置迁移，再调用checked initializer，最后sed转换（U:root/etc/uci-defaults/luci-ssr-plus:31-127、129-134）。保持非空（包括格式损坏）用户文件不被模板替换、私有stage绝对UCI验证、0644、同文件系统rename、锁串行。

注意历史因果：r6错误将initialize放在已有配置迁移之前，r7才纠正；本地文档 docs/ssrplus-compatibility.md:74-83 已说明。上游v198.2仍用reset只是功能差异，不能据此声称它存在相同“先初始化再补ss-rust”的r6缺陷。v198.2本身已经没有补写ss_type的migration。

需要保留v198.2新模板节（http_proxy、clash_client_group）和新迁移（config_update_interval、component_mirror、filter_aaaa、pdnsd_enable、SS类型转换），但后者是否接受是配置兼容决策，initializer不得悄悄替项目决定。原模板安装不能替代用户已有配置迁移。验证包括缺失/空/非空/损坏配置、重复及并发初始化、模板缺失/非法/无global、copy/chmod/UCI/rename失败、绝对stage绕开运行时UCI覆盖和saved delta、新默认节可被LuCI读取。

## 17 subscription-auto：1hunk已被上游删去，但原契约不再成立

U:defaults:31-124没有旧“缺ss_type补ss-rust”语句，因此原删除hunk不需保留。**不能据此宣称本地r8目标全被覆盖**：

- U:subscribe.lua:41-85只检测Rust/Xray/Mihomo，preferred_ss_backend不读取ss_type，不再检测SS-libev，不根据链接type参数选择Xray。
- Rust+Xray、enable_mihomo非1：should_use_mihomo_mode为false，preferred_ss_backend返回ss-rust；1270-1278进native SS分支，1420-1546没有Xray WS/TLS传输设置。旧r7/r8“auto + transport SS走Xray”的保护丢失。
- U:init:1199-1265、3102启动执行normalize_xray_protocol_nodes，1255-1258删除ss_type/xray_hy2_type/xray_tj_type；U:luasrc/model/cbi/shadowsocksr/client-config.lua:305-360打开编辑页也迁移并删除这些配置。U:defaults:96-122按已安装核心迁移ss/ss-libev及Xray SS节点，甚至仅有Mihomo即可把Xray SS改type=ss。
- 固定v198.2没有ssr_type；SSR链接仍输出type=ssr（subscribe.lua:1050-1082），不要写成“新增Xray SSR/ssr_type”——那可能来自其他dev快照，不属于此commit。

迁移必须明确接受新的核心政策，或重新保留显式选择与链接能力判断；仅恢复缺省空值远远不够。必要矩阵：旧missing/empty/auto/Rust/libev/Xray/custom、纯SS与WS/TLS/HTTPUpgrade、Rust/Xray/Mihomo各种组合，以及defaults→init→打开LuCI→重新订阅全过程；观察最终运行核心与JSON/YAML，而不只看UCI字段。

## 18 ss-parser：14hunks逐类核对

- helper hunk1（patch行17）：decodedQueryValue仍无对应，上游继续UrlDecode；保留“只消费string/拒绝table、不可二次decode”契约。
- 凭据hunks2-3（行32、61）：U:subscribe.lua:1279-1312已经先切userinfo/host、percent-only解码、支持SIP002/whole-base64/plain、使用冒号分隔及colon-free扩展。可删重复主算法；但缺少本地 `userinfo == "" -> nil`。输入 `ss://@ss.example:443?type=ws` 在仅Xray模式可落空密码/none分支；继续保留空userinfo保护和无效组拒绝。
- SS Reality hunk4、SS WS/HTTPUpgrade/XHTTP hunk5、H2 hunk6、raw hunk7：U:subscribe.lua:1346-1348、1371-1379、1398-1399、1416-1417均仍对已解码params再次UrlDecode，未覆盖。
- Trojan WS/HTTPUpgrade/XHTTP hunk8、H2 hunk9、raw hunk10：上游1619已UrlDecode query值，1707-1715、1733-1734、1751-1752仍第二次decode，未覆盖。
- VLESS Reality hunk11、WS/HTTPUpgrade/XHTTP hunk12、H2 hunk13、raw hunk14：上游1756的URL.parse后，1832-1834、1845-1853、1871-1872、1889-1890仍第二次decode，未覆盖。

lua-neturl仍为1.2-1（U:../lua-neturl/Makefile:7-15）；真实库tests/fixtures/lua-neturl/v1.2-1/url.lua:84-93、204-240显示query已解码且+变空格。移植测试继续使用真实打包库，覆盖%252F/%2B、字面+、bracket table/重复参数、Reality spiderX/publicKey，并保持TLS Host规则由20修正，不把18旧条件重新带回。

## 20 transport-config：11hunks逐项核对

1. nonEmptyQueryValue（行5）：上游无对应，仍需使显式空Host按缺失处理，以允许生成器回退SNI。
2. SS finalmask（行16）：上游1357已写result.finalmask，覆盖；仅注释仍写finalmaskg，不影响语义。
3. SS WS/HTTPUpgrade Host（行29）：上游1371/1374仍因tls=1丢独立Host，未覆盖。
4. SS raw HTTP映射（行42）：上游1416-1417仍写tcp_host/tcp_path，生成器实际读http_host/http_path，未覆盖。
5-6. 原生SS外层Base64保留加号（行53/62）：上游1432/1440仍base64Decode(UrlDecode(...))，UrlDecode把+变空格，未覆盖。
7. Trojan finalmask（行71）：上游1690已写result.finalmask，覆盖。
8. Trojan TLS WS/HTTPUpgrade Host（行84）：上游1707/1710仍丢独立Host，未覆盖。
9. Trojan参数键与raw映射（行97）：上游1619将所有query key lower；1746已读params.servicename（该行覆盖），但1736-1743、1749仍读headerType/quicSecurity，1751-1752仍写tcp_host/tcp_path，余部未覆盖。
10. VLESS TLS/Reality WS/HTTPUpgrade Host（行129）：上游1845/1848仍以tls/reality条件清掉独立Host，未覆盖。
11. VLESS raw HTTP映射（行142）：上游1889-1890仍写tcp_host/tcp_path，未覆盖。

消费端证据：U:root/usr/share/shadowsocksr/gen_config.lua:618-635读取http_path/http_host；648-662读取ws_host/httpupgrade_host并回退tls_host；705-707读serviceName；893-899读finalmask。HTTP Host-only请求仍需填默认http_path='/'，否则生成器632的headers门槛可能不发Host。无需为已覆盖finalmask和servicename重复打补丁，但所有剩余字段必须跑完整新生成器JSON断言，并加入Mihomo转换支路（subscribe.lua:710-734、764等），不能只验证解析结果。

## 22 ss-password：1hunk仍需要

U:subscribe.lua:1458-1473仍对Base64已还原的密码进行isURLEncodedPassword启发式及UrlDecode。字面%2F会变成/，与当前r10/r11修复契约相反。保留去掉此内层猜测；外层percent解码应与20的+保留修复一起适配；原生分支现在可能输出ss（Mihomo）或ss-rust，不再是ss-libev，但密码字节规则相同。覆盖SIP002、整串Base64、Base64URL、外层percent escape、%2F/%252F/%2f/%FF/非法UTF8形状、真实slash和普通+，最终核心JSON及YAML都必须字节一致。

## 24 node-references：7hunks不能代替一般升级迁移

hunks1-2 private legacy identity表/局部legacy密码、hunk3重现旧密码猜测、hunk4双hash、hunk5构建一对一计划、hunk6写前计划、hunk7沿原SID更新：上游均无等价实现。U:subscribe.lua:2012-2019只算当前hash，2912-2919直接按hash删/改，2980-2999只处理global_server。

C:subscribe.lua:1894-1936明确限于同groupHash、r9 native SS错误密码的精确旧hash，并核对old.type在ss-rust/ss-libev、password及type/server/port/method/alias完全一致。它不做模糊身份匹配，不迁移所有引用，不修复任意凭据变化。190-r11已正确的密码不触发legacy兼容，只有current hash完全一致才会原位保留。

v198.2的类型转换、URL转换groupHash、Mihomo单总节点聚合、AnyTLS/Trojan/Hysteria类型变化都会改变身份；把24原样套入不会保持这些SID。尤其：

- defaults/init/LuCI可先改old.type但不重算old.hashkey；新解析计算新类型hash，不再等于190旧hash；24只替换password模拟历史hash，无法覆盖其他字段变化。
- U:init:2525-2535按enabled主动把socks5_proxy.server（及新http_proxy.server）写same/nil，旧独立SOCKS SID即使保存也会被启动路径覆盖。旧Netflix、UDP独立选择也应逐项与新UI/运行政策核对，不应声称保留SID就保留原策略。
- 如果坚持兼容旧r9密码身份，需在明确旧基线模型下计算历史hash，并在有歧义时写前拒绝，不能用新v198字段+旧密码冒充确切r9历史身份。对于190→198需独立迁移计划，不能扩大24的宽松匹配范围来掩盖。

必要验证：r9错误密码→新版本、190-r11正确密码→新版本；每种旧native/Xray/Mihomo模式；保留组与变组、单项更新、MD5命中但核心强制刷新、全局/UDP/SOCKS及其他当前仍支持引用；不同SID指向不同合法节点；相同alias不同凭据与多个旧SID争同一新节点；commit/restart/YAML失败和并发用户改写；在restart之前观察**实际已提交配置**，并启动对应新生成器验证真实endpoint与password。

## 回归保护与验证边界

现有有价值覆盖：tests/test_ssrplus_subscription.py:395-544（狭义r11迁移/歧义/并发）；546-670（凭据/once-decode）；671-976（事务/回滚/锁/shared-delta）；tests/test_ssrplus_core_config.py:193-373（选择到核心）、375-543（transport/密码）；tests/test_ssrplus_firstboot.py:154-525（真实defaults边界/顺序/保留值）。

但这些测试目前把订阅源固定到2abdc9aa（subscription.py:76-98）、生成器固定旧SHA/blob（core_config.py:20-22、44-49）、firstboot固定旧source-files.tsv（firstboot.py:33-53）。未改测试输入及新系统边界前，现有全部通过也不证明v198.2兼容。当前未执行测试；以上为静态证据审查。新的事务/初始化/解析测试应在隔离目录、禁网络、mock真实系统调用边界下验证，另需目标OpenWrt真UCI/LuCI/核心组合及重启验证。

恢复性：旧订阅事务对UCI字段有恢复能力，但v198.2新增持久化YAML和启动时配置迁移，使单纯回退软件包不足以保证恢复原策略；迁移方案应明确保留原UCI+受影响YAML及版本化状态的恢复路径。不能以补丁数量少或文本可应用判定低风险。
返回 [迁移评估总表](../ssrplus-v198.2-migration-assessment.md)。
