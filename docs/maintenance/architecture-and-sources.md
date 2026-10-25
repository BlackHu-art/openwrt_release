# 架构与来源

完整目录表见 [项目布局](../project-layout.md)，版本身份见 [生产来源锁](../../wrt_core/managed/sources.lock.json)。

## 配置与调用顺序

[`build.sh`](../../build.sh) 只把 `compilecfg/<设备>.ini` 与 `deconfig/<设备>.config` 同名成对的设备列为可选。
`.ini` 决定固件上游仓库、分支、可选提交、构建目录和默认 fragments。
配置依次组合为：设备 `.config` → `compile_base.config` → 生效 fragments。
`ADD_CONFIG_FRAGMENTS` 追加并去重，`REMOVE_CONFIG_FRAGMENTS` 从最终片段列表移除；
移除片段不会撤销设备配置或公共配置中已有的选择。先用 `config_preview` 查看有效结果。

```text
build.sh：设备/模式与 fragments → 判断 Docker 选择
  └─ wrt_core/update.sh
       1. stage_repo_checkout：准备并清理上游构建树
       2. stage_upstream_feeds_update：生成 feeds/*
       3. stage_feed_source_cleanup：移除同名冲突来源
       4. stage_custom_feed_prepare：装载受管源码及其他 custom_feed
       5. stage_pre_install_source_fixes：构建副本适配、补丁、工具链门槛
       6. stage_feeds_install：刷新索引并生成 package/feeds/*
       7. stage_post_install_package_fixes：安装后路径修正与一致性检查
  └─ 组合 .config → 保存 .config.requested → make defconfig
       → SSR 最终配置检查 → check_selected_plugins.py
       → debug 停止，或下载/prepare/编译/成品检查 → firmware/
```

阶段实现见 [`update.sh`](../../wrt_core/update.sh)。安装前不能依赖 `package/feeds/*`，
安装后需考虑 feeds 链接和最终来源路径。下载、日志、退出码和成品门禁由
[`build_steps.sh`](../../wrt_core/modules/build_steps.sh) 等模块实现，不能只看主入口末尾是否输出成功。

## 三种源码位置

| 位置 | 身份 | 修改方式 |
| --- | --- | --- |
| `wrt_core/managed/` | 30 个生产原始源码单元；锁记录文件集合、提交、blob、mode、SHA-256 | 升级来源时独立审查并完整更新；兼容补丁不直接写入原始字节 |
| `maintenance/plugins/` | 原始参考快照及 SSR 历史派生输入，不作为包安装来源；SmartDNS 兼容脚本读取其原始配方进行基线校验 | 用于比较上游、追溯来源和许可证；更新 SmartDNS 快照须联动审核固定提交与兼容基线 |
| `<BUILD_DIR>/custom_feed/`、`feeds/`、`package/` | 本次构建实际使用的副本 | loader 恢复执行权限/符号链接，模块再应用修正；下次准备可能清理 |

[`managed_plugins.py`](../../wrt_core/managed_plugins.py) 校验输入并装载到允许的构建目录；
损坏或缺失不会自动回退远端，外部同名包会被拒绝。Windows 中保存的链接目标文本不等于 Linux 真正链接。
[`tests/fixtures/`](../../tests/fixtures/) 是固定回归输入，与参考快照和生产输入分别维护。
受管的是包装配方及随包文件，并不代表核心源码归档、二进制和所有 feeds 已内嵌或全部固定。

SmartDNS 包装仓库仍从 `ZqinKing/openwrt-smartdns` 获取，但 `update_smartdns` 在克隆后 fetch、checkout 并核对固定提交 `cdf0de1d3e64984ea2c56ec873f233495ddb1de0`，随后才执行 WebUI 下载兼容、优化补丁和 CC 修正。当前核心配方仍为 `1.2025.47-r1`，未升级到默认分支的新配方 48.4；LuCI 来源仍为 `pymumu/luci-app-smartdns`，插件选择与配置保持不变。此 pin 与原始快照、归档身份和补丁须一起审核更新，不能跳过源码漂移检查。失败背景及核验边界见 [SmartDNS 来源固定说明](../source-download-compat.md#smartdns-包装来源固定)。

## 当前 SSR／核心边界

SSR 与选定配套核心固定到 `fw876/helloworld@v198.2` 的
`45893d778767f3bdb2fcb6e873cf8f9a667d94d4`。原始 Xray 配方及 Linux 测试产物身份为
`26.10.21-r2`；生产构建副本的派生修订与 UPX 处理见 [fw876 集成说明](../fw876-core-migration.md)。
完整十份 Xray 补丁与 Go ≥1.27.3 的门槛仍需检查。SSR 旧 190 系列生命周期/DNS 代码仅用于历史回归。

Passwall1/Passwall2 已移除；其他插件选择以当前配置和 defconfig 后检查为准。
更新 fw876 时先比较具体完整提交，只移植已审查且当前需要的修复。
不能整批切换滚动 `dev`：本轮审查发现其 Hysteria2 相关路径存在未定义 `node` 的回归风险，
因此选择固定来源上的单项移植；该判断有时间范围，未来仍需重新审查。
来源提交、选择理由与实际执行证据见 [本轮上游修复记录](../fw876-upstream-backports.md)。

运行时 Xray 组件更新由 SSR 管理，SSR 主程序在线自升级禁用以保留项目适配。
组件在线更新、构建来源锁升级和固件发布是不同操作，各自需要对应证据。
