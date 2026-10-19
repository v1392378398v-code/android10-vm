# Android 10 loader/Bionic：源码构建边界与 P2 属性进展

日期：2026-10-06。本文收束已完成的源码读取和本地静态检查，不代表源码
loader 已构建或完整容器已运行。本文记录早期源码研究的暂停点；最新优先级
以 [两仪方案](TWOYI_ANDROID10_PLAN.md) 为准。2026-10-07 的 P1b 窗口探针已通过，
P2 独立私有属性组件也已通过，本地与普通 APK UID 设备测试各覆盖 46 个独立检查，
详见 [组件说明](../container-probe/properties/README.md) 与
[证据](evidence/container-properties-p2.json)。同版属性 API 和真实 async-safe 已编译成
archive，新增静态构造之前初始化与失败重试的 5 个场景通过；这些 API 目前只链接在
独立测试文件内。新增[同版静态 Bionic 自举闭包](../container-probe/runtime/README.md)
已成功链接并通过本地和普通 APK UID 的四个场景：真实 CRT 初始化、ELF TLS、
pthread、析构、退出 flush 与私有 SDK 29 均通过，且仅映射自身可执行文件。
后续[配套源码 linker / 动态 libc](../container-probe/runtime/dynamic/README.md)也已
构建并通过本地及普通 APK UID 的四种属性状态和四种装载失败场景。共享 globals、
并发分配、动态 TLS 与 DSO 卸载通过；精简记录见
[动态运行库证据](evidence/container-runtime-dynamic.json)。新增
[数学与 C++ 配套模块](../container-probe/runtime/companion/README.md)也已通过本地和
普通 APK UID 两轮各 39 项检查：跨库异常、RAII、RTTI、线程/TLS 析构、动态卸载
与展开回溯均通过，异常终止和缺库负测单独验证。AArch64 LLVM 展开器适配及
binary128 `sincosl` 修正有独立记录；精简结果见
[配套运行库证据](evidence/container-runtime-companion.json)。属性测试握手修正后为
48 项。通用路径/exec/APEX、Binder/HwBinder 和完整产品运行时接着推进。

前置原型及运行证据见 [CONTAINER_LOADER.md](CONTAINER_LOADER.md) 和
[container-probe/README.md](../container-probe/README.md)。

## 1. 结论

- Android 10 linker 是带自举运行时的 ELF 装载器，不是普通 NDK 共享库。
  从源码构建时，应把同版 linker、私有 libc/TLS 和动态 libc 视为一个一致性
  单元；只替换 loader 文件、继续混用其他版本私有运行时，缺少兼容依据。
- 现有 NDK r29 的 `libc.a` 与已验证 Android 10 工件存在实际对象布局差异。
  `--target=aarch64-linux-android29` 选择 API 层级，不会把这份静态库转换成
  Android 10 平台私有 ABI。
- 恢复本路线时，独立属性共享区是较小的可测切口，但它与完整 loader/Bionic
  重建分开验收，也不等同于 Android 10 桌面或快速启动已经实现。

## 2. 已核实的源码闭包起点

源码基线为 `android-10.0.0_r47`，固定到：

| 仓库 | 提交 |
| --- | --- |
| `platform/bionic` | `290c0cb5044b643e5d6cbcb1a5b275541ca3a89e` |
| `platform/system/core` | `1dea9a052b7f214c10a77d5ed6ffd3602722a817` |

这两个提交用于解释构建接口；不声称它们逐字节对应现有 reDroid 工件。

### 自举与 libc

`linker/Android.bp:150–304` 明确规定：[S1]

- 静态依赖链接成共享对象，带 `-shared`、`-Bsymbolic`、
  `--exclude-libs,ALL`、`soname=ld-android.so`。
- `nocrt: true`，ARM64 使用自己的 `begin.S`、`tlsdesc_resolver.S`；
  关闭 stack protector，隐藏实现符号，链接后添加 `__dl_` 前缀。
- `stl: "none"`，手动链接 `libc++_static`，避免自动带入 `libdl`；
  `system_shared_libs: []`。
- 静态依赖为 `libc_nomalloc`、`libm`、`libziparchive`、`libutils`、
  `libbase`、`libz`、`libasync_safe`、`liblog`、`libc++_static`，最后放
  `liblinker_malloc`；Android 目标另加 `libdebuggerd_handler_fallback`。

