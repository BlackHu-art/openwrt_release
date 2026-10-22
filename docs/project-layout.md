# 项目文件布局

本项目按构建、插件维护、验证、文档四类职责组织。已有构建入口、设备配置、补丁和测试路径保持不变；新增源码集中在 `maintenance/plugins/`，不接入 feeds，不改变当前固件的软件包选择。

## 目录总览

```text
openwrt_release/
├── build.sh                         # 设备选择、配置组合、构建与固件收集
├── .github/workflows/               # 回归检查、单设备构建和发布、批量发布
├── wrt_core/                        # 实际参与固件构建的逻辑和配置
│   ├── compilecfg/                  # 设备源码地址、分支、提交、配置片段
│   ├── deconfig/                    # 设备配置、公共配置、fragments/
│   ├── modules/                     # 源码/feeds/插件处理与构建步骤
│   ├── patches/                     # 构建时应用的补丁及注入文件
│   ├── compat/                      # 本地兼容实现、源码基线表和包定义
│   ├── ci/                          # CI 专用辅助入口
│   ├── update.sh                    # 源码准备与插件修正编排
│   ├── build_container.sh           # 容器内构建入口
│   ├── check_selected_plugins.py    # defconfig 后的插件选择检查
│   └── ssrplus_verify.py            # SSR 包与 rootfs 的成品校验
├── maintenance/
│   └── plugins/                     # 用于审查和持续维护的原始上游快照
│       ├── README.md                # 来源、版本、目录与更新流程
│       ├── sources.lock.json        # 六份源码的提交、树和版本记录
│       ├── manifests/               # 各源码文件的 Git blob、模式和 SHA-256
│       ├── licenses/                # 从包目录之外补充保留的上游许可证
│       ├── smartdns/
│       │   ├── package/             # ZqinKing/openwrt-smartdns
│       │   └── luci-app-smartdns/   # pymumu/luci-app-smartdns
│       ├── passwall/luci-app-passwall/
│       ├── passwall2/luci-app-passwall2/
│       ├── openclash/luci-app-openclash/
│       ├── adguardhome/luci-app-adguardhome/
│       └── ssrplus/                 # v198.2 原始仓库、190-r11 比较副本及证据
├── tests/
│   ├── run_all.sh                   # 现有回归测试入口
│   ├── windows-tests.ps1            # Windows PowerShell 安装、检查与运行入口
│   ├── windows_test_env.py          # 仓库外依赖管理、校验与回归日志
│   ├── requirements.txt             # 固定版本的 Python 测试依赖
│   ├── fetch_xray_test_core.py      # 下载并校验固定版本的官方 Xray 测试核心
│   ├── test_*.sh / test_*.py        # 构建契约、插件及运行逻辑测试
│   └── fixtures/                    # 固定、已经审查的测试输入
├── docs/                            # 当前说明及历史设计/诊断记录
├── README.md                        # 使用入口与编译指南
└── firmware/                        # 构建生成，Git 忽略
```

`imm-nss/`、`immortalwrt/`、`libwrt/` 等目录是按设备生成的上游构建工作树；GitHub Actions 使用 `action_build/`。这些目录与维护快照用途不同，不应把需要保留的人工修改仅放在构建工作树中。

## 三种源码的职责

| 位置 | 用途 | 更新原则 |
| --- | --- | --- |
| `maintenance/plugins/` | 查看完整插件调用链、比较上游版本、准备后续修复 | 每次获取都记录实际提交和原始文件校验值；保持原始快照与本地补丁分离 |
| `tests/fixtures/` | 重现问题、验证补丁、检查兼容旧基线 | 仅在回归需求改变并完成审查后更新；不能随上游刷新自动覆盖 |
| `<BUILD_DIR>/feeds/`、`custom_feed/`、`package/` | 本次固件实际编译的源码 | 由现有构建脚本拉取、替换和修正，可能在下一次构建被清理 |

维护区记录的提交仅锁定本地审查快照，**不锁定下一次固件构建的插件版本**。构建依然使用 `wrt_core/modules/` 中原有的来源和分支策略。

## 构建与维护关系

```text
设备 .ini + 设备 .config + 公共配置 + fragments
                    │
                 build.sh
                    │
             wrt_core/update.sh
                    │
        上游源码与 feeds → 插件修正/补丁
                    │
           make defconfig → 选择检查
                    │
          下载与编译 → 成品检查 → firmware/

上游指定提交 → maintenance/plugins/ 原始快照
                    │
              差异审查与问题定位
                    │
       后续单独评审：补丁 + fixture + 回归验证
                    │
             再决定是否接入构建
```

## 文件归属约定

- 新设备的构建信息放在 `wrt_core/compilecfg/` 和 `wrt_core/deconfig/` 的同名文件中。
- 生效的源码替换和兼容逻辑放在 `wrt_core/modules/`；需要保留的修复以独立补丁放在 `wrt_core/patches/`。
- 用于维护的新上游源码放在 `maintenance/plugins/`，不混入生产模块或测试基线。
- 回归测试仍放在 `tests/`。第三方测试文件保留来源、提交、原路径和许可证说明。
- 当前行为说明放在 `docs/`；带日期的诊断、设计与计划作为历史记录保留，不能据此推断最新构建状态。

第一批来源、版本记录和后续更新步骤见 [插件源码维护说明](../maintenance/plugins/README.md)。现有生效补丁见 [插件兼容性说明](plugin-compatibility.md) 与 [SSR 兼容性说明](ssrplus-compatibility.md)。

SSR Plus+ 新版本的审查结论单独放在 [v198.2 迁移评估](ssrplus-v198.2-migration-assessment.md)。其中 `current-190-r11` 是可重新生成的比较副本，不是新增生产来源；原始 `v198.2` 与派生源码均不接入当前构建。
