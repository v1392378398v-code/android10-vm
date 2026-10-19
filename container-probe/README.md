# Android 10 原生装载小探针

这是独立的 G1 stage-0 验证包，不是容器后端或桌面实现。默认构建不包含此模块；
显式传入 `-PcontainerProbe` 才加入。包名为 `io.a10vm.containerprobe`；默认 G1
构建禁用窗口 Activity，`-PcontainerGraphics` 启用 Surface 测试页。测试包没有
网络权限或对 `io.a10vm` 数据的访问。

## 验收对象

1. 从已审计的 v4 镜像只读提取 Android 10 linker、libc、libm、libdl，记录源镜像和
   每个 ELF 的 SHA-256、大小、DT_NEEDED；提取前后源镜像 SHA 一致。
2. 编译 API 29 / ARM64 PIE 小程序，通过 APK 安装的 `nativeLibraryDir` 执行。
   程序回传随机 nonce、UID、capabilities、SELinux 域、libc 身份和全部内存映射。
3. **客体正测：**私有 linker 配置只搜索客体库；Java 端校验安装后库哈希与执行映射，
   检查 libc/libm/libdl 调用、正常退出与 `dlopen("liblog.so")` 未装载宿主库。
4. **宿主对照：**同一程序直接执行，由宿主 linker 装载；检测器必须识别其库来源差异。
5. **缺库负测：**只删除测试目录中的 libc 符号链接，再调用客体 linker；应在链接阶段
   因 `libc.so` 缺失退出，而非从宿主补齐。
6. **身份判定负测：**对真实输出分别移除 SELinux 标签、替换为 `su` 域；复用同一
   判定函数，两种修改后的记录均应判失败。这是判定器测试，不是以该域运行程序。

安装库采用 `liba10vm-a10-*.so` 独立名称，私有目录通过符号链接保留依赖名。
没有复制第二套运行库。`ld-android.so` 是当前 linker 自身的 SONAME，已纳入闭包核对。
`LD_CONFIG_FILE` 的工件依据与直接调用语义见 [源码核对](../docs/CONTAINER_LOADER.md)。

## 构建与实测

在仓库根目录执行，使用现有 Termux clang 和 NDK sysroot：

```sh
sh container-probe/prepare.sh \
  artifacts/guest/android10-display-v4.raw \
  artifacts/container/gate-0-repeatable/report.json
sh tools/build-termux.sh -PcontainerProbe \
  :container-probe:assembleDebug :container-probe:lintDebug --offline

# 已连接开发设备时，默认用 ADB 安装、启动 Instrumentation、取回报告并卸载测试包。
sh container-probe/test-device.sh

# 本次开发手机使用此入口；Root 仅在开发安装、Instrumentation 调度和取报告时使用。
sh container-probe/test-device.sh --local-root
```

两个实测命令二选一。APK 内部没有 `su` 调用，受测程序始终由普通 APK UID 启动。
脚本可附加 APK 路径；默认读取本模块的 debug 输出。每个子进程最多等待 8 秒，
输出重定向到文件避免管道阻塞，超时终止并回收。安装前检查同名包，保留已有安装；
本轮安装尝试后的退出路径检查测试包并尝试卸载，查询或卸载失败保留日志并非零退出。
每次使用外部随机 nonce 核对报告，旧报告不计为本轮成功。

`python3 container-probe/test-cleanup.py` 使用临时假 ADB 验证安装已落地后超时、
未产生安装、同名旧包和卸载失败四种路径；不连接设备，结束后自动删除测试文件。

## 当前结果：2026-10-06

本机 **SDK 36、ARM64、4 KB 页** 实测通过，测试 APK target SDK 35 / min SDK 30：

