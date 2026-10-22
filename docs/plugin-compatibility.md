# 插件兼容修复与编译入口

兼容修复沿用当前选择的插件来源，不切换 SSR dev 分支。为满足当前 Passwall / Passwall2
生成器的最低版本要求，共享 Xray 配方从 `26.3.27` 调整为 `26.7.11`；sing-box 保持 `1.14.3`。
后续通过项目标准 `build.sh` / GitHub Actions 编译、并选中对应插件的固件，
会在编译源码准备阶段自动应用这些补丁。

当前 AX6600 的 `jdcloud_ipq60xx_immwrt.config` 已启用 SSR Plus、OpenClash 和 AdGuard Home。
`jdcloud_ipq60xx_libwrt.config` 启用 OpenClash/ADG，SSR 需由最终配置选中；
本次不改变各机型的插件选择。

## Passwall、Passwall2 与共享 Xray

两套插件继续从 `Openwrt-Passwall` 各自仓库的 `main` 获取。维护区保存的原始源码不改写；
`stage_pre_install_source_fixes` 在 feeds install 前通过 `fix_passwall_compat` 应用补丁。

- sing-box `< 1.15.0` 遇到非空 `tls_pinSHA256` 时明确报错，不再将证书指纹丢弃并自动设置
  `tls.insecure=true`。即使原配置同时指定允许不安全连接，也不会忽略已指定的指纹。
- 三个生成器调用入口检查 Lua 的退出状态，将诊断写入插件日志，删除失败时留下的 JSON，
  并停止该次核心检查和启动。已有空指纹配置及显式 `tls_allowInsecure` 语义保持不变；
  支持指纹字段的 sing-box 分支继续使用原有格式转换。
- 旧核心上使用证书指纹的节点现在会被拒绝，需要使用支持该字段的核心，或由用户明确重新配置
  证书验证方式。补丁不自动删除指纹、改成公有 CA 校验或将证书指纹冒充公钥指纹。

