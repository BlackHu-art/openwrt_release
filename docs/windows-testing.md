# Windows 本地回归测试

Windows 测试入口为 [`tests/windows-tests.ps1`](../tests/windows-tests.ps1)，实际环境管理由 [`tests/windows_test_env.py`](../tests/windows_test_env.py) 完成。它在仓库外安装专用依赖，再执行现有 [`tests/run_all.sh`](../tests/run_all.sh)，适合本地检查构建契约、补丁、插件配置和运行逻辑。

## 环境要求

- Windows x64，已安装 **Python 3.11 或更高版本的 x64 解释器**，可创建 `venv` 并使用 pip。
- Git for Windows 安装在默认目录 **`C:\Program Files\Git`**。现有多处测试固定使用该路径，暂不支持其他安装目录。
- Windows 自带的 `%SystemRoot%\System32\tar.exe` 能解压 zstd 格式的 `.tar.zst` 文件和 Ruby 的 `.7z` 归档。
- 首次 `install` 时能访问 Python 包索引、MSYS2 官方下载源，以及 Xray、Ruby、Node.js 的官方发行资源。
- 可写的仓库外依赖目录。默认值为 **`%LOCALAPPDATA%\openwrt-release-test-deps`**；Microsoft Store 应用可能重定向本地应用数据路径，以脚本实际打印的绝对路径为准。

脚本不会自动安装 Git 或 Python，不会替换 Git for Windows 的 DLL，也不会修改用户或系统的全局 `PATH`。Ruby 和 Node.js 使用依赖目录内的固定私有版本；测试工具只用于本地回归，不打包进固件。

## 首次安装

在仓库根目录打开 PowerShell，执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action install
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action run
```

`-ExecutionPolicy Bypass` 仅用于本次启动的 PowerShell 进程，无需更改系统执行策略。三个操作的职责如下：

| 操作 | 行为 |
| --- | --- |
| `install` | 创建专用 Python 虚拟环境，安装固定版本的 Python 包，下载并校验 flock、Xray、Ruby 和 Node.js 测试工具 |
| `check` | 检查现有依赖、二进制哈希、Bash、flock 实际互斥能力、Xray 与 Ruby / Node.js 版本和运行能力，不下载依赖 |
| `run` | 先检查环境，再运行完整回归入口并保存日志和结果，不下载依赖 |

需要指定依赖位置或 Python 解释器时，对每次操作使用相同参数：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action install -DepsDir 'D:\openwrt-test-deps' -Python 'C:\path\python.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action check -DepsDir 'D:\openwrt-test-deps' -Python 'C:\path\python.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\windows-tests.ps1 -Action run -DepsDir 'D:\openwrt-test-deps' -Python 'C:\path\python.exe'
```

将示例解释器路径替换为实际的 x64 Python。`-DepsDir` 必须在仓库外，不要指定仓库本身或其子目录。带空格的路径必须加引号。