| 项目 | 结果 |
| --- | --- |
| 受测 UID / capabilities | 普通 APK UID，`CapEff=0000000000000000` |
| SELinux 域 | `u:r:untrusted_app:s0:...` |
| 客体库来源 | 5 个文件型可执行映射均为已核对的 APK 原生文件；没有宿主 ELF 混入 |
| 正测 / 宿主对照 / 缺 libc | 全部符合预期；缺库退出码为 1 |
| 身份判定 | 校验 `untrusted_app` 系列域；缺标签和 `su` 域负测先红后绿 |
| 属性观察 | `visible_sdk=36`，仍看见宿主属性，不冒充客体 SDK 29 私有属性 |
| 工具验证 | APK v2 签名、ZIP 完整性及 5 个 ELF 哈希通过；Lint 0 errors / 4 warnings |
| 存储 | APK 约 1.24 MiB；准备材料约 3.0 MiB；没有新增整盘镜像 |

原始报告在 `artifacts/container/g1-stage0/report.json`，精简证据在
[`docs/evidence/container-g1-stage0.json`](../docs/evidence/container-g1-stage0.json)。
归档的小 APK 为 `artifacts/container/g1-stage0/probe.apk`，可作为实测脚本的最后一个参数。
时间字段只表示小 ELF 的一次进程调用，不是 Android 冷启动、桌面帧率或触摸延迟。
四项 Lint 提示为 target API、ChromeOS ABI、备份声明与测试包图标；没有为临时包增加 UI。

评审收尾：Standards 轴发现安装中断清理窗口，Spec 轴另发现身份标签判据缺口；
两项均以先红后绿的回归修复。安装清理 4 项、身份判定 2 项均通过，既有 31 项 JVM
及显示桥、端口取消、启动检查也通过。对应红/绿日志留在上述小型证据目录。

## 模块边界与后续

- `prepare.sh`：只读提取、输入闭包、native 编译；固定一个生成目录。
- `ProbeInstrumentation`：测试入口与结果归档。
- `LoaderProbe`：私有库目录、三个验收场景与来源判定。
- `ProbeProcess`：进程环境、时间上限、输出回收。
- `payload.c`：真实客体库调用与进程内观测。

KISS / YAGNI：只验证当前最早关卡，不引入后端管理框架、完整系统副本或新 UI。
SRP / DRY：提取、装载、进程生命周期各自独立；正负测复用相同启动与判定路径。

**完整 G1 仍未通过。** 当前 linker / Bionic 来自锁定镜像，不是本工程源码重建；
私有属性、绝对路径/APEX 适配尚未实现。私有 Binder、ART 与完整桌面也未实现；
图形预验证的后续结果见下节。
结果只覆盖本机；Android 11–15 与 16 KB 页设备需分别验证。

下一步先实现可复现的客体 loader / Bionic 构建与私有属性，再进入私有 Binder。
本轮已只保留一份小探针 APK，删除本模块 `build/`、JVM 构建输出和临时测试 class，
清理 **17.54 MiB**；本轮保留的 APK 与证据目录合计约 **1.4 MiB**。
后续按需重建，继续复用已有镜像；旧实验磁盘的待确认清理范围保持不变。

## 后续进展：P1a 图形离屏验证（2026-10-06）

依据后续的[两仪研究方案](../docs/TWOYI_ANDROID10_PLAN.md)，增加了独立
[图形探针](graphics/README.md)：Android 10 linker/Bionic 装载真实 `GL2Encoder`，
经配套生成的协议和私有 socket 交给宿主 GPU。普通 APK UID 实测通过 32 轮绘制、
64 次像素核对；既有 G1 正负测仍通过。结果见
[精简证据](../docs/evidence/container-graphics-p1a.json)。

这只是完整 G4 之前的小闭环；当时私有属性、Binder、Surface 和 Android 桌面仍待实现。
本次没有替换主 App 后端，离屏循环耗时也不作为开机或触摸性能。上述 G1 结果保留为
历史阶段记录；接下来按两仪方案的 P1/P2/P3 关卡推进，继续复用既有镜像。

## 后续进展：P1b 窗口与输入验证（2026-10-07）

普通 APK UID 下的 Android 10 编码客户端 → 宿主 GLES → Surface 路径已通过
60 秒/100 次输入长测。360×640、30 Hz 场景中，帧间隔 P95 为 34.83 ms，
输入到 Surface 采样 P95 为 76.26 ms；10 次 Activity/Surface 重建保持客体 PID
并恢复合成图像。停止协议完成、客体退出码为 0；G1/P1a 检查同轮通过。

