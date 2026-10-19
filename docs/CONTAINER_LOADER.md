# G1 stage-0：直接使用 Android 10 linker 装载受控 ELF

查阅日期：2026-10-06。源码固定为 AOSP Android 10 Bionic 提交
`290c0cb5044b643e5d6cbcb1a5b275541ca3a89e`。本文件记录只读源码调查与实现依据，
未下载完整源码树。随后的小 APK 实测及验收结果见
[`container-probe/README.md`](../container-probe/README.md)，与下文的研究模板分开记录。

## 1. 确定的入口与参数

**可以直接调用，但参数不是 glibc 的 `ld.so` 参数集。** [L1][L2]

```text
linker64 /absolute/path/program [arguments...]
linker64 /absolute/path/archive.zip!/program [arguments...]
linker64 --help
```

- `linker_main.cpp:655–677` 以 `AT_ENTRY == &_start` 识别直接执行模式。
  `argv[1]` 是目标路径，`initial_linker_arg_count=1`；构造器和 C `main()`
  看见去掉 linker 参数后的 argc/argv。[L1][L3]
- `load_executable():263–292` 要求目标使用**绝对路径**，自行 `open`、
  `ElfReader::Read/Load`，取得目标 PHDR 和入口；目标应为 AArch64 PIE/ET_DYN。
- 本版本只专门处理无参数和 `--help`；`--list`、`--library-path` 不是选项，
  传入会被当成程序路径。库路径应设置环境变量 `LD_LIBRARY_PATH`。
- ZIP 模式要求目标条目未压缩且页对齐；为减少首个测试的打包变量，stage-0
  先用真实文件。官方 `tests/dl_test.cpp:100–127` 已覆盖直接文件与 ZIP 两种
  调用语义，但不代表本机/本次镜像已经运行通过。[L2]

## 2. auxv 与真实装载身份

**源码事实：**直接模式内核首先执行的是 linker。`AT_BASE=0` 时 linker 用
`AT_PHDR/AT_PHNUM` 计算自己的基址；之后用独立 `ExecutableInfo` 保存所装载
目标的 PHDR、PHNUM 和 entry。ARM64 入口最终跳到这个目标 entry。[L1][L4]

该路径没有把原始 auxv 改写成目标程序的内容。Bionic 保存 `args.auxv`，
`getauxval()` 仍从这份表读取。因此应预期：[L5][L6]

| 值 | stage-0 中的含义 |
| --- | --- |
| `main(argc, argv)` / `getprogname()` | 调整后的目标程序参数 |
| `AT_EXECFN`、`AT_PHDR`、`AT_ENTRY` | 保留内核执行 linker 时的记录，不当成目标 ELF 身份证明 |
| `/proc/self/exe` | 内核执行文件，即 APK 内安装的 linker 文件 |
| `dl_iterate_phdr()` / `dladdr()` | 用户空间动态装载视图，用于核对 probe 和客体库 |

还有一个易误判点：`kLinkerPath` 在此版本固定为 `/system/bin/linker64`，
link_map 会使用该名字。因此一个名为 `/system/bin/linker64` 的枚举项可能是
**当前客体 linker 的合成标签**。应按地址范围关联 `/proc/self/maps` 与实际
安装文件 SHA，而非仅按名字判定混入宿主。未来目标若依赖 auxv/`/proc` 身份，
需要单独的语义适配；本阶段不通过改日志或伪造返回值掩盖差异。[L1]

## 3. LD_LIBRARY_PATH、namespace 与 APEX

`AT_SECURE=0` 时 linker 才读取 `LD_LIBRARY_PATH`、`LD_PRELOAD`。库名无 `/`
时先查 LD 路径，再查 namespace 默认路径；带 `/` 的依赖按路径打开。
所以 **LD_LIBRARY_PATH 是优先搜索路径，不是完整隔离策略**。[L1][L7]

默认配置选择会检查 APEX、`/system/etc/ld.config.arm64.txt`、VNDK 配置及
`/system/etc/ld.config.txt`；未取得配置时默认库路径仍可能指向宿主 `/system`
等目录。把客体目录放到应用私有路径并不会自动改变这些绝对位置。[L7]

