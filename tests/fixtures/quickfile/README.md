# QuickFile 固定源码基线

`13f1a61/` 保存官方仓库
[sbwml/luci-app-quickfile](https://github.com/sbwml/luci-app-quickfile/tree/13f1a61d962e3a7790f7ab9898543be2ee5835cb)
提交 `13f1a61d962e3a7790f7ab9898543be2ee5835cb` 的两份原始 Makefile，来源记录见
[`source.json`](13f1a61/source.json)。这是测试 fixture，不是构建时的完整 QuickFile 源码，
也不属于 `wrt_core/managed/` 的 16 个顶层单元。

核心 recipe 为 `2.0.8-r1`，LuCI 为 `1.0.0-r1`。核心使用 rust/host 和
rust-package.mk 编译目标源码，再从 `PKG_INSTALL_DIR/bin/quickfile` 安装；LuCI
依赖 luci-nginx 与 quickfile。官方源码归档的 SHA-256 已核对为
`05596624c46331418296a86a4f0a457a9b5f8ff2d9bd81e0f4e8cb6a3933b7db`。
归档仍按 recipe 哈希外部下载，没有存入此 fixture。

旧适配按 `ARCH_PACKAGES` 替换预编译文件名，对这份 Rust recipe 没有匹配对象，
会成功返回而不改内容。它是失效 no-op，未据此证明当前发生了编译失败。
`add_quickfile` 已移除该改写，先用 `quickfile_verify.py` 检查候选 recipe 的
Rust 构建与安装结构，再替换构建目录中的源码；检查失败保留已有源码并返回错误。
该检查没有把完整上游提交固定为此 fixture。

[`test_quickfile_source.py`](../../test_quickfile_source.py) 覆盖原始 recipe 字节保留、
x86_64/aarch64 输入、不符合结构的预编译 recipe、缺失 Rust 依赖、无效源包哈希，
以及阶段调用的错误传播。测试不执行 Rust 交叉编译，不证明最终固件或 nginx/LuCI/终端功能通过。

更新基线时保留上游原始字节、提交和许可声明，同时审查 verifier、fixture 与回归。
不要仅修改旧 sed 的架构回退来适配新源码。