复现命令、模块边界和测量口径见 [图形探针](graphics/README.md)，精简结果见
[P1b 清单](../docs/evidence/container-graphics-p1b.json)。安装清理回归现为 6 项；
本轮主工程 34 项 JVM 回归通过。图形候选 `artifacts/container/graphics/probe.apk`
约 1.98 MiB，不含 ROM；归档后清理可重建输出，原镜像与数据链保留。

P2 接着验证私有属性、源码运行时闭包和 Binder/HwBinder。P1b 的时间字段只覆盖
探针窗口；完整 Android 10 桌面的启动与点击性能仍待 P3 验收。

## 后续进展：P2 独立私有属性组件（2026-10-07）

[私有属性组件](properties/README.md)已通过普通 APK UID 实测，客体与宿主对照各
覆盖 46 个独立检查；本地真实路径及路径别名回归各通过相同 46 项。私有 SDK 29、
跨进程 property/global serial 与阻塞等待、只读映射、多实例隔离和映射释放通过。
设备上 `/data/user/0` 与 `/data/data` 名称差异由设备号/inode/权限判定解决。

精简结果见 [P2 属性清单](../docs/evidence/container-properties-p2.json)。归档 APK
`artifacts/container/properties/probe.apk` 约 1.51 MiB；ZIP、v2 签名和 7 个原生输入
与设备报告一致，Lint 0 errors / 8 warnings。源码及补丁只占小型组件范围。

新增真实 AOSP API archive 和同版 async-safe，静态初始化前读取、构造后状态保持、
失败重试、实例切换拒绝及写端共 5 个场景，在本地与设备的客体/宿主对照中通过。
API 对象保留平凡构造/析构，没有静态初始化段，组件用显式 Reset 释放映射。
API 目前只链接在独立 executable 内，客体 libc 的属性 API 对照仍返回宿主 SDK 36。
完整 G1/P2 未通过，接着推进同版 Bionic/linker 源码自举与成套属性接入，
然后是 Binder/HwBinder 和 P3 桌面。上面的 G1/P1 描述保留为历史阶段记录。

## 后续进展：P2 静态 Bionic 自举（2026-10-07）

[源码自举模块](runtime/README.md)已生成真实 Android 10 静态 Bionic executable。
普通 APK UID 下，`reader/missing/relative/incomplete` 四个场景全部通过：私有 SDK 29
从 preinit 起生效，真实 pthread、ELF TLS、errno、线程析构、fini 与 stdio 退出 flush
均有实际结果。可执行文件没有解释器、动态依赖和未解析强符号，执行映射仅为自身。

新增 `-PcontainerRuntime` 构建与 `--bootstrap` 实测入口，复用现有属性实例和进程
管理。389 个上游编译输入固定到同版提交并校验内容；重复构建哈希一致。
精简记录见[自举证据](../docs/evidence/container-runtime-bootstrap.json)，小 APK 归档为
`artifacts/container/runtime/probe.apk`。完整 linker / 动态 libc、Binder 与桌面继续推进；
这里的小程序耗时不计作 Android 冷启动或点击性能。

## 后续进展：P2 源码 linker 与动态 Bionic（2026-10-07）

[动态运行库模块](runtime/dynamic/README.md)已通过普通 APK UID 实测。源码 linker
无解释器、动态依赖和未解析符号；718 个选定的 shared-libc 源生成配套 libc，
使用真实 jemalloc。四种属性状态各通过 20 个独立检查，四种装载失败均在 main 前
结束；实际映射核验、共享 globals、并发分配、动态 TLS 和 DSO 卸载通过。