脚本根据自身位置找到仓库，因此可以从任意当前目录调用其绝对路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File 'D:\Source Projects\openwrt_release\tests\windows-tests.ps1' -Action run -DepsDir 'D:\Test Dependencies\openwrt-release'
```

也可以直接调用 Python 入口；以下命令从仓库根目录执行：

```powershell
python tests/windows_test_env.py install --deps-dir 'D:\openwrt-test-deps'
python tests/windows_test_env.py check --deps-dir 'D:\openwrt-test-deps'
python tests/windows_test_env.py run --deps-dir 'D:\openwrt-test-deps'
```

若要指定 Python，可使用 PowerShell 调用运算符，例如 `& 'C:\path\python.exe' tests/windows_test_env.py check --deps-dir 'D:\openwrt-test-deps'`。直接调用 Python 入口时，同样可以用脚本绝对路径从任意目录运行。

## 日常复跑与结果

依赖安装完成后，日常运行只需执行 `-Action run`。需要单独排查环境时执行 `-Action check`；二者都不会自动下载缺失依赖。依赖缺失或校验失败时，应根据错误修复环境，再显式运行 `install`。从旧版环境升级时，也需显式运行一次 `install`，补齐固定 Ruby 与 Node.js，再运行 `check` / `run`。

回归入口实际执行：

```bash
bash --noprofile --norc -x tests/run_all.sh
```

脚本仅为测试子进程设置环境：将专用 venv、flock 和 Git 工具目录加入 `PATH`，设置 `SSRP_TEST_FLOCK_DIR`、`XRAY_TEST_BINARY`、`PYTHONDONTWRITEBYTECODE`、`PYTHONUTF8=1`，以及指向受管绝对路径的 `RUBY`、`NODE`。清除继承的 `PYTHONPATH`、`PYTHONHOME`、`RUBYOPT`、`RUBYLIB`、`GEM_HOME`、`GEM_PATH`、`NODE_OPTIONS` 和 `NODE_PATH`，避免外部运行环境干扰测试；Python 强制 UTF-8 以正确读取中文测试文件。无需手动激活 venv。

Windows 入口强制设置 `OPENCLASH_REQUIRE_RUBY34=1`、`OPENCLASH_REQUIRE_NODE=1` 和 `REQUIRE_XRAY_TEST_CORE=1`。OpenClash AST 覆写测试必须执行 Ruby 3.4 或更高版本，dashboard 和文件名表单测试必须执行真实 Node.js，共享 Xray 配置必须执行真实核心解析；依赖缺失时不能跳过后将整轮判为通过。

每次回归的输出保存在实际依赖目录下：

```text
<依赖目录>/runs/<时间戳>/
├── regression.log    # 完整回归输出，包含 Bash 执行跟踪
└── result.json       # 本次运行结果
```

以脚本打印的日志路径为准。`run` 将回归进程的真实退出码返回给调用者；PowerShell 中可用 `$LASTEXITCODE` 查看。失败时先看 `regression.log` 中首个失败入口及其上下文，不要只看最后一行。`tests/run_all.sh` 遇到失败会停止，因此提前结束的运行不代表后续测试已经执行。

完整回归执行期间按 `Ctrl+C` 取消时，脚本返回 `130` 并清理本次回归进程树。若根进程已经自行退出，或系统拒绝终止进程，`result.json` 会记录 `cleanup_error`；此时根据日志检查遗留进程，不能据退出码认定所有后代进程均已结束。

## 固定依赖与更新

Python 依赖固定在 [`tests/requirements.txt`](../tests/requirements.txt)，安装操作使用 `pip install -r tests/requirements.txt` 读取它：

| 依赖 | 固定版本 | 用途 |
| --- | --- | --- |
| PyYAML | `6.0.3` | YAML 配置检查 |
| Lupa | `2.8` | 执行测试中的 Lua 逻辑，包括 `lupa.lua51` |
| MSYS2 util-linux | `2.40.2-2` | 从官方包中仅提取 `flock.exe`，验证真实文件锁互斥 |
| Xray | `26.10.21`，官方紧急安全更新 | 对生成配置执行核心解析检查 |
| [RubyInstaller](https://github.com/oneclick/rubyinstaller2/releases/tag/RubyInstaller-3.4.9-1) | `3.4.9-1`，Ruby `3.4.9` | 私有 `bin` / `lib` 运行目录，执行真实 Ruby 3.4 AST 与 YAML 覆写检查 |
| [Node.js](https://nodejs.org/download/release/v22.23.4/) | `22.23.4` | 仅提取 `node.exe`，执行 dashboard 与文件名 JavaScript 检查 |

Xray 通过 [`tests/fetch_xray_test_core.py`](../tests/fetch_xray_test_core.py) 下载固定 Windows x64 发布包，并校验 ZIP 哈希。Ruby 使用[官方便携归档](https://github.com/oneclick/rubyinstaller2/releases/download/RubyInstaller-3.4.9-1/rubyinstaller-3.4.9-1-x64.7z)，Node.js 使用[官方 Windows x64 ZIP](https://nodejs.org/download/release/v22.23.4/node-v22.23.4-win-x64.zip)。Windows 环境脚本还校验提取后的工具文件和 Ruby 完整运行目录，当前值如下：

| 文件 | SHA-256 |
| --- | --- |
| MSYS2 util-linux 下载包 | `969edb185d37986e6feddb3c54807598e3cc6774b736fec3a27d5d27731f7fdd` |
| `flock.exe` | `20ea2583f3c464a19dcb618141866c4f5794842952259edcc578feec79917b8a` |
| `Xray-windows-64.zip` | `fc58c39ee2f2717b4c54d28d374362389e5319b20ae44aea76ea45a5243ec827` |
| `xray.exe` | `c77a00eb84fb93ae044c2d771a1cabcc033b81e487253fbc35b12df6879c1e15` |
| `rubyinstaller-3.4.9-1-x64.7z` | `4375268618b61dadf53bf8e54beaca74ea30580c90d3c47ea9f2a134bd3e494e` |
| `ruby.exe` | `77e75784ff76f347ae316150b5b7b2f5eb91bb264ab39c6820600d1b3df6b6bb` |
| Ruby `bin` / `lib` 运行树（按环境脚本算法） | `0480aa03bcbbd69919f0fccecb0000076081c8186100a6096c302cb304d211ee` |
| `node-v22.23.4-win-x64.zip` | `cbc74b5e0982c9dbb41525fd8fb5dcd32fbee237863f7829072f4639a1ce5f20` |
| `node.exe` | `dccc52de28d8df2ee22d2062424f8c563070d95d8ad70c54c4bf01d590dec14f` |

`check` / `run` 校验 Ruby 完整运行树，并执行实际 YAML 模块运行检查；真实 AST 与覆写入口由回归执行。Node.js 检查版本并执行内置 VM 模块烟测。仅确认命令存在或版本字符串正确不足以通过环境检查。
Ruby 与 Node.js 归档缓存位于 `<依赖目录>/downloads/`；`install` 可以使用已通过固定哈希校验的缓存修复对应运行文件。环境元数据保存在依赖目录的 `environment.json` 中。

版本维护应作为仓库变更处理：先确认官方来源及下载包、可执行文件的校验值，再同步更新脚本、依赖文件和本说明，重新执行安装、环境检查与回归。不要因下载失败而改用未校验的二进制，也不要把哈希校验或必需依赖检查改成跳过。

更换 Xray 版本时，还需核对 [`tests/fixtures/proxy-cores/`](../tests/fixtures/proxy-cores/README.md) 中的固定基线和 [`tests/test_shared_xray_compat.py`](../tests/test_shared_xray_compat.py) 的共享核心配置用例。现有验证基线为 53 份生成配置，其中包括 19 份 SSR Plus+ 配置；这不是 unittest 用例数量。不能仅凭 `xray version` 输出正确就认为配置兼容。

Windows 将完整生成 JSON 经 Xray 官方 `stdin:` 输入交给真实核心解析，避免本机原生进程与 Python 读取临时文件内容不一致；Linux CI 继续通过文件加载。两种入口都检查 53 份合法配置，并确认无效协议被核心明确拒绝。这不验证 Windows 临时文件加载，也不改变固件中的配置生成或加载流程。

## 常见问题与验证边界

| 现象 | 处理方式 |
| --- | --- |
| 找不到 Git Bash | 确认 Git for Windows 位于 `C:\Program Files\Git`；现有测试不支持其他安装目录 |
| 找不到 Python、版本或位数不符合要求 | 安装 Python 3.11+ x64，使用 `-Python` 指定真实解释器路径 |
| `tar.exe` 无法解压 `.tar.zst` 或 `.7z` | 检查 Windows 自带 tar 的 zstd / 7z 支持，更新到满足要求的系统工具后重试 |
| 下载超时或无法连接 | 检查网络及对应官方源的可达性，恢复后重新运行 `install`；`check`、`run` 不会补下载 |
| 下载包或可执行文件 SHA-256 不匹配 | 保留错误输出，核对固定版本与官方来源，排查下载损坏或文件被替换；不要跳过校验 |
| flock 存在但互斥检查失败 | 查看检查错误并确认 Git/MSYS 运行环境兼容；不要把其他 MSYS2 DLL 复制到 Git 安装目录 |
| Ruby / Node.js 缺失、版本不符或运行检查失败 | 使用同一个 `-DepsDir` 显式重新执行 `install`，再执行 `check`；不要改用全局命令或取消强制检查 |
| 找不到刚安装的依赖或日志 | 采用脚本实际打印的依赖路径；显式使用同一个 `-DepsDir`，并留意 Store 应用的路径重定向 |

Windows 仍有依赖 Linux 能力的既有跳过项，包括 `/proc` 与真实 SIGKILL 场景、已安装的 dnsmasq、`luac`、BusyBox，以及 POSIX 安装权限。实际跳过项以本次日志为准，测试新增后入口数和用例总数可能变化。必需的 PyYAML、Lupa、flock、Xray、Ruby 3.4+ 或 Node.js 缺失时，环境检查应失败，不能把新增跳过当作通过。

本地回归覆盖固定测试输入、配置生成和受控运行逻辑；Xray 在这里用于配置解析。Windows 测试通过不能替代 Linux 网络命名空间 CI、固件交叉编译、成品校验或路由器实测。

OpenClash TUN capability regression also accepts explicitly downloaded old/new
Mihomo cores. Use `tests/fetch_mihomo_test_cores.py --generation old --output <path>` (or `--generation new`) for SHA-256 pinned official 1.19.30/1.19.33 assets, then set
`MIHOMO_OLD_TEST_BIN`, `MIHOMO_NEW_TEST_BIN` and `OPENCLASH_REQUIRE_MIHOMO=1`
before running the wrapper. CI always provisions both and requires these checks.
The wrapper preserves these environment variables. Binary parsing checks do not
start forwarding services. HomeProxy's optional actual-core check uses
`SING_BOX_TEST_BIN`; the Node generation checks still run without that binary.
