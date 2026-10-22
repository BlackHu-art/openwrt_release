# SSR v198.2 lifecycle / DNS / persistence patch assessment

本报告仅核对固定 `45893d778767f3bdb2fcb6e873cf8f9a667d94d4`（v198.2）源码与本地 HEAD `6d76ce1` 中的指定补丁，不执行上游脚本，不改仓库。按补丁全部 hunks 的功能分组逐项追踪。没有以 apply 失败推断缺陷，没有对 router/netfilter/real dnsmasq 作运行验证。

行号约定：上游路径均相对 `maintenance/plugins/ssrplus/upstream-v198.2/luci-app-ssr-plus/`；`init`=`root/etc/init.d/shadowsocksr`，`rules`=`root/usr/bin/ssr-rules`，`gfw`=`root/usr/share/shadowsocksr/gfw2ipset.sh`，`update`=`root/usr/share/shadowsocksr/update.lua`，`monitor`=`root/usr/bin/ssr-monitor`，`switch`=`root/usr/bin/ssr-switch`，`scheduler`=`root/usr/share/shadowsocksr/ssrplusupdate.sh`。补丁行号相对 `wrt_core/patches/`。`runtime`=`wrt_core/compat/ssrplus/runtime.sh`。

## 总览

| 顺序/补丁 | 结论 | 迁移优先级 | 已覆盖与必须保留的边界 |
|---|---|---|---|
| 1 startup-lock | 保留目标、重写 | P0，基础依赖 | 上游仍旧锁实现；生命周期串行、锁失败退出、daemon FD 关闭、整次 restart 锁需要保留 |
| 2 dns-transaction | 部分覆盖，主体重写 | P0，与 1/5 配套 | 上游已去除非 GFW 的两种 set 指令；Netflix/oversea 分支已删除；私有生成、真实 dnsmasq 验证、原子单文件发布、错误传播未覆盖 |
| 3 updater-validation | 部分覆盖，主体重写 | P1，但发布升级前必须完成 | 新增 ip6_data 验证；其他下载限制、锁、私有 scratch、源文件提交/回滚、统一 activation 未覆盖 |
| 4 persistence | 部分覆盖，主体重写 | P0，与 8 配套 | 上游列表 metadata CR/LF 处理已覆盖；原子快照、失败保留上次文件、导出错误传播未覆盖 |
| 5 availability | 部分覆盖，主体重写 | P0 | 上游 UCI 参数引用和 IPv6 解析有改进；有界解析、有效缓存、只读 preflight、清理错误传播未覆盖 |
| 7 monitor-scheduler | 部分覆盖，按新模式重写 | P1 | switch 已合并为一次 restart；失败仍被吞；monitor DNS/KCP 直接启动仍在；scheduler 仍绕过 lifecycle |
| 8 persistence-lifecycle | 部分覆盖，主体重写 | P0，风险最高 | 上游补了普通 IPv4 snapshot restore 的策略路由；私有快照隔离、独立锁、身份安全 daemon、checked restore、成功后指纹提交未覆盖 |
| 10 dns-forwarding | 主能力覆盖，保留本地保护并重写 | P1（preflight 接入前必需） | GFW nft resolver bootstrap、无 ipset 调用路径、启动后 -P 已覆盖；prepare-only、正确地址解析/族检查、错误传播未覆盖 |
| 11 custom-ports | 上游完整覆盖，可以停用 | P2，移除重复补丁 | global dports 默认值及 global custom_ports 读取已等价实现；保留行为测试 |

优先级是迁移实施次序，非新增漏洞严重性。P0 要先形成可测试的启动/停止/失败收敛骨架；P1 连接外围调用；P2 清理已覆盖补丁。

## 1. ssrplus-startup-lock.patch

本地全部修改块：补丁 4–34 删除 `set_lock/unset_lock/unlock` 并简化 `_exit`；35–58 关闭 daemon launch FD9、删除 `check_server` 中递归 restart；59–83 将 start/stop 私有化及 boot 接入；84–97 去除后台 kill 管道；98–121 将 reset 及 start/stop/restart/reload 统一纳入 runtime 锁。

