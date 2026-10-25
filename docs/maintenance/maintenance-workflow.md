# 维护流程

先读 [架构与来源](architecture-and-sources.md)，确定本轮改的是配置、原始来源，还是构建副本适配。
保留其他人的未提交工作；新环境恢复按 [快速开始](quickstart.md)。

## 开始与定位

```powershell
git status --short --branch
git remote -v
git log -1 --format=fuller
git diff --stat
```

记录设备、来源完整提交、问题触发条件和实际失败阶段。设备选择看 `compilecfg/` 与 `deconfig/`；
插件来源先看生产锁，再从 `update.sh` 阶段追到 `modules/`、适配脚本和补丁。
不要依据维护快照的版本表猜测当前固件来源，也不要仅凭插件界面版本推断核心身份。

## 更新来源与补丁

1. 在独立审查目录获取指定来源，记录新旧完整 commit/tree、版本、依赖、下载哈希和许可证；先读差异，不执行下载源码中的脚本。
2. 只刷新参考快照时，按 [维护区说明](../../maintenance/plugins/README.md) 更新快照、manifest 和参考锁；这一步不改变生产。
3. 升级生产输入时，按 [受管说明](../../wrt_core/managed/README.md) 完整替换目标子树、删除上游已删除文件，同步生产来源锁。保留原始字节、mode 和链接目标，检查 Git 忽略规则是否漏文件。
4. 只移植修复时，将有来源提交的补丁放入 `wrt_core/patches/`，在已有模块/适配器接入构建副本。SSR 使用 `compat/ssrplus/patches.list`，其他对象沿现有适配入口；不能只加补丁文件而不接入调用链。
5. 更新对应 guard、fixture 和回归：先复现问题，再验证修复；覆盖重复执行、未知来源/部分应用拒绝和失败退出码。输入变化时要重新审查，不能仅改哈希让 guard 通过。
6. 更新当前行为说明和验证边界；历史诊断保留日期及适用版本，不把历史建议重新写成当前默认。

补丁阶段必须匹配目录生命周期：源码/feeds 修改优先在安装前；依赖 `package/feeds/` 的处理放安装后。
已有适配器通常先完整校验或在临时副本中预检，再发布修改；扩展时保留其拒绝未知输入和避免部分写入的约束。
插件、设备和 fragment 选择的变化应单独说明，不能由升级的新默认值隐式扩大范围。

## 验证与交付

以下检查从仓库根目录执行；Python 应来自已经恢复的环境。Windows 完整回归使用 PowerShell 包装入口。

```powershell
python tests/verify_upstream_sync.py
python wrt_core/managed_plugins.py check
git diff --check
```

先运行修改对象的相关测试，再执行 `tests/windows-tests.ps1 -Action run` 或 Linux 完整入口。
Linux 强制下载、原生 Kconfig、fw876 核心、权限/链接和网络命名空间检查以
[CI 配置](../../.github/workflows/test_ssrplus.yml) 为准。涉及平台特性时必须保留相应 Linux 证据。
文档修改还需检查相对文件链接及最终 diff；命令中的设备/分支必须能映射到当前仓库。

```powershell
python tests/check_doc_links.py
```

该检查器校验维护文档的仓库内相对路径，不扫描第三方源码，不证明外部 URL 可达或运行命令正确。

| 证据层级 | 能支持的结论 | 仍需独立验证 |
| --- | --- | --- |
| 来源锁和哈希检查 | 已审查输入完整、来源未漂移 | 配方能否编译、运行功能 |
| Windows 主机回归 | 固定输入、生成配置和受控逻辑 | Linux 权限/链接、网络命名空间 |
| Linux CI | 当次提交在必需依赖和隔离网络场景下通过 | 目标交叉编译、最终固件和设备 |
| 固件构建与成品门禁 | 对应设备产物构建并通过已实现的包/rootfs 检查 | 刷机、保留配置升级与真实业务 |
| 路由器实测 | 具体设备和网络条件下的行为 | 未测试设备、协议和升级路径 |

每次记录日期、仓库 SHA、命令、退出码、失败/跳过项和日志位置。CI 另记 run ID/attempt/head SHA，
固件另记设备、上游固件 SHA、fragments、产物身份；不要把不同提交的通过结果合并成一次验收。
`run_all.sh` 遇首个失败停止，未执行的后续入口应记“未执行”。

提交前查看 `git diff --stat`、完整 diff、`git status --short` 和 `git diff --check`，
确认原始来源、派生补丁和说明各自完整，未混入依赖目录、日志、固件、密钥或构建树修改。
提交/推送后核对远端 SHA，再按 [CI 排错](troubleshooting.md) 查看匹配提交的执行；
推送触发回归不等于触发固件构建或发布。
