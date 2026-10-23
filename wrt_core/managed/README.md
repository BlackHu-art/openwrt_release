# 构建受管插件源码

本目录保存实际参与固件源码准备的本地输入。它与
[`maintenance/plugins/`](../../maintenance/plugins/README.md) 的 reference-only 审查快照用途不同。
构建不会以维护区的快照替代这里的输入，也不会为缺失或损坏的受管文件自动回退远端。

当前 [`sources.lock.json`](sources.lock.json) 有 **30 个顶层源码单元**，不是 30 个最终二进制包。
Argon 子树内还包含空 `luci-app-argon-config` 兼容 recipe，随主题一起保存和安装，
不另拷贝、不另计为顶层来源。包内的子 recipe 和下载源码仍以实际 Makefile 为准。

## 来源与安装路径

| 顶层单元 | 原始版本/标识 | 锁定上游提交 | 构建目标 |
| --- | --- | --- | --- |
| luci-app-homeproxy | 官方固定源码 | fadaa676104f | custom_feed/luci-app-homeproxy |
| luci-app-ssr-plus | 198-2 | fw876 v198.2 / 45893d778767 | custom_feed/luci-app-ssr-plus |
| xray-core | fw876 26.10.21-r2，完整十份补丁 | fw876 v198.2 / 45893d778767 | custom_feed/xray-core |
| chinadns-ng、dns2socks、dns2tcp、lua-neturl、microsocks、mosdns | 原始 fw876 配方 | fw876 v198.2 / 45893d778767 | custom_feed/同名目录 |
| shadowsocks-rust、shadowsocksr-libev、simple-obfs、tcping、v2ray-plugin、ipt2socks | 原始 fw876 配方 | fw876 v198.2 / 45893d778767 | custom_feed/同名目录 |
| upx | 5.2.1，Xray host 编译依赖 | fw876 v198.2 / 45893d778767 | custom_feed/upx |
| sing-box | 1.14.3 | small-package fca4816303d6 | custom_feed/sing-box |
| oaf | 内核包源码 | small-package fca4816303d6 | custom_feed/oaf |
| open-app-filter | appfilter 7.0.1 | small-package fca4816303d6 | custom_feed/open-app-filter |
| luci-app-oaf | 7.0 | small-package fca4816303d6 | custom_feed/luci-app-oaf |
| luci-app-istorex | 0.6.6 | small-package fca4816303d6 | custom_feed/luci-app-istorex |
| quickstart | 0.13.0-r1 | small-package fca4816303d6 | custom_feed/quickstart |
| luci-app-quickstart | 0.12.10-r1 | small-package fca4816303d6 | custom_feed/luci-app-quickstart |
| luci-app-store | 0.2.1-r1 | small-package fca4816303d6 | custom_feed/luci-app-store |
| taskd | 1.0.3-r2 | small-package fca4816303d6 | custom_feed/taskd |
| luci-lib-taskd | 1.0.26 | small-package fca4816303d6 | custom_feed/luci-lib-taskd |
| luci-lib-xterm | 4.18.0 | small-package fca4816303d6 | custom_feed/luci-lib-xterm |
| luci-theme-argon | 3.1.0 | 81e781c09ecf | feeds/luci/themes/luci-theme-argon |
| luci-theme-aurora | 1.4.0 | 84c27b66952e | feeds/luci/themes/luci-theme-aurora |
| luci-app-aurora-config | 1.2.5 | a5299ce01448 | feeds/luci/applications/luci-app-aurora-config |

完整仓库 URL、引用、提交和源路径均以锁文件为准。27 个 custom_feed 单元先写入
`<BUILD_DIR>/custom_feed/`，再通过现有 src-link feed 进入 `feeds/custom_feed` 并安装；
两个主题沿用 `feeds/luci/themes/`，Aurora 配置包沿用 `feeds/luci/applications/` 路径。

## 文件存储与 loader

- `packages/<id>/` 保存锁定来源的原始 blobs，兼容补丁作用于独立构建副本。
- `sources.lock.json` 记录文件集合、SHA-256、Git blob 和 mode，以及来源和许可声明位置。
- `compat/istore_backend.lua` 是固定版本的兼容文件；`licenses/` 保留额外取得的来源许可证。
- Windows 中的 Git mode `120000` 文件以链接目标文本保存。它们不是已经还原的 Linux 符号链接。
  普通检出也不等于已恢复 POSIX 执行位。

[`managed_plugins.py`](../managed_plugins.py) 的 `check` 验证各单元文件集合、内容哈希和安全路径；
`stage` 校验后在构建目录临时副本中按 mode 恢复 `0644` / `0755` 与包内相对链接，
再替换目标目录。`verify-staged` 检查构建副本完整文件集合、哈希、文件类型和 POSIX mode，
缺失或额外补丁均拒绝。`assert-external` 在网络请求之前拒绝外部同步任何受管同名包。
`support` 校验锁定兼容文件后写入指定构建路径。
[`managed_plugins.sh`](../modules/managed_plugins.sh) 提供 shell 接入，
[`custom_feed.sh`](../modules/custom_feed.sh) 在重建自定义 feed 前执行完整输入检查。
loader 面向构建源码树，不用于改写运行中的 `/etc` 或用户 overlay。

可在仓库根执行只读输入检查：

```bash
python3 wrt_core/managed_plugins.py check
```

这条命令只检查本地输入，不执行 OpenWrt 依赖求解、下载或交叉编译。

## 构建副本的兼容处理

HomeProxy 固定 `fadaa676` 官方源码，继续应用原有 sing-box 1.14、ACL 域名和特性缓存补丁，
补齐 `ucode-mod-math`，保留补丁预检与未知源码拒绝逻辑。翻译和规则数据随提交一起固定。

