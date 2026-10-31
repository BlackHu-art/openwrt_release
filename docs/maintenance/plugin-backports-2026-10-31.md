# 2026-10-31 插件必要修复回移

本轮仅修复 OAF、Quickstart、OpenClash 的运行逻辑。生产来源、固定提交、原始源码、维护快照、插件选择及设备编译配置均不变。修复在源码准备阶段写入独立构建副本；不是整体升级上游分支。

## 来源与范围

| 对象 | 已审查修复来源 | 本地派生入口 |
| --- | --- | --- |
| OAF | [small-package 0892bf4f](https://github.com/kenzok8/small-package/commit/0892bf4fbaa2d4f99fe5e9c1425ced31574c965e) | [oaf_runtime_compat.py](../../wrt_core/oaf_runtime_compat.py)、[补丁与取舍](../../wrt_core/patches/oaf-runtime-safety.json) |
| Quickstart | [small-package d4611b99](https://github.com/kenzok8/small-package/commit/d4611b99118531f49f26a834e5ee6400e201c15a) | [quickstart_compat.py](../../wrt_core/quickstart_compat.py)、[局部补丁](../../wrt_core/patches/quickstart-runtime-safety.patch) |
| OpenClash | [订阅保留 373d0023](https://github.com/vernesong/OpenClash/commit/373d0023c7006fee3bb66c90f40355ef02e2d682)、[ETag 40150081](https://github.com/vernesong/OpenClash/commit/4015008110e8a40b41c416677c0e7224635d9379)、[组名引用 2cd5ad98](https://github.com/vernesong/OpenClash/commit/2cd5ad9847b1debcb65b9843925041305aa3c2b3) | [openclash_runtime_compat.py](../../wrt_core/openclash_runtime_compat.py)、[完整输入身份](../../wrt_core/compat/openclash-runtime/sources.json) |

OAF 只回移数据包范围检查、softirq 原子分配、非线性 skb 精确复制、HTTP 边界及失败解锁；LAN 接口读取改用现有 `fwx` schema。保留 3000 字节 DPI 上限及原有默认关闭、ACL 和服务生命周期处理；不引入版本、UI 或昵称/白名单 reload 变化。

Quickstart 保留受管兼容后端的温度/status 适配，在临时副本装载该模板后修复完整发送、chunk/EOF/CRLF 处理。显式加载 `nixio.util`；其 `recvall` 可返回短串，必须验证长度。控制器和安装脚本分别验证包名，非法参数在写日志和安装前拒绝；合法参数按原值传递，执行失败保留非零结果。原模板及来源锁不改。

OpenClash 保留原有六份补丁，新增订阅下载/核心校验失败保留旧配置、成功替换后才提交 ETag、锁定缓存更新及策略组引用同步。Ruby 校验器不可运行也拒绝替换。仅移植当前代码可用的逻辑，不引入 dev 整体版本、oixCloud 新流程、路由优先级、多 WAN、Tailscale 或 WAN 规则改动。

## 构建与失败处理

- `update_oaf_deconfig` 先预检运行源码，再执行原默认值/ACL 修正，最后发布 C 修复；任一来源校验失败均停止该阶段。
- `fix_quickstart` 先对三份运行输入整体预检，再发布派生内容；不会先用模板覆盖后端、随后才发现控制器漂移。
- `fix_openclash_compat` 在 scratch 中逆序规范化完整已知补丁，验证受保护文件的原始 blob，再顺序应用完整补丁栈。后续补丁失配不会使前置六补丁先写入真实构建目录。
- 原始/完整已准备状态可重复执行；未知源码或残缺补丁拒绝。普通发布错误按适配器回归验证恢复；进程被强制终止后的残缺构建树应重新装载，不承诺跨进程崩溃的多文件事务。
- OpenClash 首次发布内容变化时保留权限但更新 mtime，使默认依赖路径/时间戳的 OpenWrt prepare 缓存失效；完整重复准备不改 mtime，发布失败恢复原字节及时间戳。
- `.gitattributes` 固定补丁 LF 和原始 fixture 字节；补丁上下文保留必要空格，不能通过清理空白改变已审查输入。

## 回归与复跑

新增 [OAF C 回归](../../tests/test_oaf_runtime.py)、[Quickstart Lua/Shell 回归](../../tests/test_quickstart_runtime.py)、[OpenClash Shell/Lua/Ruby 回归](../../tests/test_openclash_updates.py)，并扩充 [实际构建入口组合](../../tests/test_managed_build.py)。均已接入 [完整入口](../../tests/run_all.sh)。

Windows 依赖沿用 [现有说明](../windows-testing.md)。OAF 新增主机 C 编译要求：可用 GCC/Clang，或安装包含 C++ 工具链和 Windows SDK 的 Visual Studio Build Tools。测试可通过 `vswhere` 自动寻找 MSVC，并只在短生命周期子进程加载 `vcvars64.bat`；不修改全局环境。安装选项见 [Microsoft 官方说明](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line)。缺少编译器明确失败，不跳过 C 测试。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/windows-tests.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File tests/windows-tests.ps1 -Action run
```

Linux CI 已具备 GCC、Ruby、Lua 和两个固定 Mihomo 核心，继续执行完整入口及原有 namespace 验证。Windows 的翻译链接创建边界仅在专项测试中模拟；Linux 使用真实链接。C 主机 harness 验证生产函数和内核 API 边界的替身，不能替代完整内核模块编译与实机流量验证。

本次 Windows 完整入口于 2026-10-31 21:03～21:29 执行，运行记录 `20261031-210339-079610` 的 `result.json` 与 `regression.log` 均确认退出码 0。46 组 unittest 共 663 项：643 通过、20 项平台跳过；16 个 Shell 入口中 15 个通过，Linux Kconfig 原生检查按平台跳过。新增三组专项共 67 项全部通过，包含 64 种 OpenClash 历史补丁组合。

本次通过 `windows_test_env.py run` 执行相同的完整入口，并设置 `MIHOMO_OLD_TEST_BIN`、`MIHOMO_NEW_TEST_BIN` 和 `OPENCLASH_REQUIRE_MIHOMO=1`，实际验证两版核心；核心获取脚本见 [fixture 说明](../../tests/fixtures/openclash/0.48.002/README.md)。Windows 跳过项涉及真实链接/模式、Linux 原生下载/核心、服务和 rootfs 边界；推送后的原有 Linux CI 继续补验，结果以对应提交的 Actions 运行记录为准。

30 个受管包完整性、上游同步不变量、文档本地链接及差异空白检查通过；来源、选择和固件编译配置无差异。本轮不包含路由器 nginx/Samba/fstab 排查、核心版本升级、固件交叉编译或实机验证。
