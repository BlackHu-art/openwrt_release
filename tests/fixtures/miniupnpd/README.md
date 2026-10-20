# miniupnpd 补丁基线

此目录保存 ImmortalWrt packages 提交
[`dd29469e222e531bfeab7450bf8df680f7c2735a`](https://github.com/immortalwrt/packages/tree/dd29469e222e531bfeab7450bf8df680f7c2735a/net/miniupnpd/patches)
的五份原始补丁，用于复现 miniupnpd 升级到 2.3.11 后旧补丁未刷新的问题。

- `020` 的权限解析器重写已进入源码，2.3.11 又进一步调整了 const 指针、ctype 转换和地址解析，不能再重复应用旧补丁。
- `030` 的私网地址判断修复已进入源码。
- `040` 的日志改进仍有作用，但帮助信息的代码位置及 HTTP/HTTPS 初始化上下文已经变化。

生产修复仅移除内容哈希匹配的 `020` / `030`，将旧 `040` 替换为针对 2.3.11 刷新的版本，继续应用 `010`、`900` 和本仓库租约补丁。已审核的上游刷新版本原样保留；未知补丁内容仍须重新评估，不能靠忽略 patch 错误继续编译。

`e765fb8/` 保存上游 2026-10-20 提交
[`e765fb8870b5911992eb4b5a1624ad451e42f4a8`](https://github.com/immortalwrt/packages/commit/e765fb8870b5911992eb4b5a1624ad451e42f4a8)
刷新后的三份原始补丁。该提交删除了 `020` / `030`，并刷新 `010`、`040` 和 `900` 的上下文。本地兼容检查识别并保留其 `040`，也继续检查可能残留的旧补丁，避免新日志补丁绕过其他文件的校验。

| 文件 | SHA-256（LF） |
| --- | --- |
| `e765fb8/010-upnp-igdv2-compat.patch` | `dee6e7b7cd015b1b1b724fa7aca639efebbfdf9760b4360e7e9cb19289ef61d5` |
| `e765fb8/040-improve-logging.patch` | `69fb7a80e422b6533086b48c1a531eb2eb20c068a8a7f0722fc11ce905e83f23` |
| `e765fb8/900-miniupnpd-format-xml-to-make-some-app-happy.patch` | `0dee7611dcb4a737b3c55af114154b5a15bc6fc4bc03e6fdc7d227ffc3e75a9b` |

离线回归：`bash tests/test_miniupnpd_compat.sh`。

真实源码验证（先下载官方源码包）：

```bash
curl -fL -o /tmp/miniupnpd-2.3.11.tar.gz \
  https://github.com/miniupnp/miniupnp/releases/download/miniupnpd_2_3_11/miniupnpd-2.3.11.tar.gz
bash tests/verify_miniupnpd_source.sh /tmp/miniupnpd-2.3.11.tar.gz
```

脚本验证 SHA-256 `91994b127da735b2c97f19992e34420648c0e8c4ace8a4bcb0596e7685c48678`，先复现旧补丁失败，再分别验证旧基线兼容修复和 `e765fb8` 上游补丁链。两条路径均检查原版权限解析器保留、日志提示和租约设置；最新上游补丁还须保持逐字节不变。此验证不等同于交叉编译或路由器运行测试。