`libc_nomalloc` 也不是 NDK `libc.a` 的别名：它以 `-DLIBC_STATIC`，
whole-static 链接 `libc_common_static` 和 `libc_init_static`。前者进一步包含
Bionic、pthread/TLS、syscall、BSD/DNS/时区等组件；文件还涉及
`generated_android_ids.h` 等生成输入。动态 `libc.so` 使用另一套初始化，
依赖 `ld-android`/`libdl` 并包含 jemalloc。[S2]

**关键私有边界：**`libc_shared_globals` 包含 `FdTable`、auxv、
`StaticTlsLayout`、`TlsModules`、`BionicAllocator` 等对象。[S3]
linker 在动态 libc 装载前初始化主线程/TLS；动态 libc 随后通过
`__loader_shared_globals()` 取共享对象，并登记 TLS generation 指针。
所以同名导出符号、成功链接或一个简单打印程序，都不足以单独验证这些布局
及初始化顺序一致。[S4][S5]

### 辅助依赖也需按实际链接闭包处理

| 模块 | 本轮核实的依赖/边界 |
| --- | --- |
| `libbase` | 包含文件、日志、属性、字符串等实现；构建依赖 `liblog`。[S6] |
| `libziparchive` | 包含 archive/stream/writer 实现，依赖 base/log/zlib。[S7] |
| `libutils` | 平台构建还声明 cutils/log/processgroup/dl/vndksupport；静态 archive 的实际抽取对象与最终链接图需在构建时核对，避免把所有平台服务都误列为运行依赖。[S8] |
| `liblog` | Android 源集合包含属性、logd、pmsg 路径；手机上的宿主 `liblog.so` 不是静态自举库的直接替身。[S9] |
| `libdebuggerd_handler_fallback` | whole-static 闭包继续带入 handler core、tombstoned client、base、async_safe、debuggerd、unwindstack、dexfile support、lzma、cutils，成本远大于一个错误输出函数。[S10] |
| libc++ / libc++abi / zlib / 编译器运行库 | 静态自举已锁定同版 libc++ 头和真实 `cxa_thread_atexit.cpp`；完整 C++/zlib 及 linker 的实际依赖仍按后续闭包构建。 |

若裁减 ZIP 装载或平台崩溃收集，应明确减少的产品能力、对应源码分支和测试。
单用空实现满足链接，会隐藏运行边界；本轮未进行这种裁剪。

## 3. 当前工具和 NDK 的实际证据

检查对象为本机 NDK `29.0.13113456`，路径前缀：

```text
$HOME/Android/Sdk/ndk/29.0.13113456/toolchains/llvm/prebuilt/linux-x86_64/
```

| 检查 | 结果及含义 |
| --- | --- |
| Termux `clang --version` | `21.1.8`，默认 target `aarch64-unknown-linux-android24`；普通 API 29 小组件需显式指定 target/sysroot。 |
| NDK `bin/clang` 文件头 | x86-64 ELF；本机 ARM64 的编译工具与 NDK 的 headers/库材料应分开选择。 |
| `sysroot/usr/lib/aarch64-linux-android/29/libc.so` | `__system_property_get`、`printf`、`pthread_create` 均仅为 `bti c; ret`；这是链接 stub，不是客体运行 libc。 |
| 同目录上一级的 `libc.a` | 含真实实现，并有 MTE、Scudo 初始化符号；API 29 子目录之外的此文件不是 Android 10 私有运行时快照。 |
| `libc++_static.a` | 定义 `std::__ndk1` 符号；混搭前须核对所有 C++ 对象的 headers、namespace、ABI 配置和初始化要求，本轮没有取得完整兼容证据。 |

进一步用 `llvm-readelf -sW`、`llvm-nm -A --defined-only --format=posix`
比对同名私有对象，得到明确的尺寸差异：

| 对象 | 已验证 Android 10 bootstrap linker | NDK r29 `libc.a` |
| --- | --- | --- |
| `__libc_shared_globals()` 的静态 `globals` | `1536` 字节（`0x600`） | `1752` 字节（`0x6d8`），`libc_init_static.o` |
| `main_thread` | `704` 字节（`0x2c0`） | `824` 字节（`0x338`），`__libc_init_main_thread.o` |

Android 10 对照工件：

```text
artifacts/container/gate-0-repeatable/bootstrap-linker64
sha256: 802a1aaa864490a465fa67e0dcdd014e0468db7745c13f502ced515bdffcfa3f
```

这些差异证明当前两组私有对象并非同一布局；本轮未测试任意混合组合，也未
逐字段恢复 NDK 布局。工程结论是保留同版自举闭包，而非凭同名符号宣称替换
兼容。公共 API 的独立组件仍可复用现有编译器、NDK 头文件及链接 stub，
其运行时身份另行验证。