上游对应证据：

- `init:869–896` 仍 `exec 1000>LOCK_FILE`、`flock -xn 1000`，`unset_lock` 会删除锁文件；`unlock` 按文件存在最多等约 10 秒后调用 unlock。`init:3091` 与 `3212–3213` 未检查获得锁的返回码。
- `init:1086–1110` 的后台 launcher、`2948/2958` 的 service_start 没有关闭生命周期 FD；以后切换 FD9 后必须同时改 launcher，否则 daemon 保留锁。
- `init:2624` 仍从 `check_server` 递归 `/etc/init.d/shadowsocksr restart`；`3184` 在启动末尾才调用。移入单锁后若保留递归入口，会产生自等待/超时路径；应在加载配置前修正引用而不嵌套重启。
- `init:3279–3285` kill 管道仍 `&`，`3322–3329` reset 仍先 stop 再单独 set_lock。上游没有自定义 restart/reload，不能视作完整 restart 临界区。
- 本地依赖不只补丁：`runtime:4–17` 才是固定 inode、30s 等锁、信号/EXIT trap；`runtime:142–167` 是整次 start/restart 实现。迁移若只保留 patch 文件而漏装 runtime，不成立。

建议：重写入口，保留 upstream 新增 `clash_cache` EXTRA_COMMANDS 的功能；所有会写 shared runtime/cache 的入口也需明确与生命周期的协调。不能直接复制 190 start/stop（会丢失 HTTP、Mihomo、IPv6 清理）。上游 start 的 `! start_rules` 失败路径会自行 `stop`（3110–3114），锁内应改走私有清理函数，避免重新进入公共锁。

必要回归：锁失败不进主体；两个 restart 完整串行；SIGKILL owner/worker 的正确锁归属；所有核心/monitor/switch/KCP 启动不继承 FD；重复 start 替换现有进程；stop 失败不再 start；kill 管道全部完成才返回；reset 与并发 restart 串行。参考 `tests/test_ssrplus_runtime_regressions.py:171–272,515–536`、`tests/test_ssrplus_runtime.py:122–207,428`。

## 2. ssrplus-dns-transaction.patch

本地全部修改块：

- 补丁 4–86：init 的 ChinaDNS 输出错误检查；Apple 仅改私有副本；begin/generate/publish/restart 与返回码；无主节点的 deny/adblock 生成错误传播；把 clean 文件放入 stage；restart 保留旧 published DNS。
- 91–196：gfw generator subshell/fail-fast/可接受 grep 无结果；Netflix 临时文件私有化与直接 sed；oversea 转换；非 GFW 清除两种 set 指令；black/white/deny/adblock 的 stage 清理与错误传播；直接调用 generator 重入 lifecycle reload。
- 201–433：updater 私有 scratch、移除对 dnsmasq 实例文件/active path 的直接依赖、全部 converter scratch 重定向、失败状态累积、全部类型 activation、同内容重试 activation、原子 canonical replace、入口退出码及 cleanup。其 activation 和下载逻辑之后被第 3 项增强，应以最终 2+3 语义迁移，不复活早期直接 chinaipset 路径。

上游对应证据：

