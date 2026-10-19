# 第三方来源与分发记录

本项目自有源码使用 GPL-2.0，正文见根目录 `LICENSE`。第三方文件保留各自许可，
根目录许可不替代依赖、Android 系统或工具链的许可。

## 客体用户空间与输入法

- reDroid ARM64 Android 10 的 OCI manifest、layer digest 与文件系统工具见
  `guest-runtime/sources.lock.json`；当前产品使用用户空间文件与配套运行库。
- MIUI12 使用的指定 ROM 和提取记录见 [MIUI 启动记录](MIUI12_BOOT_TRIAL.md)。
- 内置 Android 10 AOSP LatinIME，与对应 ARM64 原生库配套，保留 APK 原始签名。
  版本、摘要、源码地址及上游 NOTICE 见
  [输入法说明](../guest-runtime/keyboard/NOTICE.md)。
- Android framework、Bionic、图形与其他组件继续保留其各自版权和许可。

## Android 10 静态自举探针

- Bionic、system/core、libc++、libc++abi 固定于 `android-10.0.0_r47`；精确提交及
  子树见 `container-probe/runtime/archives.txt`，编译输入内容摘要见 `sources.sha256`。
- Bionic 与其导入的 BSD 源码、system/core 头文件保留各文件的版权及许可。
- libc++ / libc++abi 使用该固定版本的 MIT / University of Illinois 双重许可；
  真实线程析构入口来自 `external/libcxxabi/src/cxa_thread_atexit.cpp`。
- 源码原件保存在 `artifacts/container/runtime/upstream/`，派生补丁、TLS 链接布局和
  构建脚本随工程保存。此静态程序直接包含相应源码实现；配套 linker / 动态 libc
  的构建与来源另外验收。

## Android 10 动态及配套运行库探针

- 配套 linker、libc/libdl、jemalloc 和 zlib 的固定输入见
  `container-probe/runtime/dynamic/` 的 `archives.txt`、`sources.sha256` 和
  `libc-sources.sha256`；复用同版静态自举及属性原件，各文件许可保持原样。
- libm 使用固定 Bionic 提交 `290c0cb5044b643e5d6cbcb1a5b275541ca3a89e`，
  其中导入的 BSD/FreeBSD/OpenBSD 数学源保留各文件版权和许可。
  `k_sincosl.h` 的单行修正只作用于派生副本，补丁随工程保存。
- ARM 数学优化例程来自 `arm-optimized-routines` 提交
  `2b1324f72857be13c6096a3bfba9e4265d26c8e6`，使用 MIT 许可。
- libc++ / libc++abi 分别固定到 `d356ee1683aa5681564c81ad69fe19bc6abd5da5` /
  `b599c4d59ebf8d589c82a1d5fd98a6c0a955fe7b`；该版本的 MIT / University of
  Illinois 双重许可文本保留在上游 `LICENSE.TXT` / `NOTICE` 文件中。
- libunwind_llvm 固定到 `c84e52d2279c3ba0017511b64515ea56c18e327d`，
  `LICENSE.TXT` 为 Apache 2.0 with LLVM Exceptions，`NOTICE` 还保留旧版
  MIT / University of Illinois 双重许可文本。两份实际文件均保留，不合并成
  单一许可描述。此探针将同版源码适配为独立 AArch64 DWARF 展开库。
- 上游原件继续保存在 `artifacts/container/runtime/upstream/`；新增固定来源、
  566 条编译/构建输入摘要及最小补丁见 `container-probe/runtime/companion/`。
  APK 为私有开发探针，完整产品分发材料仍按各组件的实际许可整理。
