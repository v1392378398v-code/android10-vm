# P2：Android 10 配套数学与 C++ 运行库

本模块从固定 Android 10 源码构建 `libm.so`、`libc++.so` 和 `libunwind.so`，
接到已有的源码 linker、动态 Bionic 与私有属性区。2026-10-07，本地与普通 APK
UID 实测两轮各通过 39 个独立检查；另外验证未捕获异常、`noexcept` 和三个缺库
场景。精简记录见[配套运行库证据](../../../docs/evidence/container-runtime-companion.json)。完整 G1/P2、
Binder/HwBinder、ART 与真实 Android 10 桌面仍有独立验收关卡。

## 构建与复现

在仓库根目录执行：

```sh
sh container-probe/runtime/companion/prepare-apk.sh \
  artifacts/guest/android10-display-v4.raw \
  artifacts/container/gate-0-repeatable/report.json
python3 container-probe/runtime/companion/test-native.py
sh tools/build-termux.sh -PcontainerProbe -PcontainerCompanion \
  :container-probe:assembleDebug :container-probe:lintDebug --offline
sh container-probe/test-device.sh --local-root --companion
python3 container-probe/test-cleanup.py
```

设备脚本也支持 ADB：去掉 `--local-root`。Root 仅供开发安装、Instrumentation
调度和报告回收；受测程序由普通 APK 直接启动。`--companion` 同时覆盖已有
G1 装载、独立属性、属性 API、静态自举与动态 Bionic 场景。

单独构建可依次执行 `build-libraries.sh`、`build-probes.sh`、`test-native.py`。
源码基线变更时以 `build-libraries.sh --record` 生成输入清单；正常构建核验清单。
复用既有镜像、源码缓存和按命令、编译器、依赖内容及对象内容校验的对象缓存。
所有新中间件保存在 Termux 私有目录中的 `artifacts/container/runtime/`。

## 固定来源与构建差异

基线为 `android-10.0.0_r47`：

| 仓库 | 固定提交 | 选定源码数 |
| --- | --- | --- |
| Bionic libm | `290c0cb5044b643e5d6cbcb1a5b275541ca3a89e` | 210 |
| arm-optimized-routines | `2b1324f72857be13c6096a3bfba9e4265d26c8e6` | 24 |
| libc++ | `d356ee1683aa5681564c81ad69fe19bc6abd5da5` | 30 |
| libc++abi | `b599c4d59ebf8d589c82a1d5fd98a6c0a955fe7b` | 19 |
| libunwind_llvm | `c84e52d2279c3ba0017511b64515ea56c18e327d` | 7 |

[sources.sha256](sources.sha256) 包含 566 条记录：559 条真实编译依赖与
7 条 Blueprint/版本脚本输入。原件保持不变，派生文件的依赖记录映射回原件；
[platform.patch](platform.patch) 单独计入打包组件摘要。编译器及 compiler-rt
builtins 的身份也保存在构建目录。

两处适配必须与原版区分：

- **AArch64 展开器。** 原版 Soong 只在 ARM32 启用 LLVM unwinder。本工程
  从同版 `libunwind_llvm` 源码构建独立 AArch64 DWARF `libunwind.so`，采用
  `_LIBUNWIND_IS_NATIVE_ONLY`，保留 libc++/libc++abi 的异常和 RTTI；libc++abi
  使用上游 ARM64 的非 ARM EHABI 配置。跨库异常与回溯的运行结果单独验证。
- **binary128 `sincosl` 修正。** 上游 `k_sincosl.h:123` 在 `iy != 0` 分支把
  sine 结果误写到 `*cs`，后面的 cosine 计算再覆盖它。仅将该行改为 `*sn`。
  派生 `s_sincosl.c` 与头放在同一目录，编译依赖明确引用派生头；上游
  原件不变。修正前直接回归失败，`(1+2i)^2` 的误差为 `2`；修正后误差为
  `3.85185988877447170611195588516985464e-34`，门槛保持 `1e-31L`。

`libc++.so` 包含真实 libc++ 和 libc++abi，`_LIBCPP_VERSION=8000`。各 ELF
直接由 `ld.lld` 链接，并显式列出私有依赖，避免编译驱动注入宿主运行库。

## 模块与已验证行为

- `select-sources.py`：从固定 Blueprint 选择 ARM64 源码、C/C++ 参数与头路径，
  复用动态 Bionic 的解析器；不按宿主源码目录猜测编译集合。