## 4. 最小切口与当前进度

1. **独立属性组件。** AOSP `libsystemproperties` 的六个实现文件是
   `context_node.cpp`、`contexts_split.cpp`、`contexts_serialized.cpp`、
   `prop_area.cpp`、`prop_info.cpp`、`system_properties.cpp`，另需
   `libpropertyinfoparser` 与 async-safe 头；parser 仅一个实现文件，
   声明 `stl: "none"`、`system_shared_libs: []`。[S11][S12]
   这比完整 libc 自举小，但仍须显式适配文件路径、权限和上下文选择。
   以普通 APK 下真实读写、serial/wait、跨进程与多实例互不串读为验收。
   **独立组件已通过：**采用真实 `ContextsSerialized` 和 parser；私有 SDK 29、
   跨进程阻塞等待、只读映射与释放检查通过。路径别名按设备号/inode/权限核对。
   已用真实 AOSP async-safe 替换 stdio；组件析构通过显式 Reset 释放映射，
   API 的静态对象保留平凡构造/析构。新增的真实 API archive 在普通 APK UID 下
   通过 5 个场景，包括 `.preinit_array` 初始化后状态保持、失败重试和实例绑定。
2. **源码自举闭包。** 固定 ARM64、同版 Bionic 私有头和源码；为源文件、
   生成头、编译器版本和静态库列出可复现清单，再检查未定义符号、链接图、
   动态依赖与 TLS/构造器顺序。所有裁剪与平台原版差异都单独记录。
3. **成套接入。** 属性初始化同时覆盖 linker 自有静态 libc 与动态客体 libc。
   `LD_PRELOAD` 只拦截几个属性值，不作为这一步的完成标准。复用已有 stage-0
   的实际映射核验、缺库负测，再新增线程/TLS/动态装卸测试。

第 1 项已有独立组件工件和设备证据。第 2 项现已完成 132 对象的真实静态自举
archive、同版 CRT 和行为验证，固定 389 个上游编译输入；二次构建哈希一致，
详见[自举证据](evidence/container-runtime-bootstrap.json)。后续已完成源码 linker、
libdl 和 718 源的 shared-libc 构建；第 3 项的共享 globals、动态 TLS、装卸与私有
属性场景通过，通用路径/exec/APEX 和完整产品运行时仍待完成。此前属性切片的
28 个固定输入中包括只读的
`libc_init_common.cpp` 初始化顺序依据；独立属性 API archive 没有编译这个文件，
新增的静态自举 archive 已编译其真实实现。API 对象没有
`.init_array/.fini_array`，archive 没有 stdio/malloc/calloc/realloc 未定义依赖，
仍有 syscall/mmap/getenv、C++ delete 及编译器原子助手等依赖，见归档
`artifacts/container/properties/runtime-undefined.txt`。

私有属性区和 executable 内 API 的 SDK 29 不等同于客体 libc 已接入；
独立组件的客体 libc 对照 `__system_property_get()` 仍读宿主 SDK 36。
早期对照的 linker/Bionic 来自锁定镜像，新的动态探针使用配套源码运行库。
完整 G1/P2 尚未通过；P1b
[图形证据](evidence/container-graphics-p1b.json) 与属性证据分别验收。

## 来源

- [S1](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/Android.bp)：linker 构建规则。
- [S2](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/Android.bp)：libc 静态/动态子模块及生成输入。
- [S3](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/private/bionic_globals.h)：`libc_shared_globals:68–96`。
- [S4](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/bionic/__libc_init_main_thread.cpp)：早期 TLS 初始化与最终线程映射。
- [S5](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/bionic/libc_init_dynamic.cpp)：动态 libc 初始化及共享 globals 入口。
- [S6](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/base/Android.bp)：libbase。
- [S7](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/libziparchive/Android.bp)：ziparchive。
- [S8](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/libutils/Android.bp)：libutils。
- [S9](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/liblog/Android.bp)：liblog。
- [S10](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/debuggerd/Android.bp)：debuggerd fallback `102–131`。
- [S11](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/system_properties/Android.bp)：libsystemproperties。
- [S12](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/property_service/libpropertyinfoparser/Android.bp)：属性信息 parser。

工具简报：早期研究限定读取官方固定源码并检查已有工件和 NDK 库；本轮新增
独立属性组件、真实 API archive 构建、本地测试及普通 APK UID 实测。未调用外部 MCP；完整
源码 linker / 动态 libc 及数学/C++ 配套库已构建并通过小探针验收；静态自举、
独立属性、动态运行库和配套库结果分别归档。
