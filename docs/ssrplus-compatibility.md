# SSR Plus 固件集成与验证

SSR 修复由项目构建流程自动应用，不依赖手动修改路由器或临时 build 目录。
当前审查基线是 `fw876/helloworld` 的
`2abdc9aa9e19607774dc9789709212b70b8607c6`，本地修复版本为 `190-r4`
（opkg 包版本为 `190-4`）。

## 以后编译如何带入修复

1. `custom_feed.sh` 导入 SSR 源码并记录实际上游提交。
2. `update.sh` 在 `feeds install` 之前调用 `fix_ssrplus_compat`，校验九个
   受保护源文件的 Git blob，再按 `patches.list` 应用完整九份补丁并安装运行脚本。
   已完整应用的旧补丁可在隔离副本中还原后重新校验；未知或不完整修改会中止构建。
3. 包内生成 `/usr/share/shadowsocksr/ssrplus-build.json`，记录上游提交、
   修复版本、补丁 SHA-256 和九个安装程序的 SHA-256/权限。
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

更新器要求目标 curl 至少为 8.4，以限制未知长度下载；旧 curl 会明确拒绝更新规则。
上游受保护源文件发生变化时，需要重新审查并更新补丁与基线，不能绕过源码校验继续编译。

## 本地验证

在独立 Python 测试环境安装 `tests/requirements.txt` 后执行：

```sh
bash tests/run_all.sh
sudo unshare -n bash tests/test_ssrplus_linux.sh
```

第二条命令要求 Linux、root、独立网络命名空间及 nft/dnsmasq/flock/ip 等依赖；
脚本会拒绝在宿主网络命名空间运行。Windows 测试中的环境跳过不能视为 Linux 已验证。
合成 IPK/APK 校验测试也不等于已经编译出固件。

可用 `python tests/prepare_ssrplus_candidate.py --output <新的目录>` 从固定公开
fixtures 生成可检查的文件树；该工具不会访问路由器，也不会启动固件编译。
手动替换程序不改变设备包管理器记录的版本，实机部署与回滚应另行验证。