- `init:3093–3094` 启动先写 active `conf-dir` 指针；`gfw:33–34` 直接复制到 active directory；`gfw:56/90/111/143` 在 `/etc/ssrplus/*.clean` 写删中间文件。`init:3183` dnsmasq restart 返回码未检查，没有 validate/atomic bundle。
- `init:1450–1456` Apple 仍原地 sed `/etc/ssrplus/applechina.conf`，之后 copy；不是私有预备。
- `init:3064` generator 返回码不直接传播；`3110–3115` 现在有规则安装失败处理（部分错误检查覆盖），但 `3117 start_dns` 和 `3120 -P` 仍未检查；`3135–3175` 无主节点 deny/adblock 写入也未 fail-fast。
- `gfw:36–47` 已在非 GFW 同时删除 ipset/nftset，因此这一小块可停用。Netflix 已从完整新 gfw/init/update 流程删除；`init:1186–1196` 将 oversea 迁到 router，新 UI 只列 gfw/router/all (`client.lua:105–108`)：旧 Netflix 和 oversea 分支不要搬回。
- 新 `gfw:24–30,43,96–100` 使用带 `4#`/`6#` family 的 nftset，白名单改为 `whitelist_domain`/`whitelist_domain6` 并不再额外 `server=/.../127.0.0.1`。新的精确域名过滤 (`gfw:61–86`) 也应保留；不可拿本地旧 generator 整体覆盖。
- `update:13–30` 仍依赖读取实际 dnsmasq instance file，固定 `/tmp/ssr-update.*` 贯穿 `82–138,151–258`；`232–244` 直接复制 canonical/active 并调用 gfw2ipset 或 chinaipset；`224–229` 相同 MD5 不再 activation；`267–286` 失败也 `os.exit(0)`。

建议：保留 1+runtime 的独立 stage -> installed `dnsmasq --test` -> 单 bundle rename；建立 gfw generator 的纯准备入口，而非整段回退到 190。将新 `set_ipv6_dns_filter start/stop` (`init:143–159,3116,3303`) 纳入成功提交/失败回收，preflight 不得触碰 DHCP UCI。旧紧急 DNS 清理只管 `_unused_ssrp_changed`（runtime:27–41），需加入 IPv6 filter marker 恢复。

必要回归：copy/sed/read/rename/dnsmasq-test/restart 分别失败时 active bundle 完整；空 grep 正常、读错失败；并发读者只见完整旧/新 bundle；无主节点 deny/adblock；Apple canonical 不变；fresh router ChinaDNS；IPv6 开/关下每条 nftset 对应存在的 family/set；whitelist_domain 行为；启动失败后 AAAA filter 恢复。参考 `test_ssrplus_runtime.py:239–386`、`test_ssrplus_runtime_regressions.py:307–452,562`，删除旧 oversea/Netflix 断言或改成配置迁移断言。

## 3. ssrplus-updater-validation.patch

全部修改块：补丁 4–36 增加 URL shell quote、worker 全事务 FD8 锁及 fd/proc 验证、curl >=8.4 gate；37–末尾替换 update：16MiB 上限、connection/total deadlines、协议限制、HTTP错误、封装/域名/CIDR/DNS directive 校验、checked file write、hash、pending/staged/backup、同内容重新 reload、失败 canonical rollback（保护更新的外部写入）、cleanup/错误报告。

上游对应：`update:149–152` 仍 URL 拼 shell、`curl -sSL --insecure` 无 -f/总时限/大小限；没有 updater 锁或私有 scratch。新增 `update:154–176` 用 `luci.ip.IPv6` 校验 ip6_data 并拒绝空列表，只有这个新类型覆盖一部分“内容验收”目标。`update:232–246` copy/activation 失败不控制成功输出；`267–286` 退出码仍为 0。

建议：保留目标、重写 updater transaction；保留上游 `ip6_data` 入口（261–270）及自动更新开启条件（291–294），将 IPv6 CIDR 作为明确的合法类型，不可交给本地 IPv4 或 DNS validator。NFIP/Netflix 类型已移除，不恢复。IPv6 canonical 更新也必须走统一生命周期，并让 persistence cache 的内容指纹覆盖 `china6_ssr.txt`。

锁次序注意：updater FD8 锁必须在调用 init 子进程时关闭（本地 call wrapper）；init 的 FD9 与 ssr-rules 自己的 FD8 锁是不同资源；后台进程不得继承任一个。不要让更新持锁进程与同名 FD 的持久化脚本形成继承死锁。

必要回归：HTTP404/200HTML/空/零规则/超限/timeout/带引号与 & 的 URL；IPv4/IPv6 CIDR 混入和边界；curl旧版 gate；forged lock marker；并发/kill worker；copy/rename/backup失败；activation失败 canonical回滚且pending保留；外部新canonical不被覆盖；同内容重试activation；所有类型返回非0。参考 `tests/test_ssrplus_updater_regressions.py:255–491,586–591`，新增 ip6_data 全矩阵。