- `prepare-sources.sh` / `platform.patch`：仅准备两个数学派生文件并应用最小修正。
- `compile.sh` / `build-libraries.sh`：编译、链接及来源清单；增量缓存复用动态模块。
- `test/MathProbe.cpp` / `ComplexProbe.c`：double/float/binary128、复数、舍入与
  浮点异常；直接 `sincosl` 回归覆盖 13 个输入，包括四象限、负值及大参数。
- `test/CxxProbe.cpp`：容器、字符串、iostream/classic locale、regex、智能指针、
  静态构造、跨库 RTTI、`call_once` 重试、future 异常和四个并发工作线程。
- `test/ExceptionProbe.cpp` / `ExceptionModule.cpp`：跨库异常、RAII、回调、
  `exception_ptr`、嵌套异常、静态初始化失败重试；四次 thread-local 析构。
- `test/LoadingProbe.cpp` / `LateModule.cpp`：两轮 dlopen/throw/dlclose，fini
  各执行一次，最终实际映射消失；检查代码与已卸载对象的生命周期分离。
- `test/UnwindProbe.cpp`：真实 `_Unwind_Backtrace`，并以 `dladdr` 核对回溯帧
  和私有展开器身份。本地取得 6 帧，6 帧均有所属映射。
- Java `CompanionRuntimeProbe`：输入摘要、进程身份、完整检查集合及实际映射；
  与动态 Bionic 共用 `RuntimeConfiguration` 和既有属性映射核验。

| 场景 | 验收结果 |
| --- | --- |
| 正常运行两轮 | 私有 SDK 29、39 项检查、构造/析构与线程正常；8 个文件型可执行映射均来自私有输入 |
| 未捕获异常 / `noexcept` | 真实 terminate handler 执行，退出码 86 |
| 缺 libm / libc++ / libunwind | 装载器在 main 前报告对应缺库并以 1 退出 |

正常场景另有三个私有属性文件各两份只读共享映射；不读取宿主属性目录。
两轮动态库卸载完成后再收集最终映射，避免把已卸载模块误判为仍驻留。

设备接入还修正了两处测试问题：Java 按字段读取工作线程、TLS 析构和晚加载轮数，
保留中间检查日志；属性跨进程测试在 writer 的 `set()` 返回后再取 global serial，
通过显式握手区分 property wake 和随后 global serial 更新。失败设备报告保留在
`artifacts/container/runtime/companion/device-regression-before.json`。属性真实路径与
路径别名本地回归各通过 48 项检查；新增两项核验握手完成。

设备为宿主 SDK 36 / ARM64 / 4 KB 页，APK min SDK 30 / target SDK 35。
受测 UID/euid 为 10748，`CapEff=0000000000000000`，SELinux 域为
`u:r:untrusted_app:s0:c236,c258,c512,c768`。同轮 G1 正负测、48 项独立属性检查、
5 个属性 API 场景、4 个静态自举场景及动态运行库正负测均通过。
其他宿主版本与 16 KB 页设备仍待覆盖。

归档 APK 为 `artifacts/container/runtime/companion/probe.apk`，3,288,371 字节，
版本 `7 / p2-companion`，SHA-256 为
`722846428a36b7527aa6ab1df3d54b0be3fa2c85b14d1da8bc4c250343c1ce80`。
ZIP、v2 签名、16 KB zipalign、19 个原生文件的大小与摘要，以及五份输入清单和
设备报告的一致性均通过；Lint 为 0 errors / 8 warnings，安装清理回归为 8 项。
六个新增 ELF 的重复构建哈希一致。完整报告保存在
`artifacts/container/runtime/companion/device/report.json`。

## 后续工作与工程原则

时区、Unicode 及完整 locale 数据尚待接入；classic locale 验证只覆盖此次 C++
探针。平台 debuggerd、属性写服务、通用路径/exec/APEX、虚拟身份及宿主版本/
页大小覆盖继续推进。小程序耗时不计作桌面冷启动或点击性能。

私有 Binder API 子关卡已在[独立模块](../../binder/README.md)通过普通 APK UID
实测；完整 G2 仍未通过。下一步验证 HwBinder，再推进 ART、系统合成与真实桌面。

KISS / YAGNI：先构建当前闭包，复用镜像与缓存。DRY：复用 Blueprint、对象缓存、
私有配置和进程回收。SRP / SOLID：构建、数学、C++、展开与设备判定分别承担
明确职责；只修改本轮所需接口。
