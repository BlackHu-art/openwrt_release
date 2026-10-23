# SSR Plus+ v198.2 迁移评估源码

此目录保留 `190-r11` 与 `fw876/helloworld@v198.2` 的历史评估输入，并追加当前修复版 `190-r12` 的派生副本。当前固件构建不读取这里；构建来源仍是 `master`，生产兼容补丁由构建流程单独应用。

## 源码副本

| 目录 | 身份与用途 |
| --- | --- |
| [upstream-v198.2/](upstream-v198.2/) | 完整上游 Git tree，固定 tag `v198.2` → `45893d778767f3bdb2fcb6e873cf8f9a667d94d4`，未经项目补丁修改 |
| [current-190-r11/](current-190-r11/) | 原迁移评估使用的历史派生副本；保留原始比较与验证证据对应的字节 |
| [current-190-r12/](current-190-r12/) | 在同一 `2abdc9aa` 完整包上，由生产 `fix_ssrplus_compat` 生成的当前派生副本；包含 Xray 传输兼容修复，不是上游原始源码 |

`upstream-v198.2` 共 **962 文件、14,357,069 字节**，包含 LuCI、配套软件包的 Makefile/补丁、上游工作流及仓库内实际跟踪的源码。它并不包含各 Makefile 后续才下载的全部 Xray、Mihomo、Go 或 Cronet 源码和工具链。

`current-190-r11` 共 **61 文件、2,179,146 字节**。项目基线为 `6d76ce124426086bbc5f90a9fcb9fcc0ba3b0a41`；原始包 59 文件，加上项目运行辅助脚本与生成的来源清单。这是 Windows 上执行生产准备函数得到的源码副本，不是从路由器或已编译 IPK 提取的结果。

`current-190-r12` 共 **61 文件、2,183,205 字节**。它保留同一完整上游包的非保护文件，使用 `7fa4381` 后当前工作树的 27 份补丁和生产准备函数生成；fresh 与完整 r11 升级均重复准备，四次结果字节一致，嵌入清单覆盖十二个安装目标。具体生成输入 SHA-256 记录在新清单中，POSIX mode 在 Windows 上仅为记录元数据。没有执行固件编译、包安装或路由器操作。

## 记录入口

- [迁移评估报告](../../../docs/ssrplus-v198.2-migration-assessment.md)：25 份补丁的去留、语义缺口、核心依赖与迁移顺序。
- [上游来源锁文件](../sources.lock.json) 与 [逐文件原始清单](../manifests/ssrplus-v198.2.json)：完整 commit/tree、字节数、Git mode/blob、SHA-256。
- [r12 当前版本清单](current-190-r12.manifest.json) 与 [r12 准备验证](current-190-r12.verification.json)：当前 61 个文件的哈希、预期 Git mode、输入哈希及重复准备结果。
- [r11 历史版本清单](current-190-r11.manifest.json)：原迁移评估对应的 61 文件清单；下列历史比较结果仍以 r11 为输入。
- [比较与检查证据](comparison-evidence.json)：还原输入哈希、25 份补丁哈希及对干净 v198.2 的独立正反向应用检查、12 个受保护源文件比较、目录差异和生产门禁拒绝结果。
- [订阅逐 hunk 覆盖](subscription-coverage.json) 与 [外部核心依赖证据](external-evidence.json)：记录部分覆盖项及固定提交的 Go/Xray 版本约束。
- [独立验证结果](verification-results.json)：源码与 Git 对象一致性、补丁检查复核、临时 index 收录及恢复原 mode 后的完整 tree 校验。

语义评估与补丁文本可应用性分开记录。补丁不能直接应用，不等于它的功能尚未被上游实现；能应用，也不等于已兼容新版调用路径。

## 存储与后续维护

原始快照直接按 Git blob 导出，未修改上游文件或 `.gitignore`。v198.2 中 36 个可执行文件的模式及 1 个符号链接保存在清单中；链接在 Windows 上保存为目标文本。运行或构建前应从固定提交重新 checkout，或按清单恢复链接和执行位。当前比较副本的预期权限另见其清单。

保留上游忽略规则意味着 `.github/copilot-instructions.md` 虽然是上游跟踪文件，普通 `git add` 仍会忽略它。它在这里仅是归档的第三方数据。以后提交此快照时，需要额外显式加入：

```powershell
git add -f -- maintenance/plugins/ssrplus/upstream-v198.2/.github/copilot-instructions.md
```

迁移评估阶段仅在临时 Git index 验证完整收录和原始字节，当时没有暂存、提交或推送真实工作区的改动；这条历史记录不表示后续交付状态。维护区 `.gitignore` 放行上游的测试目录，以免受到项目根 `test/` 规则影响。

上游根 [LICENSE](upstream-v198.2/LICENSE) 与旧基线根 LICENSE 的 Git blob 相同；原文件版权声明保留。当前比较副本还包含本项目补丁生成内容，其来源记录见 `comparison-evidence.json`，不能把这份派生副本称为未修改上游版本。

需要刷新比较时，应重新取得目标固定 tag/commit，完整导出目录、重新还原项目补丁版本并重做清单；不能把滚动 `dev` 的新文件混入 `v198.2` 目录。本次没有生成或接入任何 `198` 系列生产迁移补丁。