## 4. ssrplus-persistence.patch

全部修改块：补丁 3–139 在 force/export 时保留旧快照、同目录 mktemp、完整 table inventory/export 检查、所有 metadata 逐行 comment、checked chmod+rename；140–174 去除 force/update/mode-change 的提前删除；175–192 full rebuild 对 persist failure 返回非0。

上游部分覆盖：`rules:1278–1283` 新 `append_nftables_comment` 把 CR/LF 折为空格；`1321–1326` 六个用户 IP 列表通过该函数写为一行注释。该列表多行逃逸目标已覆盖，不应报告成“上游完全没修 metadata”。但 `1319–1320` runmode/server 等仍直接 echo，不能把局部 helper 等同于任意 metadata 都被处理。

尚未覆盖：`rules:1291–1294,1441–1442,1913–1915,1948–1952` 先删旧文件；`1309–1348` 直接追加正式快照；table export 返回码不控制完整性；`1352` 只用 HAS_RULES/非空/grep 检查；`1960–1962,1986–1988` 即使 persist failure 仍 exit0。

建议：迁移原子发布/保留旧文件/失败传播，复用上游 metadata helper 但让 helper 写 staged file；保留 `# IPv6 schema: 1`、support flag（1317–1318）与新 whitelist schema，不能漏掉这些恢复判据。

必要回归：CR/LF/反斜线/多行列表 metadata；列举table失败、某table导出失败、无table、write/chmod/mv失败都保留旧快照；强制更新/模式改变/IP列表改变同样保护；caller收到failure。参考 `tests/test_ssrplus_persistence.py:121–239`，新增 IPv6 schema/head 保留检查。

## 5. ssrplus-availability.patch

全部修改块：补丁 4–10 snapshot私有目录；11–23 UCI参数引用并传播set失败；24–77 host/IP有效性、有限DNS/HTTP解析、有效缓存、prepare不commit；78–124 launcher/service_start/防火墙写入的prepare guard与非JSON清单；125–180 get_host_ip失败传播、snapshot迁移归rules负责、-K/-X/-f失败传播；181–186不再按ps grep杀rules；187–末尾 private preflight。

上游对应：

- `init:112–120` 参数已引用，但没有 `uci set || return`，commit可掩盖set失败。
- `init:799–832` 新支持 bracket IPv6 literal及resolveip -6 fallback（仅IPv6启用）；IPv4 regex只形状校验，HTTP fallback `819` 无deadline/上限/HTTP错误验证，失败不回退有效cached IP。`823` 每次commit；`3014/3020` 不检查解析结果。
- `init:3053–3060,3226–3241` 仍公共snapshot搬移及unchecked -K/-X/-f；`3284` 仍grep ssr-rules杀进程。`init:3110–3115` 已对start_rules安装失败停止服务，但这发生在 `Start_Run/start_http_proxy` 后，不能等价于“替换前无副作用预检”。
- 没有 SSRP_PREPARE_ONLY/ssrp_preflight，启动立即产生 core、规则、DNS/UCI改动。

新增路径使旧preflight原封不动不安全：

1. `load_config` (`init:2525–2535`) 会重写/commit SOCKS/HTTP节点字段；`normalize_run_mode` (`1190–1193`) 和 `normalize_xray_protocol_nodes` 会迁移UCI；`start_dns` fallback (`1307–1325`) 会commit新模式。prepare必须禁止这些写入，或在独立候选状态上进行。
2. `Start_Run` 的 Clash路径调用 `download_clash_config`；`init:482–586` 写 `/etc/ssrplus/clash` cache/hash，remote hash/download只connect timeout而无总时限。preflight必须私有缓存/有界下载，不能意外改变正式缓存。
3. `prepare_clash_runtime_config:726–735` 会搬移/链接持久化cache.db；Mihomo TUIC/SS/V2Ray配置为 YAML，旧只扫 `$TMP_PATH/*.json` 的 jq validator覆盖不足。新 HTTP代理也需进入准备/验收清单。只是扩展glob并不足以验证Mihomo语义。
4. IPv6 literal/AAAA fallback必须保留；不能用本地强制 `resolveip -4` 替代上游新IPv6路径。cached地址需跟IPv6开关/地址族兼容。失败回收还需 AAAA filter 和 IPv6 bridge sysctl。

