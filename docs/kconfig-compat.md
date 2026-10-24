# Qt5 与 squeezelite 循环依赖兼容

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