### stage-0 的闭集配置

本版本提供 `LD_CONFIG_FILE`，但受编译宏 **`USE_LD_CONFIG_FILE`** 控制。
`linker/Android.bp:197–200` 只在平台 `product_variables.debuggable` 下打开它。
这取决于该 linker 的构建，不取决于测试 APK 的 `debuggable=true`。[L7][L8]

**已锁定工件的静态证据：**本次只读检查
`artifacts/container/gate-0-repeatable/bootstrap-linker64`，SHA-256 为
`802a1aaa864490a465fa67e0dcdd014e0468db7745c13f502ced515bdffcfa3f`：

- `LD_CONFIG_FILE` 字符串的文件偏移/ELF VA 均为 `0xb1d2`。
- `init_default_namespaces` 位于 `0x40510`；`0x405a4`/`0x405ac` 组合出
  `0xb1d2`，`0x405bc` 调用 `__dl_getenv`，随后 `0x405cc` 调用 `stat64` 并
  检查文件类型，成功路径采用该环境变量值。

因此当前工件**含有该编译路径**，不只是 strings 命中或目录名含 `debug`。
实际解析/装载还需配置正负测。该 linker 可作为临时试验材料；配置模板如下，
占位值由应用替换为真实绝对路径：[L9][L10]

```ini
dir.stage0 = PROBE_DIRECTORY
[stage0]
namespace.default.isolated = true
namespace.default.search.paths = GUEST_LIB_DIRECTORY
namespace.default.permitted.paths = GUEST_LIB_DIRECTORY
```

这里不配置宿主库目录、额外 namespace 链接或宿主 APEX。配置文件须存在且
可读，`dir.stage0` 要匹配目标 ELF 的实际路径；缺文件/解析失败仍可能走默认
配置，故“无宿主库回退”以负测为准。更换 linker 工件时重新核验此能力；
后续采用源码构建、固定私有配置的 linker，不靠旧 target SDK 补齐条件。

**隐式依赖也要核对：**Android 10 libc 构造器调用 `netdClientInit()`，会尝试
`dlopen("libnetd_client.so")`；库不存在时可继续使用默认实现。若 namespace
回退到宿主，简单的 `printf` 测试也可能夹带宿主库，还需检查 DT_NEEDED 之外
的动态装载。[L11]

## 4. 最小可构建原型

建议先做小型独立 smoke APK：纯 Java 启动器 + 独立子进程，保持普通应用 UID。
只复用现有锁定镜像中的 **一份 linker64、libc.so、libdl.so、libm.so**，另加
源码编译的 probe；不要再次复制完整磁盘或两份相同 linker。所有提取件保留
SHA、来源路径、ELF 依赖，递归检查后若有额外依赖再按需加入。

- 将 linker/probe 分别作为 `liba10_linker.so`、`liba10_probe.so` 打入
  `jniLibs/arm64-v8a`；测试包令原生库提取到 `nativeLibraryDir`，不对它们调用
  `System.loadLibrary()`。子进程通过完整路径执行 linker。
- 客体三库保留 `libc.so`、`libdl.so`、`libm.so` 文件名以匹配 DT_NEEDED；
  路径中出现新别名而依赖名未变，仍会导致搜索回退。测试包与生产包分开，
  独立验证通过后再调整生产依赖目录。
- probe 使用 Android API 29 的 C 工具链、PIE、仅基本 libc/libdl/libm API。
  首轮避开 ART、Binder、网络和系统服务。源码构建模板如下；编译器路径应先
  核对目标/sysroot，Termux 默认 clang 的宿主 API 不自动等于 Android 29。

```sh
"$ANDROID29_CC" -fPIE -pie -fno-builtin \
  -Wl,--pack-dyn-relocs=none -Wl,--no-as-needed \
  probe.c -ldl -lm -o "$OUT/liba10_probe.so"
```

由 APK 的 `ProcessBuilder` 设置干净环境并启动；等价的命令参数为：