必要回归：有限解析、invalid literal/response拒绝、有效cache fallback、set失败不被commit遮蔽、prepare不写UCI/cache/firewall不启动进程、JSON/YAML及HTTP配置错误先于stop、clash只有配置文件/URL无server字段也可预检、正常新节点类型不被旧get_host_ip规则误拒、failed cleanup仍恢复DNS。参考 `tests/test_ssrplus_availability.py:29–210`，新增上述v198.2类型与IPv6矩阵。

## 7. ssrplus-monitor-scheduler.patch

全部修改块：补丁 4–287 monitor整段重写为“故障统一restart，检查restart状态并退出”；各TCP/UDP/server/KCP/local/DNS1–6和独立China listener；288–301 scheduler失败即停、去掉直接chinaipset；302–末尾 switch一次restart、错误向调用者传播。

上游覆盖/缺口：

- `switch:153–156` 已是单次 restart（本地由 stop+start 改为restart的目标覆盖），但马上 `return 0` 吞失败；`207–213` 两条switch调用后继续成功日志并return0。节点选择现在先 `set_main_server` (`145–150`)，迁移错误处理要明确失败后选中节点状态，不可照抄旧的success后commit假设。
- `monitor:94–98,108–112,118–123,139–144,201–206` 某些故障会restart但忽略状态；server/local还先直接kill。`127–134` KCP直接重启；`148–199` DNS1/4/6仍独立启动。mode4恢复甚至用 `/etc/mosdns/config.yaml` (`165`)，而init启动用 `$TMP_PATH/mosdns-config.yaml` (`1351–1357`)；这是当前固定上游两条路径不一致的直接静态证据。
- `monitor:210` China5333检测仍靠旧DHCP marker，但 init `1438–1442` 用私有conf并不置marker，fresh router路径不应依赖它。
- `scheduler:2–33` 新增目录锁、loop interval，但 `35–39` 仍忽略update失败，直接chinaipset，然后订阅；`41–43` 无论前步是否成功均写运行时间。

不能整段覆盖 monitor：新 `monitor:27–40,48–62,88–107` 有ipt2socks线程数检测；server/local新匹配Mihomo相关名称；mode7内置DNS需保留 (`201–207`)；DNS2socks 2/3和DNSPROXY5已不在新UI (`client.lua:131–143`) /start_dns分支，旧这些监控不要重新加入；新mode6启动是5335与300两个独立listener (`init:1397–1398`)，旧只查300依然不能覆盖两个的完整健康。

建议：保留上游检测目标与线程数，替换所有恢复动作到checked lifecycle；China5333按真实启动条件（router、非builtin、非0、chinadns既非空也非none）及端口识别；mode7按所选核心判断。scheduler保留loop feature，但在成功activation之后才订阅/更新时间，去掉绕过事务的chinaipset。目录锁SIGKILL残留的处理属新调度实现需要验证的点，不能以旧r6/r7记录断言上游同bug。

必要回归：每个存续DNS模式1/4/6/7健康与单组件死亡；mode6只剩一个listener；新ipt2socks线程计数；KCP/server/local恢复绝无锁外kill/launch；fresh router5333/none/builtin条件；restart失败无成功日志；stop并发下排队；scheduler失败不订阅不stamp、订阅failure传播、loop并发与中断锁回收。参考 `tests/test_ssrplus_monitor_scheduler.py:215–279,415–443`，删除已撤模式断言并新增6双listener/7。

## 8. ssrplus-persistence-lifecycle.patch

