# Kconfig 兼容回归的真实上游夹具

`sources.json` 为每个原样保留的文件记录仓库、源提交、路径、Git blob SHA-1、SHA-256 和许可证说明。源提交只用于复现测试及审查兼容转换，生产 feed 的来源和更新方式不变。

- 固件生成器及 `conf`：`VIKINGYFY/immortalwrt@3fd1e27a511851b41cf082b067b60099e8e026c4`。
- Qt5、Mesa：`openwrt/video@bea0fb29f9573ab4c9bd77a9a495127958992d53`。
- squeezelite、ffmpeg、libdrm、libx264：`immortalwrt/packages@72c7391fb2d04080afd0bfe919605749f81eb747`。

这些文件通过官方 GitHub Git/Contents API 与固定提交的 raw 文件获取。OpenWrt / package 配方头部标明 GPL v2；`packages/LICENSE` 保留原许可证文本。固件源文件的 SPDX 和 `immortalwrt/COPYING` 原样保留。Mesa 配方没有文件级许可证头；其 `PKG_LICENSE=BSD-3-Clause` 描述被构建的 Mesa，不能作为配方本身的授权声明。该差别也记录在清单中。

`tests/test_kconfig_compat.py` 用 GNU Make 执行真实包定义及其继承链，再通过原版 `package-defaults.mk`、`package-dumpinfo.mk` 和 `package-metadata.pl` 生成 Kconfig。编译器、安装和工具链初始化的 include 被置空，其余无关库作为独立叶子包。涉及循环的 Qt5、Mesa provider、libdrm 的 `video-support` 前置条件，以及 squeezelite、ffmpeg provider、libx264 的 `BUILD_PATENTED` 前置条件全部来自实际配方。测试同时施加仓库现有的 `<PACKAGE_$pkgname` 到 `!=y` 兼容转换，证明其无法独自解决这两个环。

Qt5 的路径是 `qt5base-gui` 条件选择 `libmesa`，默认 provider `libmesa-softpipe` 依赖 `libdrm`，后者依赖 `video-support`。生成器将 `!(BUILD_qt5base-gui_OPENGL_OPENGLES2 && provider 条件) || PACKAGE_video-support` 加回 GUI 包，GUI 下的 OpenGL choice 再依赖 GUI 包，闭合循环。squeezelite 的 WMA/ALAC 条件选择 ffmpeg，ffmpeg 的 libdrm / libx264 前置条件被同样传播，WMA/ALAC 开关原先又处于父包 `if` 内。

生产转换只删除 Qt5 OpenGL choice 的父包依赖，将 squeezelite 父包 `if` 改为无依赖的选项菜单。原默认值、条件库依赖、全部功能开关和编译参数不变。选项会在父包未选中时可见；测试确认单独打开选项不会自动选中父包或库。完整文件指纹确保新的上游改动必须重新审查，不能被宽泛替换静默接受。

Windows 用 `kconfiglib==14.1.0` 作解析及符号求值检查。真实 Linux 门禁为 `bash tests/test_kconfig_linux.sh`：在临时目录以 GCC/Make 编译夹具内的真实上游 `conf`，以 `--fatalrecursive --defconfig` 重跑同一组语义测试。需要 `gcc make perl python3`；上游生成的 lexer/parser 已保留，无需 Flex/Bison。`REQUIRE_KCONFIG_CONF=1` 时非 Linux 也必须失败，Linux 缺任何工具始终失败；普通 Windows 只明确跳过该 Linux 门禁。两种解析器仅因上游语法演进在测试前置 MODULES 声明上分别使用 `modules` / `option modules`。

这些测试覆盖 Kconfig 配置阶段，不代表 Qt5、Mesa、ffmpeg 或 squeezelite 已完成固件编译或设备运行验证。
