# SmartDNS 下载边界

`3fd1e27a/download.mk` 是旧 IPQ60xx 固件下载框架的原始文件，没有修改：

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
它不会构建 Rust/Node/WebUI；新增核心检查会实际获取主程序固定归档。缺少平台或工具时
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

## 核心 canonical 归档及双框架门禁

`000a4e74/download.mk` 是 LiBwrt 的另一份原始下载规则，没有修改：

- 仓库：`https://github.com/LiBwrt/openwrt-6.x`
- 提交：`000a4e74b17edfdc296f9eaa674344fc0adaaf95`
- 原路径：`include/download.mk`
- SHA-256：`d06a7ba7746d65121bd6d374dcad1e4fca359b675f23fe5b89522849fe99077f`

测试中 `MODERN_FILES` 同时固定此底座的 `scripts/download.pl`、`dl_github_archive.py` 和
`projectsmirrors.json` 的完整 SHA-256；真实网络门禁获取这些文件并校验后使用。
下载程序仍是上游实现，仅在临时镜像清单中清空公共镜像，避免命中旧缓存遮蔽实际来源。

核心采用 [上游已合并的 codeload 获取方式](https://github.com/pymumu/openwrt-smartdns/commit/1db3543cfaa397cd1115b0479416f73062711a63)，
保留当前 `136c0c2690138d6dedd8b520281aafe49112643f` 源码，不采用上游版本升级。
归档 SHA-256 为 `fd7bfb126ba15764d89a3a57efbea67602105a7bf394f81b7b5dd81693ddc5cb`，
859558 字节；Git tree `4f7381b2b6778f5f6b96d7e2dbdf7167753d2b52`，时间戳 `1769178721`。
实际包内 445 个文件 / 546 个条目全部与独立读取的 Git blob 比对，包括可执行模式，
归档根目录为 `smartdns-136c0c2690138d6dedd8b520281aafe49112643f`。
GitHub tar 的 owner/group 为 0/root，普通文件 0664，可执行文件 / 目录 0775，
对应 `git archive` 默认 `tar.umask=0002`；全局 PAX comment 标识完整固定提交。

核心真实下载在上述两个框架下均执行，校验实际 `PKG_BUILD_DIR`、真实解包与优化补丁路径，
再用错误哈希要求实际下载器拒绝字节并删除临时下载。此核心检查与原 WebUI 真下载共用
`REQUIRE_SMARTDNS_DOWNLOAD=1`，Linux 必需门禁不能跳过；还需要 `patch` 工具。
默认离线检查展开两个框架的核心命令和构建路径，保留 WebUI unset/n/y/m 选择测试。

原 `.tar.zst` 的 `d7e149…` 已由固定 Git blob + GNU tar 1.35 / zstd 1.5.7 独立重现，
原配方的 `5ef82e…` 生产环境无法从已过期日志恢复；没有把未证明的工具版本解释当成事实。
修复使用直接校验 canonical 字节的上游方案，避免本机重新压缩的字节差异，不放宽完整性检查。
