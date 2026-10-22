# 插件兼容修复与编译入口

本次修复沿用当前选择的插件来源，不切换 SSR dev 分支，不升级代理内核。
后续通过项目标准 `build.sh` / GitHub Actions 编译、并选中对应插件的固件，
会在编译源码准备阶段自动应用这些补丁。

当前 AX6600 的 `jdcloud_ipq60xx_immwrt.config` 已启用这三个插件。
`jdcloud_ipq60xx_libwrt.config` 启用 OpenClash/ADG，SSR 需由最终配置选中；
本次不改变各机型的插件选择。

## SSR Plus

`wrt_core/modules/custom_feed.sh` 从 `fw876/helloworld` 的 **master** 获取包。
`wrt_core/update.sh` 的 `stage_pre_install_source_fixes` 在 feeds install 前调用
`fix_ssrplus_compat`，按 `wrt_core/compat/ssrplus/patches.list` 应用十四份补丁。
原有十二份保持不变，随后追加首次初始化修复及单独的版本标记补丁。
完整旧 `190-r4`/`190-r5` 源码及其原始构建清单也会重新验证并升级。

- 回移 [b791299](https://github.com/fw876/helloworld/commit/b791299f2859c0bbd9ebea48af17dea8a30fdae9)：
  nft GFW 模式下将 DNS 上游 IPv4 地址加入已有 `inet ss_spec gfwlist`，
  DNS 准备阶段不操作内核，完成后更新 SSR 私有持久化快照。
  当前 master 没有 IPv6 GFW 规则，IPv6 地址安全跳过。
- 回移 [356dd51](https://github.com/fw876/helloworld/commit/356dd51f880da55544e7601a0a3773acaf6fd76f)：
  自定义代理端口从 global 配置读取。
- 首次配置生成与运行时 reset 分离，空配置不再依赖停服务及规则清理；已有非空配置跳过默认值安装，保留上游兼容迁移。
- 包版本为 `190-6`，内嵌修复标识为 `190-r6`。构建清单包含全部补丁和
  受保护程序哈希；现有包与 rootfs 门禁继续校验实际成品。

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

`tests/run_all.sh` 包含三组新增专项回归及现有完整回归。
`.github/workflows/test_ssrplus.yml` 在 Linux 上执行该入口，并在隔离网络
命名空间内用真实 nft/dnsmasq 验证生成配置与生命周期。
标准固件构建及发布工作流继续依赖测试门禁。

测试执行实际打补丁后的程序，下载、服务和外部网络边界在测试中替换。
源码补丁支持重复执行，补丁或 SSR 源码校验不匹配时在写入前拒绝。Windows 本地验证不能
替代 Linux 可执行权限及 nft/dnsmasq 检查；这些由 Linux CI 完成。
以上不代表已完成完整固件交叉编译或路由器实机验收。