两套插件生成的 Xray JSON 声明 `version.min=26.7.11`。当前 small-package 的 `26.3.27`
会拒绝这类配置，因此通过 [Xray 配方补丁](../wrt_core/patches/xray-core-26.7.11.patch)
仅调整版本与源码 SHA-256，继续使用原有 XTLS 下载来源、依赖、构建参数和安装规则。
`26.7.11` 的[官方发布](https://github.com/XTLS/Xray-core/releases/tag/v26.7.11)标记为预发布；
本次选择的是满足最低要求的版本，不将其称为稳定版。来源、提交、源码哈希及审查时的 Go
配方记录在 [版本记录](../wrt_core/compat/proxy-cores/xray-26.7.11.json)。

[fix_xray_core_compat](../wrt_core/modules/xray_core_compat.sh) 在现有 `update_golang` 之后执行，
检查本轮实际获取的 Go 配方至少为 `1.26`，并读取两套插件实际生成器的最低 Xray 版本。
未审查的 Xray Makefile、插件最低版本提高、版本声明异常或 Go 不满足要求都会停止构建，
不继续使用不兼容配方；重复执行也会重新检查版本条件。

Passwall、Passwall2 和 SSR Plus 共用 `/usr/bin/xray`，因此此次配方调整也影响选用 Xray 的
SSR Plus 节点。新增回归执行三者真实生成器，覆盖 53 份最终配置，包括 VLESS / Trojan / SS
的 raw、WebSocket、HTTPUpgrade、gRPC 与 TLS，以及 VMess WebSocket/TLS、VLESS Reality、
透明代理、DNS、分流和辅助代理入口。
SSR Plus 用例先执行实际订阅器再生成配置。`xray-plugin` 是独立软件包及二进制，不随此配方改版。

## SSR Plus

`wrt_core/modules/custom_feed.sh` 从 `fw876/helloworld` 的 **master** 获取包。
`wrt_core/update.sh` 的 `stage_pre_install_source_fixes` 在 feeds install 前调用
`fix_ssrplus_compat`，按 `wrt_core/compat/ssrplus/patches.list` 应用二十五份补丁。
原有二十三份保持不变，随后追加订阅节点引用修复及单独的版本标记补丁。
完整旧 `190-r4`/`190-r5`/`190-r6`/`190-r7`/`190-r8`/`190-r9`/`190-r10` 源码及其原始构建清单也会重新验证并升级。

- 回移 [b791299](https://github.com/fw876/helloworld/commit/b791299f2859c0bbd9ebea48af17dea8a30fdae9)：
  nft GFW 模式下将 DNS 上游 IPv4 地址加入已有 `inet ss_spec gfwlist`，
  DNS 准备阶段不操作内核，完成后更新 SSR 私有持久化快照。
  当前 master 没有 IPv6 GFW 规则，IPv6 地址安全跳过。
- 回移 [356dd51](https://github.com/fw876/helloworld/commit/356dd51f880da55544e7601a0a3773acaf6fd76f)：
  自定义代理端口从 global 配置读取。
- 首次配置生成与运行时 reset 分离，空配置不再依赖停服务及规则清理；已有非空配置跳过默认值安装，保留上游兼容迁移。
- 初始化在旧配置迁移之后、原有 sed 转换之前执行；新配置保留自动核心选择，SS WebSocket 链接保留 Xray 传输参数。
- 保留配置升级时，缺失的 SS 订阅核心偏好继续表示自动；已有显式偏好不改写，包括旧版本保存的 Rust。
- 回移 [16617be](https://github.com/fw876/helloworld/commit/16617bee81157f68965994125b88ee74a822faa5) 的 SS 凭据解析修复，适配当前 master 的辅助函数；支持整串 Base64、SIP002 和明文凭据。
- 已解码的 URL 查询参数直接写入传输字段，避免路径中的加号、百分号等被再次转换。
- 订阅到实际核心 JSON 的回归覆盖 Trojan gRPC/HTTP 伪装、SS/VLESS HTTP 伪装、
  SS/Trojan finalmask、原生 SS Base64 加号和 TLS 下独立的 WS/HTTPUpgrade Host。
- 原生 SS 的 Base64 凭据解码后保留密码的精确字节，字面 `%2B`、`%3A`、`%25`
  不再被猜测为内层 URI 编码；外层 URI 转义仍解码。仅后续订阅实际重新解析链接时生效，
  已有持久化值和 MD5 缓存不迁移。旧密码信息若已损失，需要重新订阅并确保实际重新解析，
  不自动迁移或重写配置。
- 订阅实际重解析原生 Base64 SS 时，同组唯一匹配历史错误密码指纹的旧节点保持原 SID，
  原位更新正确密码和指纹，主代理、UDP、SOCKS5 与 Netflix 引用保持不变。
  手工节点、跨组节点和普通凭据变更不做模糊匹配；歧义在写入前拒绝整个订阅事务，
  保留配置和 MD5 缓存。初始化和默认模板不改动，也不在升级时自动迁移配置。
- 包版本为 `190-11`，内嵌修复标识为 `190-r11`。构建清单包含全部补丁和
  十二个安装目标哈希，包括实际核心生成器；现有包与 rootfs 门禁继续校验实际成品。
  r4/r5 原始清单保持九个目标，r6/r7/r8 保持十一个，r9/r10 分别保持二十一/二十三份补丁和十二个目标。

细节见 [SSR 兼容性说明](ssrplus-compatibility.md)。

## OpenClash

从当前 `kenzok8/small-package` 获取包，在 feeds install 前调用
`fix_openclash_compat`。保留现有 WAN 子网修复，替换旧校验匹配补丁，
对照 [91d7370](https://github.com/vernesong/OpenClash/commit/91d73707a6bcd0f8ec96a57095d72b1b4357cbe7)
按完整 basename 精确匹配 SHA-256 清单，处理路径前缀、星号、CRLF 和大写哈希。
文件内容不匹配时拒绝；没有有效校验值时保留上游的警告并跳过校验行为。

标准构建每次刷新 custom feed 后应用补丁。手工保留的旧匹配补丁状态不自动
迁移；与已审查原始或当前补丁状态不匹配的源码会停止构建，需重新审查。

## AdGuard Home

feeds install 后，`wrt_core/modules/service_fixes.sh` 的 `update_adguardhome`
获取 `ZqinKing/luci-app-adguardhome`，随即调用 `fix_adguardhome_compat`。
更新器与默认下载链接一起修复：

- 默认先下载 GitHub 指定稳定标签，再尝试官方稳定镜像。
- 旧固件保留的 `links.txt` 自定义配置仍可使用；稳定更新跳过其中已知的
  beta、edge 和 GitHub 预发布标签地址。
- 稳定 API 标签必须符合 `vX.Y.Z`，每个下载候选执行 `--version` 并与目标
  精确比较。坏归档、错误版本或无法运行的候选继续尝试下一镜像。
- 所有候选无效时，在停止或替换现有核心之前失败；成功日志显示已验证的版本。
- 自动更新不降级；同数字版本的正式版高于预发布版，手工 force 保留原有语义。

默认链接变化只影响新配置；运行时检查也覆盖被固件升级保留的旧链接配置。

## 验证与适用范围

`tests/run_all.sh` 包含插件专项回归及现有完整回归。Passwall TLS 与启动入口回归覆盖旧核心
拒绝指纹、受支持核心保留指纹、无指纹配置、隐式 TLS 协议、生成失败后停止启动，以及补丁重复应用。
Xray 配方回归覆盖源码与补丁哈希、版本及 Go 门槛、重复执行和失败时不写入原配方；
源码准备阶段回归另外验证实际接入顺序。
`.github/workflows/test_ssrplus.yml` 在 Linux 上执行该入口，并在隔离网络
命名空间内用真实 nft/dnsmasq 验证生成配置与生命周期。
标准固件构建及发布工作流继续依赖测试门禁。

共享 Xray 回归通过 `XRAY_TEST_BINARY` 调用官方核心的 `run -test` 检查最终配置。
CI 使用 [固定版本下载器](../tests/fetch_xray_test_core.py) 校验归档 SHA-256 后设置该变量；
本地未设置时会明确跳过实际核心校验，但仍运行生成器检查。Windows 与 Linux amd64 的
官方测试归档分别锁定哈希。该校验不启动代理监听，也不能证明真实 TLS 握手或数据转发成功。

测试执行实际打补丁后的程序，下载、服务和外部网络边界在测试中替换。
首次初始化测试通过限定的 UCI 边界提交实际配置，再由真实 sed 和 Lua 5.1
订阅器处理，覆盖最终核心选择和 WebSocket 参数；订阅传输回归继续执行真实
上游 `gen_config.lua` 检查最终 JSON。这不替代目标 UCI 或核心握手的验收。
源码补丁支持重复执行，补丁或 SSR 源码校验不匹配时在写入前拒绝。Windows 的 SSR 首次初始化
回归也需要真实 `flock`；只有 Git Bash 时会因缺少该命令失败，可通过现有 `SSRP_TEST_FLOCK_DIR`
指定可用工具目录。Windows 本地验证不能替代 Linux 可执行权限及 nft/dnsmasq 检查；
这些仍需在 Linux CI 验证。
以上不代表已完成完整固件交叉编译或路由器实机验收。
