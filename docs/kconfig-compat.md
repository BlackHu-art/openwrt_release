# Qt5、squeezelite 与 fwknop/GnuPG2 循环依赖兼容

[构建 40076155141](https://github.com/BlackHu-art/openwrt_release/actions/runs/40076155141) 在 `make defconfig` 报告两个循环。该次流程继续到下载阶段，最终失败点是 SmartDNS WebUI；循环依赖同样需要修复，不能将它当作正常配置结果。

- Qt5：`PACKAGE_qt5base-gui` 的条件 Mesa 依赖经 `package-metadata.pl` 传递库的限制，引用 OpenGL 选项；OpenGL choice 又依赖父包，构成环。
- squeezelite：`SQUEEZELITE_WMA_ALAC` 条件依赖 FFmpeg，FFmpeg 的条件库约束向上展开；整个 custom 配置被 `if PACKAGE_squeezelite-custom` 包围，构成环。

现有 `package-metadata.pl` 中虚拟 provider 比较符号的修正不能消除这两个环。新适配不扩大对元数据生成器的改写，而在安装 feeds 前调用 [`kconfig_compat.py`](../wrt_core/kconfig_compat.py)，验证完整配方后只修改构建副本：

1. Qt5 OpenGL choice 去除父包依赖，仍默认 `NONE`。
2. squeezelite custom 的父包 `if` 改为普通 menu，全部功能开关仍默认 n。

这些选项会在配置菜单中可见，但不会因此选择父包或库。原 `DEPENDS`、版本、编译参数和用户配置均保留；选中父包后仍按功能开关选择 Mesa、FFmpeg 和相应库，库的架构、video-support 等限制仍生效。上游 FFmpeg 配方已使用同类无父包 guard 的菜单，并说明其避免循环的原因。

审查输入来自 `openwrt/video@bea0fb29f9573ab4c9bd77a9a495127958992d53`、`immortalwrt/packages@72c7391fb2d04080afd0bfe919605749f81eb747` 和既定固件提交 `3fd1e27a511851b41cf082b067b60099e8e026c4`。这些提交用于固定测试输入，不改变生产 feeds 的获取来源或策略。完整身份和校验值见 [fixture 记录](../tests/fixtures/kconfig-compat/sources.json)。

对没有对应包的其他固件源码，适配跳过不存在的包；目录存在但文件缺失、源文件出现未知变化或仅应用部分修复时，必须失败。所有存在包先完成校验，再开始写入，重复执行不重写。

[`test_kconfig_compat.py`](../tests/test_kconfig_compat.py) 使用真实配方、`Dumpinfo/Package` 和 `package-metadata.pl`，分别重现两个原始环，验证默认未选择包、功能开关、条件库依赖、限制条件、缺包、漂移拒绝和错误传播。无关库作为独立叶节点，工具链和编译目标隔离，不等于解析完整固件所有 feeds。

Windows 使用固定 `kconfiglib==14.1.0`；Linux 必需门禁另外从固定上游源码编译真实 `scripts/config/conf`，用同一批生成元数据和配置场景复验：

```bash
python3 tests/test_kconfig_compat.py -v
REQUIRE_KCONFIG_CONF=1 bash tests/test_kconfig_linux.sh
```

原生门禁需要 Linux、GCC、GNU Make、Perl 和 Python 3。已保留上游生成的 lexer/parser，因此不需要临时重新生成解析器。测试不修改 `deconfig/`、`compilecfg/` 或固件插件选择，也不执行 Qt5/squeezelite 目标架构编译。

## 2026-11-21 来源变体

新增精确审查 master、openwrt-25.12、openwrt-24.10 的 squeezelite 配方，以及 video `6a3b5fd6` 的 Qt5 依赖/打包修复。保留各版本下载身份、依赖和冲突声明；完整原始输入见 `tests/fixtures/kconfig-compat/variants/` 与来源记录。

新版 Qt5 的 linuxfb 对 libdrm 增加条件依赖，会经元数据传递引入 DRM 与父包的新循环。本地先用真实配方复现，再仅对此已审查配方去除 DRM 功能的父包 guard；其 libdrm 条件依赖和开关语义保留。旧配方仍只应用原 OpenGL 修复。新增分支样本均验证未选择包、功能库依赖、默认值、重复执行和未知变化拒绝，Linux 原生 conf 同样执行这些案例。

## 2026-11-21 fwknop / GnuPG2 兼容修复

实际 Linux 配置验证在
[京东云 ImmortalWrt 流程 44868990580](https://github.com/BlackHu-art/openwrt_release/actions/runs/44868990580)
报告新的环：`fwknopd` 被 LuCI 页面选中，LuCI 经传递依赖受 `FWKNOPD_GPG` 限制，
GPG 选项又处于 fwknop 父包菜单内。流程当时仍以成功结束，因此退出码不能替代日志中循环诊断的检查。

锁定的 LuCI `8724b54d` 配方仅声明 `+fwknopd`，没有直接增加 GPG 限制。
真正来源是 packages 的 GnuPG2 配方：`gnupg2-utils` 使用 `DEPENDS:=gnupg2 +libcurl`，
要求主程序预先启用，却没有自动选中它；元数据生成器因而把父包的条件依赖向 LuCI 传播。
这与 [上游问题 31215](https://github.com/openwrt/packages/issues/31215) 相同。
[上游作者建议](https://github.com/openwrt/packages/issues/31215#issuecomment-6808924386)
将该依赖改为 `+gnupg2`，让工具包自动携带必需的主程序。该建议尚未以合并提交提供；
本项目按精确来源实现这一兼容修复，不将其描述为已合并的上游补丁。

适配器仅对已审查的完整 GnuPG2 配方增加这一处 `+`，不修改 fwknop 或 LuCI 配方、
GPG / NFQ 捕获的父包 guard、默认 n、条件库、版本或编译参数。
旧/新 master 的配方相同，25.12 / 24.10 的另一份配方也经过完整校验。
维护分支的 fwknop 尚使用 GnuPG 1，未重现本次环；其 GnuPG2 工具包同样修复必需运行时的自动选择。
所有原样配方与 blob / SHA-256 见 [fixture 记录](../tests/fixtures/kconfig-compat/sources.json)。

新增回归通过真实 `luci.mk`、fwknop、gnupg2、gpgme 配方生成元数据，使用两种配置求值器：
先重现原始三节点循环，再验证修复后父包未选择时选项及库保持未选中；父包选为 y / m 时，
可选 GPG、NFQ 捕获及 libpcap 切换仍保留；四个锁定分支的 GnuPG2 工具包会携带同级 y / m 运行时。
同时检查重复运行不重写、未知/缺失配方在任何写入前被拒绝。测试不代表 fwknop 目标架构编译或设备运行验证。
