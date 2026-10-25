# 维护快速开始

## 新电脑首次接手

先安装 Git；Windows 测试另需 Python 3.11+ x64 和默认位置 `C:\Program Files\Git` 的 Git for Windows。
仓库不会自动安装 Git/Python。测试工具和网络要求详见 [Windows 回归说明](../windows-testing.md)。

```powershell
git clone https://github.com/BlackHu-art/openwrt_release.git
cd openwrt_release
git remote -v
git status --short --branch
git log -1 --format=fuller
```

已有仓库先检查工作区，确认当前分支与上游后再 `git pull --ff-only`；存在本地修改或分叉时先处理其归属。
需要继续指定维护分支时，从远端分支检出它；不要把默认分支的文件状态当作另一分支的执行结果。

Windows 在仓库根目录恢复专用环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action install
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action run
$LASTEXITCODE
```

`install` 下载固定依赖；`check` 和 `run` 不补下载。默认依赖在仓库外的
`%LOCALAPPDATA%\openwrt-release-test-deps`，以脚本实际输出路径为准；自定义时三次操作传同一个
`-DepsDir`，必要时用 `-Python` 指定解释器。无需复制旧电脑的依赖目录或激活 venv。
失败与跳过项、日志位置、符号链接限制均见详细说明。

## Linux 与构建环境

Linux 完整回归入口是 `bash tests/run_all.sh`，它不自动安装测试依赖。
[Linux CI 工作流](../../.github/workflows/test_ssrplus.yml) 是完整准备步骤的来源：Ubuntu 24.04、
系统网络/归档/编译工具、固定 Python requirements、Ruby 3.4、Node 22，以及校验过的官方 Xray、
fw876 Xray 和两版 Mihomo 测试核心。复现 CI 时还需保留其必需环境变量，并执行两条独立网络命名空间检查。
仅在普通 Linux shell 执行回归入口可能跳过缺少能力的用例，不能称为完整 CI 等价验证。

固件编译另按 [根指南](../../README.md) 准备 Linux 或 Docker 环境；主机回归环境不是固件工具链。
先用配置预览检查目标，无需下载上游或写构建目录：

```bash
bash build.sh jdcloud_ipq60xx_immwrt config_preview
```

`debug` 会准备源码并执行到 `make defconfig`；默认模式会下载、交叉编译并刷新 `firmware/`。
不要在保存人工修改的构建工作树上把完整构建当成只读检查。

## 给新电脑／新聊天的交接最小清单

可直接提供以下内容，让接手者先读 [文档索引](../README.md)：

1. 仓库地址、维护分支、`git rev-parse HEAD` 和 `git status --short --branch`；列明未提交改动的归属。
2. 目标设备配置名、构建模式、额外/移除的 fragments；本轮允许改动与禁止改动的范围。
3. 问题触发条件、预期行为、相关文件/函数与来源完整提交；补丁维护参考 [流程](maintenance-workflow.md)。
4. 已执行命令、真实退出码、失败与跳过项、日志位置；CI 附 run ID、attempt 和 head SHA。
5. 尚未验证的 Linux 能力、目标交叉编译、最终产物、保留配置升级与路由器功能。

证据按“源码确认／已执行通过／已执行失败／跳过／尚未执行”记录，附日期和提交。
不能把“配置了门禁”“测试核心下载成功”写成“门禁通过”或“协议互通”。
日志交接应去除订阅地址、访问令牌、私钥与其他凭据；机器本地路径用可替换的占位说明。
