# 固件与 feed 来源锁

18 个配置现在都使用完整的固件提交，并按底座固定 feed 提交。
生产记录位于 [`wrt_core/feeds.lock.json`](../wrt_core/feeds.lock.json)，适配器为
[`wrt_core/feeds_lock.py`](../wrt_core/feeds_lock.py)。`update.sh` 的五参数接口保持不变。

## 固件配套

| 固件来源 / 分支 | 固件提交 | feed 配套 |
| --- | --- | --- |
| VIKINGYFY / main，原五个 IPQ60xx pin | `3fd1e27a511851b41cf082b067b60099e8e026c4` | legacy-master |
| VIKINGYFY / main，其余三个配置 | `f9b0ce7650fdcc7f4793256a3ae43c1132e2bc49` | legacy-master |
| LiBwrt / 25.12-nss，四个配置 | `000a4e74b17edfdc296f9eaa674344fc0adaaf95` | openwrt-25.12 |
| ImmortalWrt / master，四个配置 | `6003f6b8c3278a27712f4fdaaa8d1e5faa2b1f54` | master |
| ZqinKing / w1701k | `796897b5417537c0b10ee9ec31166ac5901bc33b` | master |
| padavanonly / openwrt-24.10-6.6 | `ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8` | openwrt-24.10 |

上述旧五个 pin 和所有设备、内核分支、配置 fragments、插件选择均保留。
上游原先选择的维护分支保持配套：LiBwrt 使用 25.12 feeds 和 NSS feeds；
padavanonly 使用 24.10 feeds，其上游配置没有 video feed。
每个 feed 的 URL、完整提交和上游提交链接均记录在锁文件中，包括额外的 Bandix 两个 feed。

## 旧底座为什么需要独立的 packages 快照

VIKINGYFY 两个固件提交均没有 `include/rust-package.mk`、`include/rust-values.mk`。
旧 Rust 构建规则位于 packages feed 的 `lang/rust/`，由配方显式引用，并通过 `rust/host` 构建。
新 packages master 中的 bottom、Python Rust 包、dufs、pdns-recursor 已转向固件核心的 Rust 接口，
还使用新的 cargo-vendor 下载方式。因此，仅接受新的 squeezelite 文件仍会在 feed 索引阶段失败。

legacy-master 的 packages 锁为
[`ffbc2408fccfb5c579363365a8971862a9718fb0`](https://github.com/immortalwrt/packages/commit/ffbc2408fccfb5c579363365a8971862a9718fb0)，
即首次导入这些配方的
[`0264bc1374f8cdacf81c3d3803365d1c86b92980`](https://github.com/immortalwrt/packages/commit/0264bc1374f8cdacf81c3d3803365d1c86b92980)
合并提交之前的主线状态。审查该不可变源码中所有 Makefile / `.mk`，未发现核心 `rust-*` include 或
cargo-vendor 协议；24.10、25.12 锁定的 packages 也没有这些新接口引用。
该快照的 squeezelite 仍为已审查的 `2.0.0.1584-r1`。

当前 master / w1701k 固件包含
[核心 Rust 构建规则](https://github.com/immortalwrt/immortalwrt/commit/32f1c26eb631b16b4184ba54d267a3984c8072d0)
和 [cargo-vendor 下载方法](https://github.com/immortalwrt/immortalwrt/commit/6362669c096b615a6ec0fa9b2b713aa69560ff8b)，
因此配套 packages
[`decf94639ffd6ddd26591c190b547c6b7eea150b`](https://github.com/immortalwrt/packages/commit/decf94639ffd6ddd26591c190b547c6b7eea150b)。
维护分支 packages 分别固定为 25.12 的 `fa25995d74a720c1c98bf6265d3dd8b4eb620d1f`
和 24.10 的 `171d5f9203379f77693807d7283515a873f95df9`。

master video 固定为
[`6a3b5fd6e963f41caa73ef4f691e156d467e2894`](https://github.com/openwrt/video/commit/6a3b5fd6e963f41caa73ef4f691e156d467e2894)，
保留上游 Qt5 的 libatomic / libdrm 依赖及插件安装检查修复；Qt 源码版本和下载哈希没有变化。
25.12 video 固定为 `094bf58da6682f895255a35a84349a79dab4bf95`。
对应 Kconfig 配方仍须通过现有的精确来源检查和兼容修复。

## 构建行为与缓存

适配器按实际 Git `origin` 加 `HEAD` 选择配套；配置预览按配置文件的 URL 和完整固件提交选择。
它在任何写入前检查整个锁、全部 feed 条目和已有检出。未知固件、来源变化、缺少必要 feed、
重复名称或重复锁定来源都会失败；不查远端分支，也不回退到滚动版本。

复用目录先只读预检，再清理；首次克隆在运行底座脚本前切到已审核提交。准备阶段原子写入 OpenWrt 原生 `URL^完整提交`，
Git 在临时目录直接获取精确 SHA，完整检出并核对后才发布到 feeds。原生工具只运行 `update -i` 建索引，
避免固定提交 fetch 失败后的原生重试误用默认 HEAD。
不混用 `;branch^commit`：旧 OpenWrt 的分支解析优先，会把这类字符串当成分支名称。
每次索引前后检查实际检出的 origin/HEAD；各轮单独保存日志，捕获原生扫描报错及缺失索引，
即使原生脚本返回零也不放行。安装前还检查 custom_feed 的绝对注册目标和实际 symlink。
TOPDIR 绑定当前 BUILD_DIR，避免继承另一个 SDK 的工作目录。
兼容补丁可以修改构建副本中的文件，Git 来源提交必须保持锁定。
已存在而提交不匹配的 feed 会明确失败，需清理旧 feed 检出后重新准备。

`config_preview` 显示所选配套、每个 feed 的提交和锁文件 SHA-256。
`pre_clone_action.sh` 将锁文件 SHA-256 加入 `repo_flag`，现有 `REPO_HASH` 缓存键因此同时包含
固件与 feed 锁身份；`PRECLONE_FEEDS_LOCK_SHA256` 防止预克隆后锁文件变化继续使用旧缓存身份。
修改锁文件的说明文字也会改变缓存键，这是有意保守地重新验证整个已审查锁。

## 更新和验证

先确定所需固件接口，再审查对应分支的实际配方，更新锁文件中的完整提交与 provenance，
同步修改相应 compilecfg pin；禁止仅替换分支名称以追逐最新版本。
旧五个显式 pin 的任何调整应另行说明设备原因。

本地检查：

```sh
python3 tests/test_feeds_lock.py
bash tests/test_repo_checkout.sh
./build.sh jdcloud_ipq60xx_immwrt config_preview
```

配置预览和项目 Bash 脚本要求 Bash 4.3 以上；macOS 系统 Bash 3.2 无法运行原有的 nameref / 小写转换语法。
新的 Python 适配器和本地 Git 行为测试可跨平台运行。
本地 Git 测试验证来源拒绝、原子写入、重复运行、真实检出校验和缓存失效；
这些测试不能代替 Linux 上的真实 feed 索引、defconfig、完整固件编译或设备实机验证。
