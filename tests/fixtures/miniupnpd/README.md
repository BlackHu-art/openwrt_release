# miniupnpd 补丁基线

此目录保存 ImmortalWrt packages 提交
[`dd29469e222e531bfeab7450bf8df680f7c2735a`](https://github.com/immortalwrt/packages/tree/dd29469e222e531bfeab7450bf8df680f7c2735a/net/miniupnpd/patches)
的五份原始补丁，用于复现 miniupnpd 升级到 2.3.11 后旧补丁未刷新的问题。

- `020` 的权限解析器重写已进入源码，2.3.11 又进一步调整了 const 指针、ctype 转换和地址解析，不能再重复应用旧补丁。
- `030` 的私网地址判断修复已进入源码。
- `040` 的日志改进仍有作用，但帮助信息的代码位置及 HTTP/HTTPS 初始化上下文已经变化。

生产修复仅移除内容哈希匹配的 `020` / `030`，将 `040` 替换为针对 2.3.11 刷新的版本，继续应用 `010`、`900` 和本仓库租约补丁。版本或补丁内容变化必须重新评估，不能靠忽略 patch 错误继续编译。

离线回归：`bash tests/test_miniupnpd_compat.sh`。

真实源码验证（先下载官方源码包）：

```bash
curl -fL -o /tmp/miniupnpd-2.3.11.tar.gz \
  https://github.com/miniupnp/miniupnp/releases/download/miniupnpd_2_3_11/miniupnpd-2.3.11.tar.gz
bash tests/verify_miniupnpd_source.sh /tmp/miniupnpd-2.3.11.tar.gz
```

脚本验证 SHA-256 `91994b127da735b2c97f19992e34420648c0e8c4ace8a4bcb0596e7685c48678`，先复现旧补丁失败，再验证完整修复后补丁链、原版权限解析器保留、日志提示和租约设置。此验证不等同于交叉编译或路由器运行测试。
