# P2：Android 10 静态 Bionic 自举闭包

2026-10-07，本地和普通 APK UID 下的四个场景通过。真实 Android 10 Bionic
从 `_start` 建立主线程、ELF TLS、私有属性与构造器，再运行 pthread 并正常退出。
可执行文件没有解释器、动态依赖或未解析强符号；文件型可执行映射仅为自身。
这是原生容器运行时的基础关卡；配套源码 linker、动态 libc、Binder/HwBinder、
ART 和完整 Android 10 桌面继续推进，启动和点击性能尚待完整系统验收。

## 构建与复现

在仓库根目录执行：

```sh
sh container-probe/runtime/prepare-apk.sh \
  artifacts/guest/android10-display-v4.raw \
  artifacts/container/gate-0-repeatable/report.json
python3 container-probe/runtime/test-native.py
sh tools/build-termux.sh -PcontainerProbe -PcontainerRuntime \
  :container-probe:assembleDebug :container-probe:lintDebug --offline
sh container-probe/test-device.sh --local-root --bootstrap
```

最后一条也支持 ADB：去掉 `--local-root`。开发安装、Instrumentation 调度和报告
回收可经 Root，APK 内部直接启动程序，受测进程保持应用 UID、零 capabilities 和
`untrusted_app` 域。脚本最后卸载测试包；已有同名安装会保留。

只构建静态自举程序可执行 `sh container-probe/runtime/build-native.sh`。
更新固定源码基线时，`--record` 根据本次对象的编译依赖生成
[sources.sha256](sources.sha256)；正常构建核对该清单和独立属性组件的清单。
被补丁修改的输入记录对应上游原文件摘要，补丁另计入组件摘要。
Gitiles tar 的时间戳会变化，因此固定文件内容而非 tar 字节摘要。

源码来自 `android-10.0.0_r47`，只取 [archives.txt](archives.txt) 指定的小型子树：

| 仓库 | 固定提交 |
| --- | --- |
| Bionic | `290c0cb5044b643e5d6cbcb1a5b275541ca3a89e` |
| system/core | `1dea9a052b7f214c10a77d5ed6ffd3602722a817` |
| libc++ | `d356ee1683aa5681564c81ad69fe19bc6abd5da5` |
| libc++abi | `b599c4d59ebf8d589c82a1d5fd98a6c0a955fe7b` |

本轮使用 Termux clang 21.1.8，ARM64 / API 29 / 4 KB 页，389 个上游输入。
archive 包含 132 个对象；真实 CRT 与三个探针对象单独链接。编译器头来自其
resource directory，其余平台头和实现来自上述固定源码；静态程序直接发出 syscall。
没有链接宿主 libc、NDK 静态 libc 或空实现来填补依赖。

## 实现与已验证行为

- `BootstrapProbe.cpp`：实际 `.preinit_array`、constructor、main、fini 顺序；
  私有属性在真实 `__libc_init_common()` 中初始化，探针无需提前注入 `environ`。
- `ThreadProbe.cpp`：两次真实 `pthread_create/join`，独立 TID、ELF TLS、errno、
  pthread key，以及 pthread key / C++ `thread_local` 析构。
- `ProcessIdentity.cpp`：进程身份、capabilities、SELinux 与实际映射。
- Java `BootstrapProbe`：复用属性实例、`ProbeProcess` 和输入哈希校验，核对四个
  场景的结果与映射；异常场景结束后没有其他文件映射。
- `properties/prepare-sources.sh`：公共源码准备与补丁路径由属性构建和本模块复用。

| 场景 | SDK 与映射 | 独立检查数 |
| --- | --- | --- |
| `reader` | preinit / constructor / main 均为 29；3 个私有 `r--s` 映射 | 12 |
| `missing` | SDK 为空；没有属性文件映射 | 11 |
| `relative` | SDK 为空；没有属性文件映射 | 11 |
| `incomplete` | SDK 为空；失败初始化释放映射 | 11 |

每个场景均核对线程隔离与两类析构各执行两次，`fini_complete=1` 后由真实 Bionic
退出清理写出缓冲中的 `stdio_flush_complete=1`。既有装载正负测、46 项独立属性检查、
5 个属性 API 场景在同轮设备测试中通过。设备宿主 SDK 36、target SDK 35、4 KB 页；
尚未覆盖其他宿主版本和 16 KB 页设备。

