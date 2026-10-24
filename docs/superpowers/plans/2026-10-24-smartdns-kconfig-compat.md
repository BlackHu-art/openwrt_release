# SmartDNS 下载与 Kconfig 循环依赖修复

目标：修复京东云构建 40076155141 暴露的问题，保留插件来源、固定提交、选择和编译配置。

1. 独立核对 WebUI 固定提交的 Git tree、blob、归档成员及 GNU tar/gzip 哈希；对照错误默认分支确认根因。
2. 先复现旧下载配方丢失提交号，再仅在构建副本将 `VERSION` 改为 `SOURCE_VERSION`，根据现有 `smartdns-ui` 的 y/m 状态注册下载。保留原始归档哈希；拒绝未知配方漂移并传播失败。
3. 使用真实 Qt5、squeezelite 配方和 package-metadata 生成依赖，复现两个环；最小调整源码 Kconfig 条件，保留默认值、功能选项和条件库依赖，不改用户配置。
4. 补充 Windows 可执行的源码、Make 展开和错误传播回归；Linux 强制执行实际下载器、独立归档核对和真实 OpenWrt conf 解析。
5. 更新维护说明和测试入口，运行受影响本地测试与完整 Linux CI，审阅最终差异；仅将验证通过的提交推进 master 并推送，再触发 `jdcloud_ipq60xx_immwrt`。

边界：测试替身只隔离包编译目标和无关网络操作。回归通过不代表目标固件已编译成功或设备运行已验证；分别报告 CI 与固件任务状态。