```sh
env -u LD_PRELOAD \
  LD_LIBRARY_PATH="$GUEST_LIB_DIRECTORY" \
  LD_CONFIG_FILE="$APP_PRIVATE_DIRECTORY/ld.stage0.config.txt" \
  "$NATIVE_LIBRARY_DIR/liba10_linker.so" \
  "$NATIVE_LIBRARY_DIR/liba10_probe.so" stage0
```

这是待执行模板，不是运行结果。其 `LD_*` 参数来自源码条件；主程序路径及
`stage0` 来自直接调用的 argv 语义。子进程设置时间上限并回收 stdout、stderr、
退出码，不启动 init，也不触碰当前 A10VM 实例。

## 5. 首轮验收：证明装载了什么

1. **离线闭包：**probe 为 AArch64 PIE；核对 DT_NEEDED、符号版本与 API；
   成套库的来源 SHA 匹配锁定材料，避免将 NDK stub 当成运行库。
2. **正测：**打印 PID/UID/GID、argv、AT_SECURE、页大小；分别调用 libc、libm、
   libdl 功能，再用 `dladdr()`、`dl_iterate_phdr()`、`/proc/self/maps` 记录库的
   实际范围/路径。宿主进程按路径/哈希核验，允许 vDSO 等内核映射并单独解释
   linker 合成标签；出现其他宿主库时标为混合结果。
3. **缺库负测：**新建小型测试目录，仅复制候选三库，先确认全套正测通过，
   再在该测试目录中移走 probe 必需的 `libm.so`；LD 路径和配置同时指向它。
   预期链接报错而非从宿主补库。保持安装目录和原件完整，只增少量测试副本。
4. **身份边界：**`ro.build.version.sdk` 等属性可能仍来自宿主。即使 ELF/库
   确属 Android 10，也不据属性读取宣称私有属性空间已完成。

通过标准是“受控 ELF 在普通 APK 子进程中使用锁定客体库执行，且库回退负测
成立”。一次 exit=0 或一句 hello 不足以通过；Termux 中的结果只算前置诊断。

## 6. 仍未覆盖的 G1 工作

| 项目 | stage-0 的边界 |
| --- | --- |
| 源码构建 | probe 可自行构建；预编译 linker/三库只是临时引导材料，仍需固定 AOSP/reDroid 补丁和可复现 Bionic 构建 |
| 私有属性 | 原 linker 在库装载前就初始化属性，libc 也有初始化；需适配两端而非只修改一个环境变量 |
| 绝对路径/APEX | 私有 namespace 控制库查找，不是 `/system`、`/data`、`/apex`、`/proc` 的通用路径重定向 |
| auxv/进程身份 | 上述直接模式保持内核的 linker 身份，需要依目标接口再做一致性设计 |
| 宿主适配 | APK 执行/映射条件、4 KB/16 KB 页与不同宿主版本仍待实测；当前旧 linker 的成功不扩展为所有 Android 11+ 手机兼容 |

## 固定源码来源

以下均固定到同一 Android 10 Bionic 提交，行号以原文件为准。

- **L1**：[linker_main.cpp：装载入口、环境和 argv](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/linker_main.cpp)
- **L2**：[dl_test.cpp：官方直接执行测试](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/tests/dl_test.cpp)
- **L3**：[libc_init_dynamic.cpp：main 参数调整](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/bionic/libc_init_dynamic.cpp)
- **L4**：[ARM64 begin.S：入口跳转](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/arch/arm64/begin.S)
- **L5**：[__libc_init_main_thread.cpp：保存 auxv](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/bionic/__libc_init_main_thread.cpp)
- **L6**：[getauxval.cpp](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/bionic/getauxval.cpp)
- **L7**：[linker.cpp：搜索与配置选择](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/linker.cpp)
- **L8**：[linker/Android.bp：构建及配置开关](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/Android.bp)
- **L9**：[linker_config.cpp：dir/section/namespace 语法](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/linker_config.cpp)
- **L10**：[linker_namespaces.cpp：路径可访问条件](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/linker/linker_namespaces.cpp)
- **L11**：[NetdClient.cpp：隐式动态库装载](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/bionic/NetdClient.cpp)

工具简报：限定 curl 读取官方固定源码；未调用外部 MCP；只新增本文件。