可执行文件约 113.5 KiB，archive 约 504.6 KiB；二次构建两者哈希一致。
本轮 APK 约 1.56 MiB，包含 8 个小型原生输入。ZIP、v2 签名、打包输入哈希、
Lint（0 errors / 8 warnings）及安装清理的 6 项回归通过。
归档 APK 为 `artifacts/container/runtime/probe.apk`，原始报告为
`artifacts/container/runtime/device/report.json`，精简记录见
[自举证据](../../docs/evidence/container-runtime-bootstrap.json)。
`elapsedMs` 是单个小程序调用耗时，包含 Java 进程等待；不作为桌面冷启动指标。

## 解决的问题与下一步

ARM64 使用真实 `syscalls/mmap.S`，排除 LP32 的 `bionic/mmap.cpp`。
`-fno-sized-deallocation` 匹配同版 libstdc++；`-fno-emulated-tls` 保证验证 ELF TLS。
首次运行发现 TLS 段对齐只有 4 字节；[arm64-tls.ld](arm64-tls.ld) 将其提高到
Bionic 要求的 64 字节，检查保留在本地测试中。

[platform.patch](platform.patch) 仅将 systrace 的整数/字符串格式化接到同版真实
async-safe formatter，保留 tracing 调用路径。属性适配复用已有补丁；其原件与镜像
保持不变。两个未解析弱符号是静态程序可缺省的 loader 线程析构引用维护入口，
源代码中的空指针检查保留。

目前采用同版 **linker allocator**，测试用 gate 串行化其使用；线程/TLS 通过不代表
通用 libc allocator 的并发能力已经通过。静态 archive 是此次程序所需的真实闭包，
完整 libc / libc++、动态加载、完整产品属性服务仍有独立关卡。

KISS / YAGNI：以可运行的小闭包验证当前 ABI，继续复用现有镜像和用户数据。
DRY / SRP：源码准备、构建、初始化、线程、身份、设备判定各自承担明确职责。
下一步构建配套源码 linker / 动态 libc，验证共享 globals、动态 TLS 和属性接入，
然后推进私有 Binder/HwBinder、系统合成和桌面。

## 后续进展：源码 linker / 动态 libc（2026-10-07）

[动态模块](dynamic/README.md)已从同版源码生成 linker、libc 和 libdl。本地及普通
APK UID 实测通过四种属性状态和四种装载失败场景；共享 globals、4 线程并发分配、
已有线程的动态 TLS、析构引用保留与 DSO 卸载、退出 flush 均通过。
静态与动态探针共用映射校验；动态 reader 的三个属性文件各映射两份。

动态 preinit 位于 libc constructor 之前，SDK 在 constructor/main 为 29；上文的
静态初始化顺序与串行 allocator 限定保留为静态工件记录。新模块采用真实 jemalloc。
复现使用 `-PcontainerDynamic` / `--dynamic`，同轮保留静态与属性回归。
证据见[动态运行库清单](../../docs/evidence/container-runtime-dynamic.json)。
完整路径/exec/APEX、配套运行库、Binder/HwBinder、ART 与桌面仍待完成。

## 后续进展：数学、C++ 与异常展开（2026-10-07）

[配套模块](companion/README.md)已接入源码 linker、动态 Bionic 和私有属性。
本地及普通 APK UID 两轮各通过 39 项数学/C++/跨库异常检查，另有两种异常终止
与三种缺库负测。libm、libc++/libc++abi 和 AArch64 LLVM 展开器的来源、适配及
binary128 `sincosl` 最小修正分别记录；六个新增 ELF 的重复构建哈希一致。
静态自举继续作为独立回归保留，属性握手测试修正后为 48 项。

复现入口为 `-PcontainerCompanion` / `--companion`，证据见
[配套运行库清单](../../docs/evidence/container-runtime-companion.json)。
私有 Binder API 子关卡现已通过，源码、socket transport、24 项本地及设备检查见
[Binder 模块](../binder/README.md)和[精简证据](../../docs/evidence/container-runtime-binder.json)。
下一步验证 HwBinder；完整产品的路径、身份、ART 和桌面验收继续推进，完整 G2
仍未通过。
