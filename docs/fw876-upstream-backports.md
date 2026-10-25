# fw876 必要修复移植记录

本页记录当前固定输入之上的生产修改，供其他电脑复现和继续维护。原始输入仍为
`fw876/helloworld@45893d778767f3bdb2fcb6e873cf8f9a667d94d4`（v198.2），
来源锁、维护区快照和插件选择不随本次补丁改变。

## 2026-10-25 采用的修复

| 修复 | 上游依据 | 本项目处理 |
| --- | --- | --- |
| Xray mKCP 伪装层顺序 | [31b180d](https://github.com/fw876/helloworld/commit/31b180df838e456bb36036bb8791f569af0fd661) | 合并至现有 [SSR Xray transport 补丁](../wrt_core/patches/ssrplus-v198-xray-transports.patch)，先生成 security/seed 条目，再生成伪装 header 条目 |
| Xray 打包复用 UPX 产物 | [20756ea](https://github.com/fw876/helloworld/commit/20756eaad8aa61ce7168dad90b56db2d7c81063c) 的 Xray 部分 | 在构建副本移植 `Build/Install` 压缩与 `Package/install` 复制；生产配方派生为 `26.10.21-r3`，保留十份核心补丁及 Go 门槛 |

KCP 新格式转换在本地已有，因此没有重复引入上游整个 `652714b`。
当前固定 Xray 为 26.10.21；自定义 `finalmask` 仍按原行为覆盖自动生成结果。
只使用 `none` 伪装时只有一个 security 条目；非空伪装与空 seed 的组合仍有两层，
同样需要正确顺序。

Xray 的原始配方和认证测试产物仍是 `26.10.21-r2`，由
[原始来源记录](../wrt_core/compat/proxy-cores/xray-26.10.21.json) 定义。
派生 r3 只改变打包压缩阶段，未更换核心源码、私有协议补丁或下载归档。
测试用 r2 核心可以验证未改变的协议配置行为，不能据此声称已经交叉编译或验收了 r3 固件。

## 本次未移植

- `69840fb`：Mihomo 内置 DNS 的进程识别修复。京东云当前选择 Xray，未选 SSR Mihomo；
  该修复按配置偏好识别后端，后续引入时还需覆盖实际核心回退路径。
- `652714b` 中的 Hysteria2 realm UPnP：属于新增功能，且审查的
  [上游代码](https://github.com/fw876/helloworld/blob/31b180df838e456bb36036bb8791f569af0fd661/luci-app-ssr-plus/root/usr/share/shadowsocksr/gen_config.lua#L791)
  引用了未定义的 `node`，不能原样整体同步。
- Mihomo AN7581 EIP93 加速与格式整理：不属于京东云 IPQ60xx 当前所需的修复。

这些取舍针对上述固定提交，不代表未来上游仍存在同样问题；再次同步时应重新比较提交。

## 验证入口与边界

- [Xray 配方回归](../tests/test_xray_core_compat.py)：完整原始/派生输入检查、十份补丁、Go 门槛、重复准备及实际 GNU Make 打包行为。
- [SSR transport 回归](../tests/test_ssrplus_core_transports.py)：当前 v198.2 KCP 生成顺序、自定义配置和真实核心本地互通；其他历史用例仍有独立说明。
- [完整回归](../tests/run_all.sh)；Windows 使用 [专用入口](windows-testing.md)，Linux 原生检查由 [CI 工作流](../.github/workflows/test_ssrplus.yml) 定义。
- 文档路径校验：`python tests/check_doc_links.py`。它检查维护文档的本地文件链接，不请求远端 URL，也不校验标题锚点。

真实 KCP 互通使用本机回环地址上的测试客户端、服务端和回显端点，不连接实际代理节点。
该结果不能代替京东云固件交叉编译、真实网络条件或路由器验收。
本次不改变 ChinaDNS-NG 的国内/可信双路查询策略；国内 DNS 延迟仍需独立检查运行参数和实际响应。

完整测试结果在实施计划的执行记录中保存：
[2026-10-25 实施计划](superpowers/plans/2026-10-25-upstream-fixes-and-maintenance.md)。