新增 `-PcontainerDynamic` 与 `--dynamic`，复用属性实例、静态探针和进程回收。
本轮 APK 约 2.40 MiB，13 个原生输入与设备报告完全一致，ZIP、v2 签名与 Lint
通过，安装清理回归为 7 项。APK 归档在 `artifacts/container/runtime/dynamic/probe.apk`；
精简记录见[动态证据](../docs/evidence/container-runtime-dynamic.json)。
早期 G1 工件继续作为镜像装载对照；完整路径/exec/APEX、Binder/HwBinder、ART 和
Android 10 桌面仍有后续关卡。本阶段结果不计作完整系统启动或点击性能。

## 后续进展：P2 数学与 C++ 配套运行库（2026-10-07）

[配套运行库模块](runtime/companion/README.md)已从固定 Android 10 源码构建
libm、libc++/libc++abi 和适配的 AArch64 LLVM 展开器。本地及普通 APK UID
两轮各通过 39 项检查：binary128/复数数学、C++ 容器与线程、跨库异常、RAII、
RTTI、动态卸载和回溯均有真实结果；两种 terminate 及三种缺库负测通过。

新增 `-PcontainerCompanion` / `--companion`，私有配置与动态探针共用。
修正上游 binary128 `sincosl` 的 sine 输出指针、Java 结果字段判定，以及属性
测试的 global serial 握手竞态；属性检查现为 48 项，运行库语义保持原有更新顺序。
设备仍为普通 APK UID、零 capabilities 和 `untrusted_app` 域；8 个文件型可执行
映射来自私有输入，三个属性文件各有两份只读映射。

APK 归档为 `artifacts/container/runtime/companion/probe.apk`，约 3.14 MiB。
19 个原生输入、五份报告清单、ZIP、v2 签名及 zipalign 核验通过；Lint 为
0 errors / 8 warnings，安装清理回归为 8 项。精简记录见
[配套运行库证据](../docs/evidence/container-runtime-companion.json)。
下一步进入私有 Binder/HwBinder 的服务注册、同步事务、嵌套回调、FD、死亡通知
和进程退出回收，再推进 ART 与完整 Android 10 桌面。

## 后续进展：P2 私有 Binder API（2026-10-07）

[Binder 模块](binder/README.md)通过普通 APK UID 完成源码 `libbinder` API 子关卡：
native 与设备端各通过 24 项 client checks；服务注册、嵌套回调、FD、oneway 顺序、
并发、死亡通知、资源回收及 broker 断开后的 looper 退出均通过。本机 SDK 36 / 4 KB
页，本轮设备 APK UID 为 `10764`；安装清理回归为 9 项。broker 使用应用内 Unix
socket 承载私有 transport，不代表内核 Binder 已完成。

APK 归档于 `artifacts/container/runtime/binder/probe.apk`，版本 `10 / p2-hidl-values`，
3,751,216 字节，SHA-256 为
`664f5e511bc6533b8c9986528ff9f83424045fb0abc5ce590baf34c9d2a3725a`；完整设备报告位于
`artifacts/container/runtime/binder/device/report.json`，精简记录见
[Binder 证据](../docs/evidence/container-runtime-binder.json)。

## 后续进展：P2 私有 HwBinder API（2026-10-07）

[HwBinder 模块](hwbinder/README.md)在同一普通 APK UID 下完成 Android 10
`libhwbinder` API 子关卡，native 与设备端各通过 16 项 client checks：context manager
发现、service lookup、同步 RPC、回调投递、嵌套回调、calling identity 恢复、嵌套 SG
缓冲、native_handle 双 FD、FD_ARRAY 生命周期，以及 HIDL 字符串向量、终止符校验和
共享内存修改。registry context、service registration、资源回收和 broker 断开后的
looper 正常退出均通过。
broker 同样使用应用内 Unix socket，不访问宿主 `/dev/hwbinder`；`completeG2` 仍为
`false`。

HwBinder 输入清单、设备报告和 native 报告分别归档在
`container-probe/build/prepared/assets/hwbinder-inputs.json`、
`artifacts/container/runtime/binder/device/report.json` 和
`artifacts/container/runtime/hwbinder/local-report.json`；精简记录见
[HwBinder 证据](../docs/evidence/container-runtime-hwbinder.json)。接下来推进 ART、
系统合成和完整 Android 10 桌面验收。