全部修改块：补丁 3–131 私有目录、独立永久锁、内容指纹、success marker、legacy迁移、PID+starttime+精确argv身份、snapshot SSR-only parser；132–313 cleanup/flush错误传播与最终状态验证；314–356 固定原子fw4 shell hook；357–499 child PID和有界关闭daemon；500–583 checked单nft事务restore+IPv4路由及内部入口；584–623 CLI锁/marker在锁后复查/错误码；624–末尾成功后指纹与marker提交、重建/恢复启动daemon的错误传播。

未被上游覆盖的主要链路：

- `rules:55–56` 仍把动态snapshot放fw4公共ruleset-post；`1169–1186` include先删SSR tables再裸`nft -f`，没有白名单或dryrun；`1455–1497` 普通restore先flush后加载，不能保存原live state。
- 没有独立persistence锁；`1370–1432` daemon仍后台subshell写 `$$`（1382–1383）而父进程 `$!` 仅日志验证；stop拿PID就kill，不验证starttime/argv，不等待停止；CLI -K (`1614–1616`) 固定exit0。
- `flush_r:240–246` 固定return0，`flush_nftables:249–315` 忽略cleanup错误；full setup `1958–1988` 未检查persist/daemon/gen_include返回的全部结果。
- 主要cache比较记录配置列表和XHTTP (`1726–1937`)；没有 canonical China CIDR文件内容指纹，因此要保留ignore list指纹，并新增china6指纹；旧SHUNT/Netflix指纹不带回已移除功能。

上游已覆盖的部分：`rules:1487–1491` 在普通IPv4恢复后检测TPROXY链并补fwmark rule+local route（priority999），这是本地恢复补路由目标的部分覆盖。`1466–1478` 增加whitelist_domain/schema/IPv6开关检查，IPv6启用或含gfwlist6时一律拒绝恢复并走普通完整重建；不要移植本地旧restore时删除这些判据。

IPv6冲突是本项阻断点：`root/usr/share/shadowsocksr/ipv6.sh:90–176` 把IPv6 sets/chains放 `inet ss_spec`，所以“两张表allowlist”可覆盖该结构，不能误写为需要新ip6 table。但是nft快照没有 `ip -6 rule/route` 或bridge sysctl，`ipv6.sh:7–31` 管理这两类状态，`180–192` 在normal setup时生成并补策略路由。旧本地 restore只恢复IPv4，若直接替换上游restore会接受IPv6快照却漏IPv6路由/bridge状态；若只保留上游拒绝IPv6snapshot的guard，然后让新的fixed hook调 `-R`，fw4 reload后又无法恢复IPv6代理。必须明确设计IPv6-aware checked restore或在hook上做完整受控重建，同时保证基本fw4 NAT不受坏snapshot影响。

另一个细节：当前上游fw4 include裸加载snapshot (`1179–1180`) 绕过普通restore的schema/IPv6拒绝检查，所以“普通启动已重建IPv6”不能当作fw4 reload生命周期已覆盖。

建议：保留私有snapshot/固定hook/独立锁/身份safe daemon/成功后fingerprint commit方案；对v198.2重写snapshot schema、IPv4+IPv6路由/bridge恢复与cleanup；lock后复查auto-restore意图避免排队hook在stop后复活规则。snapshot迁移只从允许的私有备份来，旧公共include直接撤销而不执行其中内容。

必要回归：-P/-R/-K/-X/-f/normal setup并发锁；坏snapshot不影响fw4 NAT；SSR-only parser拒绝foreign table/flush/include/括号与字符串逃逸；原子nft dryrun/apply失败不损坏现有SSR；IPv4/IPv6 policy和bridge恢复；stop后排队hook不复活；内容更新后重建及失败后指纹不前移；stale/reused PID不误kill、正确child有界停止、锁持有时pending export可中断；daemon/hook publication失败保留旧文件；升级/降级IPv6、旧whitelist/schema走重建。参考 `tests/test_ssrplus_persistence_lifecycle.py:154–441`，新增IPv6真实network namespace或路由器测试。