SSR 和实际选择的共享核心统一使用 `fw876/helloworld@v198.2`，固定提交
`45893d778767f3bdb2fcb6e873cf8f9a667d94d4`。导入时按维护快照 manifest
逐文件验证大小、SHA-256、Git blob 并保留 mode；原始受管包不应用生产兼容修改。
不导入未选择的 fw876 可选核心。MosDNS 核心使用 fw876，未选择的 LuCI MosDNS
仍沿用原来源和配置处理；tcping 的准备入口只校验本地 fw876 源，不再在线覆盖。

Xray 保存完整 `26.10.21-r2` recipe、EIP93 说明及十份补丁。
[`fix_xray_core_compat`](../modules/xray_core_compat.sh) 对整个包做精确校验，
随后检查官方 Passwall2 生成器最低版本和 Go >=1.27.3；每次准备都会重新检查。
原官方 Xray 升级补丁不再用于生产。fw876 Xray 需要 `golang/host` 和 `upx/host`，
UPX 只作为编译依赖引入；shadowsocks-rust 依赖标准 `rust/host`。
Xray recipe 内启用 Naive outbound 时另按原配方下载固定哈希的 Cronet Clang，
不需要导入单独 NaiveProxy 的 `gn/host` 包。
Go 使用先校验再替换的 `27.x` 获取流程；sing-box 保持 `1.14.3`。
固定 recipe 不表示把 Xray、sing-box 等核心源码归档全部内嵌，下载仍按 recipe 的来源和哈希执行。
完整来源与 fw876 测试产物身份见
[`xray-26.10.21.json`](../compat/proxy-cores/xray-26.10.21.json)。官方 Xray 二进制
仅做通用配置交叉检查，fw876 私有协议需要 Linux 上的固定 fw876 测试核心。

OAF 保持当前 7 / `fwx` schema，不包含旧 OAF 6 规则自动迁移。
[`oaf_compat.py`](../oaf_compat.py) 只在构建副本准备新安装默认值：应用过滤、MAC 过滤、
记录三项 enable 均为 0，`disable_hnat=0`；原有显式 `fwx` 值保留。
`99_disable_oaf` 在三项均为 0 时执行默认停用，在线包安装的自动启动用一次性安装上下文抑制，
在线包升级保留管理员已有 enabled 选择，后续手动 enable/start 仍正常；
普通首启（含保留配置刷机后首启）仍在三项均0时停用服务，不保证保留该情形的开机启用状态；两份同名 ACL 合并为后端包单一文件所有者。
运行功能仍以用户到启动项手动 enable/start 为前提，未承诺旧规则语义迁移或实机功能验收。

iStoreX 七个组件一起固定。`luci-lib-taskd 1.0.26` 满足 iStoreX 的 >=1.0.15 和商店的 >=1.0.19；
taskd 1.0.3-r2 满足库要求的 taskd >=1.0.3。标准依赖由目标核心/feeds 提供，
其中 script-utils 是两套 AX6600 上游核心 util-linux recipe 的子包。
原 quickstart 存储依赖处理继续保留，二进制 quickstart 和 istore-ui 归档仍从 recipe 指定地址下载。

`istore_backend.lua` 固定
[gist revision 51ae1464e068fadc348c0b577f8ffd338bbd7ee5](https://gist.github.com/puteulanus/1c180fae6bccd25e57eb6d30b7aa28aa/51ae1464e068fadc348c0b577f8ffd338bbd7ee5)，
SHA-256 为 `5eb5e0524a42b62895ee8163d50bf1d78999db7c1321646fdcca3c99c26249e2`。
锁文件保留其独立来源和许可说明：捕获版本没有发布额外明确许可证，
small-package 根 Apache-2.0 不能作为这个 gist 的许可证明。

Argon 3.1.0 由主题唯一提供配置、RPC、界面与翻译，内部空兼容包保留旧包名和升级流程。
构建删除旧独立配置源码；集成标记或兼容包缺失即失败。Aurora 主题与配置仍是两个源码单元。

QuickFile 另走外部获取流程，**不属于本目录**。已核对 2.0.8 官方 Rust 源码包哈希；
旧架构 sed 是不匹配当前 recipe 的 no-op，移除后由结构 guard 要求安装目标 Rust 产物。
该检查不锁定整个外部提交，也不代表交叉编译已经成功，详见
[QuickFile fixture](../../tests/fixtures/quickfile/README.md)。

## 来源刷新与验证边界

1. 在独立审查目录解析新提交，比较完整目标子树、版本、依赖、下载哈希、许可声明和删除文件。
2. 按 Git blob 保存完整新来源，保留链接目标文本与 mode；不要把已应用补丁的构建副本覆盖回原始快照。
3. 一起更新本目录源码和 `sources.lock.json`，包括文件集合、摘要、来源、模式及补充文件。
4. 审查和更新关联模块、补丁/compat、fixture 与回归；Xray、HomeProxy、OAF 的已审查输入发生变化时，
   不能仅更新锁文件来绕过原 guard。维护区参考快照的更新不会自动进入本目录。
5. 执行本地输入检查及相关回归，再按需要完成 Linux 权限/符号链接检查、目标依赖求解、
   完整交叉编译、最终包/rootfs 检查与路由器功能验收。

本说明记录接入方式和测试范围，不预先宣称本轮全套回归通过。来源哈希检查和主机回归
不能代替完整固件交叉编译或路由器验收。第三方源码保留各自版权与许可声明，不能统一解释为主项目许可证。

Aurora 构建副本还经过 `theme_compat.py` 完整脚本 guard。旧版或缺失 schema 的
初始化仅补缺省和无冲突别名，保留已有设置；未来或未知 schema 不降级。
Argon 仓库级初始化同样只填缺项。原始受管源码和哈希保持不变。
