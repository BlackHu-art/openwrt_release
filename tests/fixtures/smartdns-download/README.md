# SmartDNS 下载边界

`3fd1e27a/download.mk` 是当前固件下载框架的原始文件，没有修改：

- 仓库：`https://github.com/VIKINGYFY/immortalwrt`
- 提交：`3fd1e27a511851b41cf082b067b60099e8e026c4`
- 原路径：`include/download.mk`
- SHA-256：`d3ab6d3764a1e521998418588cfc76e0108fc8064f11dcd18e1b080ca1191d57`

`tests/test_smartdns_download.py` 默认用 GNU Make 展开这份真实下载规则，
验证原始 SmartDNS recipe 丢失提交参数的原因，并检查 WebUI 的 unset/n/y/m
选择行为。只替代 `rules.mk` 的构建变量、`package.mk` 的编译边界和 Rust
include；默认 SmartDNS 主程序下载仍由原始 `Download/default` 注册。

`REQUIRE_SMARTDNS_DOWNLOAD=1 python tests/test_smartdns_download.py` 必须在
Linux 上执行，并且需要 Bash、GNU Make、Git、Perl、curl、flock、GNU tar 和
gzip。这个门禁会下载并验证与既有 simple-obfs 回归相同的固定框架文件，
清空临时镜像清单，然后分别在 WebUI 选择为 y/m 时执行真实 WebUI 归档目标。
它不会构建 Rust/Node/WebUI，也不会下载 SmartDNS 主程序。缺少平台或工具时
必需门禁直接失败；未启用时网络测试明确跳过。

预期 WebUI 内容直接读取 `pymumu/smartdns-webui.git` 的固定 Git 对象：

- 提交：`3261c18b1b93d841e86d9e727557109ae71d71cd`
- tree：`190f76f34cfda865389b27e8f69887aa6a64edc3`
- 提交时间戳：`1766583635`
- 文件：109 个普通文件，无子模块、符号链接或可执行文件
- `.gitattributes`：`* text=lf`，没有 `export-ignore` 或 `export-subst`
- 最终 tar：151 个条目（109 文件 + 42 目录）
- tar SHA-256：`a203faeeb55271853270e0e84907d29d4e32043cf1bc86f4e45a4e78ff92816f`
- gzip SHA-256：`4401734712dd034eb1088ce440d1bc64d053dfcd6f63f66c08cd48ab68593042`

独立审计使用 Git blob 对象的内容、权限和固定时间戳重建 GNU tar/gzip，
与真实下载产物逐字节比较；错误哈希另行执行一次全新下载，要求实际下载器拒绝。
