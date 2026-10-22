# SSR Plus 固件集成与验证

SSR 修复由项目构建流程自动应用，不依赖手动修改路由器或临时 build 目录。
当前审查基线是 `fw876/helloworld` 的
`2abdc9aa9e19607774dc9789709212b70b8607c6`，本地修复版本为 `190-r9`
（opkg 包版本为 `190-9`）。

## 以后编译如何带入修复

1. `custom_feed.sh` 导入 SSR 源码并记录实际上游提交。
2. `update.sh` 在 `feeds install` 之前调用 `fix_ssrplus_compat`，校验十二个
   受保护源文件的 Git blob，再按 `patches.list` 应用完整二十一份补丁并安装运行脚本。
   已完整应用的旧补丁可在隔离副本中还原后重新校验；未知或不完整修改会中止构建。
3. 包内生成 `/usr/share/shadowsocksr/ssrplus-build.json`，记录上游提交、
   修复版本、补丁 SHA-256 和十二个安装文件的 SHA-256/权限；默认模板为
   `0644`，初始化脚本及运行程序为 `0755`。
4. `make defconfig` 后检查实际配置：选择 SSR 时必须使用 firewall4、
   nftables 后端、dnsmasq-full 的 nftset 支持以及 flock。
5. 编译后、收集固件之前，校验实际 IPK/APK 的版本、文件内容、权限和内嵌清单；
   `CONFIG_PACKAGE_luci-app-ssr-plus=y` 时也校验公共 rootfs。启用按设备 rootfs
   时，还会校验 `build_dir/target-*/linux-*/target-dir-<ROOTFS_ID>` 下实际制镜像的
   每个根目录；不能只用公共 rootfs 代替按设备目录的校验。
   缺包、缺清单、旧脚本或不一致文件都会让构建失败。

`jdcloud_ipq60xx_immwrt.config` 默认选择 `luci-app-ssr-plus=y`，该路径会将
修复安装进固件。其他设备或自定义配置应确认最终 `.config` 中该选项为 `y`；
普通 `m` 配置只生成软件包。若已选设备的专用包列表明确安装 SSR，则也检查
实际含 SSR 的设备 rootfs；未选择 SSR 的固件不会被自动添加 SSR。

构建和发布工作流依赖 `.github/workflows/test_ssrplus.yml`。
它先运行项目回归，再在隔离 Linux 网络命名空间验证真实 dnsmasq/nft/锁和进程行为；
验证失败时不进入固件构建。全机型发布复用相同门禁。

## 修复范围

- 整个启动、停止、重载过程串行执行；真正后台进程不继承生命周期锁。
- DNS 私有生成、验证后原子发布；预检失败保留现有服务，替换后失败返回错误并尝试清理。
- 节点解析和规则下载有时限，下载内容通过规则验证后才发布。
- 订阅分组保留失败组及手工节点，使用一次受检查的同步重启。
- DNS 监测按实际运行配置检查所需进程和独立监听端口。
- nft 快照仅保存 SSR 自有表，校验后恢复；停止后禁止自动恢复，IP 列表内容变化会重建。
- nft GFW 模式将 IPv4 DNS 上游加入已有的 SSR 集合，并在 DNS 启动后刷新私有快照；预检阶段不操作实时集合。
- 自定义代理端口从 LuCI 实际写入的 global 配置读取。