## 10. ssrplus-dns-forwarding.patch

全部修改块：补丁 10–37 给nft GFW直接插resolver、prepare guard、IPv4合法性/现存set检查、backend guard和兼容重复ipset；38–65 init/MosDNS无需HAS_IPSET也调用且传播错误；66–末尾DNS启动后刷新private snapshot。

上游 `init:1268–1278` 已添加nft GFW resolver bootstrap；`1332–1334,1343–1349` 调用不再受HAS_IPSET限制；`3118–3120` DNS后 `ssr-rules -P` 更新snapshot。所以“fw4无ipset时DNS根本不入set”已覆盖，不能继续保留同一个bug叙述。

尚未覆盖：上游 `${2%:*}` 没验证literal/地址族/现存set，插入失败后固定return0；init start_dns与snapshot -P也不传播失败。没有prepare-only，所以第5项preflight直接复用它会改live set。旧补丁的“skip IPv6”是190仅IPv4基线约束；v198.2有gfwlist6，不能把它说成新IPv6功能的完整实现。UI tunnel_forward目前仍限制ip4addrport (`client.lua:145–160`)，MosDNS字段允许tcp IP或tls DOMAIN (`163–172`)，因此分类型解析并对支持的IPv6输入选族/否则明确跳过，不能简单截最后冒号制造IPv4元素，也不能把hostname误当IP。

建议：停用已覆盖的原backport能力块，将guard/checked invocation作为preflight和DNS事务补丁的一部分重写；snapshot刷新通过第8项新私有事务，保留rules -> DNS bootstrap -> snapshot -> DNS publish顺序。旧oversea ipset分支已移除，不恢复。

必要回归：nft+无ipset GFW resolver成功；prepare不查不改live firewall；无set不造空table；无效IP/IPv6/URL/domain/多resolver地址处理；单插入失败停止activation；既有ipset member不误失败；snapshot包含bootstrap地址；v6启用后若支持v6resolver必须只进gfwlist6。参考 `tests/test_ssrplus_followup_fixes.py:135–187,212–228`，把“永远skip IPv6”改成新支持策略的测试。

## 11. ssrplus-custom-ports.patch

唯一hunk（8–18）将global dports默认值设1，从 `global.custom_ports` 读取，取代从节点读取。

上游 `init:3036–3044` 已完全等价：global dports默认1、global custom_ports、值非空才生成 `-m multiport --dports`；`3078` 原样交给ssr-rules。UI字段在global区 (`client.lua:122–129`)。可以在新版本patches.list停用整项。无需拿历史commit ancestry当证据，固定tag实际代码已证明等价。

必要回归：global与node字段不同值时只取global；all/custom空值不继承node端口；常用端口preset保持；验证最终ssr-rules命令和nft规则（特别IPv6新规则）包含预期端口。参考 `tests/test_ssrplus_followup_fixes.py:194–206`。

## 建议实施顺序与验证界限

1. 固定v198.2源码与当前本地最终行为分别留基线；先移除11的重复hunk、拆开10/4/7已覆盖的小块，不机械复制旧文件。
2. 1+runtime、5的新preflight、2的DNS transaction作为一组：锁和private generation先可验证；prepare覆盖所有v198.2路径后才能称无副作用。
3. 4+8一组实现私有快照和v198.2 IPv6-aware lifecycle。目录迁移、fw4 hook和PID策略不能分散成半迁移状态。
4. 将3+7+10接到同一checked activation；再适配其余agent审查的订阅、核心配置、firstboot/包声明。
5. Linux fixture/故障注入及shell/Lua语法是必要门槛，但不等于实际OpenWrt fw4/nft事务、dnsmasq jail、Mihomo语义、IPv6 TPROXY真实数据面验证。此次未执行这些测试，不可声明修复或上机可用。

已读本任务9项补丁的全部内容以及上述固定tag调用路径；没有使用旧记忆中的r6/r7回归推断上游行为。

返回 [迁移评估总表](../ssrplus-v198.2-migration-assessment.md)。