`r5` 保留原有 `r4` 补丁，并在最后单独递增软件包 release，完整旧修复状态仍可逆向校验后升级。
这两项跟进参考上游 dev 的 [DNS 转发修复](https://github.com/fw876/helloworld/commit/b791299f2859c0bbd9ebea48af17dea8a30fdae9)
和 [custom_ports 修复](https://github.com/fw876/helloworld/commit/356dd51f880da55544e7601a0a3773acaf6fd76f)，
不切换到 dev 的新协议或核心组合。

## r6：首次初始化

插件自带的初始化脚本在空配置时调用 `reset`。此前本地运行时修复要求停止/清理规则成功后才能
重置；首次启动缺少 `/var/etc` 时，清理 include 文件失败，因而阻断默认配置复制。
这是此前本地修复引入的回归；空配置首次启动路径未被当时的运行回归覆盖。

`r6` 添加受现有生命周期锁保护的 `initialize` 入口，并由真实 uci-defaults
调用。配置缺失或为空时，检查默认模板、在同目录暂存、设置 `0644`
权限，以绝对路径交给 UCI 校验暂存文件，避开运行时配置覆盖和未提交变更，再原子发布。
入口仍在原 init 脚本内，不新增开机服务；不停止服务、清理规则、重启 DNS 或执行代理核心。
失败输出诊断并返回非零，让原 uci-defaults 留待重试。

任何已有非空配置都跳过默认值安装，包括缺少 global 段的异常配置；不会为
修复页面而自动重置用户数据。原有上游兼容迁移仍保留。显式 `reset` 的停止
失败保护不变。

原有十二份补丁和运行辅助脚本保持不变，完整 `r4`/`r5` 状态仍可校验升级。
初始化脚本和只读默认模板现已纳入源码、软件包及 rootfs 成品校验；可变的
`/etc/config/shadowsocksr` 不纳入安装文件哈希。

2026-10-22 核对的上游 [master](https://github.com/fw876/helloworld/blob/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/etc/uci-defaults/luci-ssr-plus#L66)
及 [dev](https://github.com/fw876/helloworld/blob/45893d778767f3bdb2fcb6e873cf8f9a667d94d4/luci-app-ssr-plus/root/etc/uci-defaults/luci-ssr-plus#L127)
仍采用空配置调用 reset 的路径，没有可直接回移的对应修复。本次保留 master 来源。

## r7：初始化顺序

`r6` 在旧配置迁移之前安装了默认配置，迁移因而误将新配置的空核心偏好写成
`ss-rust`。直接订阅普通 SS 时，这会使仅安装 libev 的系统选择不可用的 Rust；
同时安装 Rust 和 Xray 时，带 WebSocket 参数的 SS 链接也会走普通 SS 分支，丢失传输参数。

`r7` 仅将受检查的 `initialize` 调用移到原 reset 位置：已有非空配置完成原有迁移后、
原有 sed 转换之前。新配置跳过旧配置迁移，保留模板中未设置的 `ss_type` 和
`xray_hy2_type`；订阅器据实际安装核心及链接参数选择核心。已有配置的显式偏好、
自定义节点、域名/IP 规则和列表文件保留；旧字段仍执行原有迁移和类型转换。

追加初始化顺序补丁和 release 补丁，原有十四份补丁、运行辅助脚本、源码表及固定
fixtures 不变。完整 `r4`/`r5`/`r6` 源码与清单均覆盖升级和重复准备；其中原始
`r4`/`r5` 清单为九个安装目标，`r6`/`r7` 为十一个，模板权限保持 `0644`。

更新器要求目标 curl 至少为 8.4，以限制未知长度下载；旧 curl 会明确拒绝更新规则。
上游受保护源文件发生变化时，需要重新审查并更新补丁与基线，不能绕过源码校验继续编译。

## r8：保留升级与 SS 订阅解析

旧配置的迁移不再为缺失的 `ss_type` 写入 `ss-rust`，订阅器继续按已安装核心和
链接参数自动选择。已有显式值，包括空值、`auto`、Rust、libev、Xray 和自定义值，
都不会被这项修复改写。无法判断既有 Rust 值是用户选择还是 r6 自动写入，因此也不会
自动清除该值；明确固定普通 SS 核心的用户仍应按节点传输需求选择合适核心。

回移上游 [16617bee](https://github.com/fw876/helloworld/commit/16617bee81157f68965994125b88ee74a822faa5)
的 SS 凭据解析逻辑，先分离、解码凭据，再解析端点；在当前 master 上适配辅助函数，
不整体切换到 dev 的新内核和协议组合。覆盖 SIP002、整串 Base64、明文及百分号编码
凭据，保留密码内的字面加号等字符，畸形链接仍不能发布无效节点。

传输字段接收已经解码一次的查询参数，避免对 `%2B`、`%252F` 等继续解码。
回归同时执行真实 Lua 5.1 订阅器与固定版本、带包配套补丁的 lua-neturl，防止只靠
Python URL 替身掩盖解析差异。全新缺失/空配置及保留配置均通过实际 defaults hook
产生最终配置后再驱动订阅器；显式配置、手工节点、当前选择和域名/IP 规则继续受保护。

新增两份行为补丁和独立 release 补丁，原有十六份补丁、运行辅助脚本及十一个
上游源文件保持不变。完整 `r7` 的十六补丁、十一个目标原始清单与 `r4`/`r5`/`r6`
一起覆盖升级和幂等准备。r8 清单保护十一个安装目标；可变用户配置不加入哈希。

## r9：订阅到最终核心配置

在完整 r8 的十九份补丁之后，追加传输参数适配和独立 release 补丁。
旧补丁、运行辅助脚本、初始化模板和十一个已审查上游输入保持原始字节，
完整 r4/r5/r6/r7/r8 源码及其原始清单都经过逆向校验、升级和重复执行验证。
`gen_config.lua` 以原始上游字节追加为第十二个源码/安装目标保护项，避免未来仅生成器
变化时绕过订阅字段契约检查；历史清单继续按原始九/十一个目标验证，不伪造旧版本元数据。

- Trojan 查询键不再因大小写处理丢失 gRPC `serviceName` 和 TCP `headerType`。
- SS/VLESS 的 TCP HTTP 伪装参数使用生成器实际读取的 Host、路径字段。
- SS/Trojan 的 `fm` 写入生成器使用的 `finalmask`，保留合法 JSON 内容。
- 原生 SS 的普通 Base64 凭据保留字面 `+`，继续支持百分号编码和 Base64URL；
  该兼容修复不改变节点的显式核心偏好。
- TLS 下的 WS/HTTPUpgrade 独立 Host 与 SNI 分别保存，路径继续只解码一次。

新回归将真实订阅器产生的节点字段交给固定上游的完整 `gen_config.lua`，
直接检查最终核心 JSON 中的服务名、HTTP 伪装、finalmask、凭据和 TLS Host。
仅 UCI、下载、核心探测和外部系统调用边界被隔离；没有用另一个生成器替代生产逻辑。
首次初始化和保留配置升级继续执行完整 defaults hook，已有非空配置不安装默认模板，
显式偏好、手工节点、现用节点及域名/IP 规则保持受保护。

本次不修改设备配置，也不在升级时自动重写已有节点；订阅字段修复在后续订阅解析时生效。
包/rootfs 门禁要求 `190-r9` 清单及对应 `190-9`/`190-r9` 包版本，旧 r8 成品即使携带
新修复字节也会因版本不一致被拒绝。

## 本地验证

在独立 Python 测试环境安装 `tests/requirements.txt` 后执行：

```sh
bash tests/run_all.sh
sudo unshare -n bash tests/test_ssrplus_linux.sh
```

第二条命令要求 Linux、root、独立网络命名空间及 nft/dnsmasq/flock/ip 等依赖；
脚本会拒绝在宿主网络命名空间运行。Windows 测试中的环境跳过不能视为 Linux 已验证。
合成 IPK/APK 校验测试也不等于已经编译出固件。

首次初始化回归执行真实补丁后的 init/uci-defaults 和订阅 Lua 5.1；UCI、下载、
已安装核心及服务调用为隔离的操作系统边界。UCI 边界只模拟该 hook 所需的读写、
新增、删除和提交，将实际配置文件交给真实 sed，再以最终配置驱动真实订阅器。
这些测试不替代目标 UCI、包管理器、刷机或实机启动验收。

可用 `python tests/prepare_ssrplus_candidate.py --output <新的目录>` 从固定公开
fixtures 生成可检查的文件树；该工具不会访问路由器，也不会启动固件编译。
手动替换程序不改变设备包管理器记录的版本，实机部署与回滚应另行验证。
