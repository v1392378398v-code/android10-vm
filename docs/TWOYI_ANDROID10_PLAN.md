# 两仪方案深挖：面向 Android 10 的原生容器路线

研究日期：2026-10-06；实现进展更新：2026-10-08。产品条件继续保持
**Android 11+ / ARM64 宿主、免 Root、安装 APK 即用、Android 10 用户空间、全屏**。
原静态研究没有安装两仪、运行其原生库或调整宿主设置；后续探针使用公开源码
重建的配套图形组件和已有 Android 10 库。当前路线以本文为准，其他文档中的
暂停点保留为此前阶段记录。

## 当前交付：原生画面与触摸试用版（2026-10-08）

主应用 `0.2.0-native-display` / versionCode 10 已切到普通应用 UID 的 Android 10
ARM64 编码客户端、宿主 GPU/Surface 和独立多指输入。主 APK 4,234,769 字节，
已完成构建、Lint、v2 签名及六个 ELF 校验，下载目录副本可供安装试用。
运行入口已移除 QEMU/TCG、截图/RFB 与镜像解压。

本轮普通 Termux UID 的生产离屏链路通过 50 帧/205 条事件，图形传输暂停期间
触摸仍送达。STOP 排队修复将立即停止场景从应用 2/205 条恢复到 205/205 条。
多指协议目标 60 Hz，尚无新版 APK/Surface 帧率实测；下方 P1b 的 30 Hz、100 次输入、
10 次重建是旧协议历史结果。详见 [当前证据](evidence/native-display.json)。

当前版本是图形/输入小闭环，完整 Android 10 桌面尚未实现；原始 Bionic 仍未与
配套源码运行时、私有属性/路径/Binder/HwBinder、ART 组合。
后续主线是完整 EGL/renderControl/gralloc/HWC/SurfaceFlinger 和系统服务集成。

## 前期组件验证与研究

后续实现：[图形小闭环](../container-probe/graphics/README.md)的 P1a 离屏与 P1b
窗口均通过普通 APK UID 实测。P1b 跑满 60 秒/100 次输入，10 次窗口重建保持客体
PID 并恢复图像；帧间隔 P95 为 34.83 ms，输入到 Surface 采样 P95 为 76.26 ms。
证据见 [P1a 历史清单](evidence/container-graphics-p1a.json) 和
[P1b 清单](evidence/container-graphics-p1b.json)。P2 的
[独立私有属性组件](../container-probe/properties/README.md)已通过 46 项检查：私有
SDK 29、跨进程 serial/wait、只读映射与实例隔离均有设备证据。客体 libc 属性 API
仍读宿主 SDK 36；新增真实 AOSP API archive 及 async-safe 构建，普通 APK UID 下
静态初始化前读值、构造后状态、失败重试与实例绑定等 5 个场景通过。API 目前链接
在独立测试 executable 内。新增[静态 Bionic 自举](../container-probe/runtime/README.md)
已通过普通 APK UID 的四个场景：真实初始化、线程/TLS、析构及退出 flush，私有
SDK 29 在 preinit 起生效，文件型可执行映射仅为自身。新增
[配套源码 linker / 动态 libc](../container-probe/runtime/dynamic/README.md)已通过普通
APK UID 实测：四种属性状态、四种装载失败、共享 globals、并发分配、动态 TLS
和 DSO 卸载通过；父进程还通过源码 linker `fork`/`execve` 启动并核验了子进程，
父子身份、属性映射与 `waitpid` 状态均通过。动态 SDK 在 libc constructor 后为 29；证据见
[动态运行库清单](evidence/container-runtime-dynamic.json)。新增
[数学/C++ 配套运行库](../container-probe/runtime/companion/README.md)已通过本地与
普通 APK UID 两轮各 39 项检查，跨库异常、RAII、线程/TLS 析构、动态卸载和
回溯验证通过；异常终止及缺库分别负测。libm 的 binary128 `sincosl` 最小修正和
AArch64 LLVM 展开器适配有单独证据，见
[配套运行库清单](evidence/container-runtime-companion.json)。属性握手修正后为
48 项，动态与配套探针共用私有配置。Binder/HwBinder 私有 API 子关卡已在普通
APK UID 下分别通过 native/device 24/24 与 16/16。新增
[免 root 文件系统/exec 模块](../container-probe/runtime/filesystem/README.md)在
Termux 普通 UID 下通过 29 项检查：客体绝对/相对路径、符号链接、APEX 目录别名、
私有写入、cwd 及经配套 linker 的 `fork`/`execve` 链；父子进程独立核验身份、
客体 ELF 闭集和三种属性文件的只读映射，四项判定负测通过。
新探针 APK 已构建及签名/内容核对，尚未安装运行；见
[文件系统证据](evidence/container-runtime-filesystem.json)。
完整路径/exec/APEX 语义、完整 G1/G2、ART/系统服务集成和 Android 10 桌面的
启动、点击性能仍待验收。下述静态研究保留原有证据口径。

## 1. 结论

**值得借鉴两仪的架构，但推荐重建可复现的 Android 10 配套组件，而非直接把
两仪 App、旧渲染库和现有 Android 10 镜像拼在一起。**

- 性能路线是让客体 ARM64 用户空间原生运行，替代 TCG 整机软件模拟；图形采用
  客体命令编码、宿主解码与 Surface 呈现，避开每帧截图、CPU 读回和 RFB 搬运。
  这是拟采用的性能路径，不是本轮已经取得的加速结果。
- 两仪公开 README 的客体是 **Android 8.1**；“初始化后三秒启动”是作者声明，
  Android 10 在该版本仍为计划。窗口重新接入、进程存活时恢复显示、完整冷启动
  是三个不同指标。[S1][S2]
- 新增的硬证据是：两仪与 AOSP Android 10 的**同号图形命令含义不同**，并且
  两仪渲染入口需要额外连接；“同为 emugl”不代表二进制或协议兼容，见第 2 节。
- 当前材料尚缺可构建的 loader、私有 Binder/HwBinder、Android 10 产品补丁
  和完整系统图形栈。维护者曾明确说明两个核心库当时未开源；此次刷新限定官方
  仓库和分支，也未取得完整 Android 10 构建清单。[S4][S14]

这里的“容器”指共享宿主内核的 Android 用户空间方案，不是独立客体内核；
客体虚拟 UID/root 与宿主权限分别处理。旧整机模拟后端及其专用记录已清理。

## 2. 已核实的两仪链路与关键缺口

证据分为：**源码事实、静态 ELF 事实、上游历史运行日志、作者声明、工程方案**。
后四类的边界在对应段落说明；没有把历史日志当成本机运行结果。

### 2.1 启动：不是 QEMU 快速启动开关

固定 App 提交为 `dd052a07a812e742ec7583da393466ccc066a8b1`。[S2]

```text
APK / SurfaceView
  -> Rust renderer_init -> ANativeWindow_fromSurface
  -> 首次：输入 socket 线程 + startOpenGLRenderer 线程
           + spawn ./init，cwd = /data/data/io.twoyi/rootfs
                          TYLOADER = loaderPath
  -> 已启动：setNativeWindow + resetSubWindow，不再次 spawn init
```

`libloader.so` 是 AArch64 / ET_DYN，入口 `0xce0`，解释器为宿主
`/system/bin/linker64`；入口最终调用 `__libc_init`，其 main 指针对应 ELF VA
`0xa548`。导入含 `mmap/mprotect/dlopen/dlsym`，但这不揭示完整的路径、属性、
exec 或虚拟身份实现。**不把这个 51 KB 文件的名称当成完整容器实现证据。**
两个原生库的来源、大小、哈希和静态地址记在 [审计清单](evidence/twoyi-static-audit.json)。

### 2.2 图形：已从函数名推进到实际调用与协议差异

对官方 `libOpenglRender.so` 的导出、反汇编和 AOSP 同类代码交叉检查，得到：

```text
startOpenGLRenderer
  -> initLibrary -> EGL / GLES dispatch
  -> initOpenGLRenderer -> RenderServer
     -> UnixStream / 配套 socket
     -> RenderThread::main
        -> GLESv1 decoder / GLESv2 decoder / renderControl decoder
        -> EGL / GLES 后端、FrameBuffer 与宿主窗口
```

`RenderThread::main` 的初始化、三路解码循环与历史 AOSP emugl 实现结构对应；
宿主库会动态装载 EGL/GLES 后端。这支持“emugl 风格命令流渲染”的判断，
**尚未锁定两仪的精确上游版本、完整改动集或实际 GPU 后端**。[S7][S8]
命令翻译、调用宿主 GLES、GPU 直通也不是同一件事；官网 FAQ 将 GPU 直通列为
后续方向。[S13]

#### 两处已证明的直接拼接障碍

| 检查项 | 两仪静态结果 | Android 10 AOSP 对照 / 影响 |
| --- | --- | --- |
| 连接握手 | `UnixStream::listen` 使用 `rootfs/opengles`；`RenderServer::create` 还监听 `rootfs/opengles2`；`main` 接受第二连接后，才从第一流读取 4 字节 flags 并创建渲染线程 | 只接通一个命令 socket 不代表服务端开始解码；第二条流的完整生命周期仍待恢复 |
| opcode `10029` | 跳转至 VA `0x58a54`，经 decoder 槽 `+0xf0` 调用 `rcGetNumDisplays()`，写回 4 字节 | Android 10 已检入的 encoder/header 将 `10029` 定义为 `rcCreateSyncKHR`，发送同步参数并读取两个 `uint64_t`；命令含义与返回长度均不同 [S10][S11] |

上述第二项的复核链是：解码器 `opcode - 10000` 跳表 → `10029` 分支 →
初始化槽位 → GOT `0x108648` 的 APS2 重定位符号 `_Z16rcGetNumDisplaysv`。
不是仅凭字符串猜测接口。所有 VA 为 ELF 链接地址，不是运行时地址；该库代码段
VA 比文件偏移大 `0x8000`。

还有一个构建注意点：所查 Android 10 固定提交中，`renderControl.in` 包含 Puid
变体，而已检入的 `renderControl_opcodes.h/enc.cpp` 使用另一组接口；其
`Android.mk` 直接列出这些 `.cpp`。因此，后续要以**实际构建输入和最终生成物**
做配对审计，别仅凭“同一仓库、同一 tag”推定所有协议文件一致。[S12]

**建议：旧库只作研究参照。新探针选择固定、公开的编码器/解码器来源，记录同一
协议定义、生成器版本、生成物哈希和扩展协商结果，再适配 APK 的 EGL/Surface。**
历史桌面 emulator renderer 也需要 Android 宿主窗口适配，不是原样链接即完成。
Android 10 的 `HostConnection` 还带有 QEMU Pipe、TCP、Virtio GPU 连接选择和
checksum/扩展协商；普通 APK 的私有传输需要显式适配，而非沿用默认设备路径。[S9]

### 2.3 Binder：私有 API 子关卡已通过，完整集成仍待实现

上游 #71 的历史崩溃栈显示：[S5]

```text
客体 libbinder!IPCThreadState::talkWithDriver
  -> 客体 libvbinder!virtual_binder_ioctl
  -> 内部 recv -> 客体 libc!recvfrom
```

维护者在 #3 提供的日志另包含 `VHWBINDER` 与死亡通知命令，说明研究范围还应
包括 HIDL/hwbinder。[S6] 这证明了具体适配层和收包路径，**未证明**服务端地址、
传输协议、FD/对象映射、线程池、引用计数及死亡通知已经可重建。
输入模块的 Unix socket 地址也不应直接套到 Binder 上。

Android 10 私有 API 子关卡现已独立验证：Binder native/device 均通过 24/24
client checks，覆盖服务注册、同步 RPC、嵌套回调、对象引用、FD、oneway 顺序、
并发、死亡通知和进程资源回收；HwBinder native/device 均通过 16/16，覆盖
context manager、service lookup、同步 RPC、回调及 calling identity 恢复、嵌套
SG/PTR/FD_ARRAY、HIDL vector/string/shared-memory 与 FD 生命周期。两组测试均
使用版本 `10 / p2-hidl-values`、UID `10764` 的普通 APK，并通过应用内 Unix
socket broker；broker 不访问宿主 `/dev/binder` 或 `/dev/hwbinder`，所以这只是
私有 API/传输子关卡，不是完整 G2。共享 transport 当前拒绝
`BINDER_BUFFER_FLAG_REF`，后续接入真实内核语义前必须补齐该能力。

### 2.4 输入与生命周期：借鉴边界，修正可见问题

输入源码把 `MotionEvent` 转成 `input_event`，经 Rust channel 送入私有 Unix
socket；连接后先发送 `repr(C) device_info`，再发送事件内存字节。[S3]
这不是直接操作宿主 `/dev/uinput`，客体还需要设备描述和读取/ioctl 的匹配端。

源码也暴露了值得避免的性能/正确性风险：

- `MAX_POINTERS=5` 的数组直接使用 pointer ID 索引，Move 分支又复用同一个
  pointer 的坐标；复用前需补上 ID→slot 映射及双指交叉、抬起、Cancel 测试。
- 每次连接创建发送线程，`rx.recv()` 失败后没有退出分支，`write_all` 错误也被
  忽略；旧连接退出与新连接替换应显式收拢，避免空转、积压和残留线程。
- `RENDERER_STARTED` 提前置位，启动子进程的结果被忽略。新实现应区分启动中、
  就绪、失败和显示已接入；Surface 存在不等于 Android 桌面已就绪。

这些是源码控制流审查结果，没有作为两仪在当前手机上的已复现故障上报。

## 3. 面向本项目的最小架构

以下是最终架构的职责划分；图形窗口预验证已实现，其他部分继续在现有探针中逐关验证。

| 职责边界 | 具体选择 | 验收重点 |
| --- | --- | --- |
| 宿主 App / 实例管理 | 保留全屏、镜像校验及导入 UI；实例与 Surface 生命周期分离；路径由实例传入而非固定 `io.twoyi` | 重建窗口保持客体 PID；失败可见、进程可回收 |
| Android 10 私有运行时 | 同版 linker/Bionic/ART；私有属性、路径、虚拟身份；最小服务监督器 | SDK 29 来自客体属性区；库来源、线程/TLS、exec/JIT 及应用数据隔离正确 |
| 私有系统 IPC | 独立 Binder/HwBinder 兼容层；注册表留在客体域 | RPC、回调、FD、死亡通知；断线与进程退出后资源回收 |
| 图形与输入 | Android 10 EGL/GLES 编码端 + 匹配宿主解码端；再接客体 gralloc/HWC/SF；输入走独立小通道 | 命令与帧序号关联、同步对象、纹理/缓冲区生命周期、点击反馈 |
| mount-free 系统服务 | 仅在完整运行时关卡通过后适配 init/vold/zygote/system_server | 无宿主挂载前提，Launcher/SystemUI、安装和持久化真实工作 |

首个图形原型限定 GLES 2、单显示器、ARM64；暂不加入 Vulkan、32 位、相机、
多实例或整机快照。按需的软件 buffer 上传仍可能存在，不预先宣称零拷贝。
两仪新 vold 分支的 mount-free 思路可参考，但它不是现成 Android 10 产品树。[S14]

Android 12+ 的子进程管理是**前置门槛**：官方两仪指南依赖开发者设置/ADB 的
处理方式，不直接满足本项目“安装 APK 即用”。前台服务本身不是多进程保活保证；
需要在普通 APK UID 和实际 targetSdk 下覆盖宿主版本、进程数与回收场景。[S15]
若这一关或私有 IPC 未通过，就停在探针阶段，不继续扩成整份 ROM。

## 4. 下一步顺序与可衡量结果

本节保留阶段验收条件；P1 已由 P1a/P1b 探针通过，P2 独立属性切口、Binder
和 HwBinder 私有 API 子关卡通过，源码 linker/动态 Bionic 和数学/C++ 配套库
已有独立验收；完整 G1/G2 运行时语义与 P3 尚待实现。

| 顺序 | 最小产物 | 通过条件 |
| --- | --- | --- |
| **P0：本轮研究** | 本文、静态审计清单 | 启动、三路解码、双连接、opcode 冲突及 Binder 线索有对应证据；已完成 |
| **P1：图形小闭环** | 无 ROM 的小 APK，受控 Android 10 编码客户端 → 匹配解码器 → Surface | 已通过 P1a/P1b：真实序号帧、100 次输入、10 次 Surface 重建保持 PID 与图像恢复、实际 EGL/GL 身份；停止协议正常退出 |
| **P2：运行时与 IPC** | 复用 `container-probe`，验证私有属性、双进程 Binder/HwBinder 及资源回收 | 属性、显式 linker `fork/execve` 子关卡、Binder 24/24、HwBinder 16/16 和断线回收已通过；`completeG2=false`，G1 通用路径/exec/APEX、内核驱动语义、跨 UID 策略和完整系统服务仍待实现 |
| **P3：系统合成与桌面** | 同版 ART、SF/HWC/gralloc、最小系统服务及 Launcher | 保留 G3–G5 验收；真实桌面、应用安装、触摸、重启后数据持久化；再测冷启动，而非用测试三角形代替桌面 |

P1 是原 G4 的独立预验证，**不代表 G1/G2 已通过**。现有 G1 stage-0 只证明
普通 APK 下受控 ELF 与客体库装载；P2 新增的独立属性区、Binder 和 HwBinder
报告证明了对应子关卡，不等同于完整源码 libc/ART 或系统 IPC 接入，完整 G1
仍有通用进程启动、路径/exec/APEX 与身份适配关卡；当前 exec 证据仅覆盖受控
程序经源码 linker 的父子进程链。证据见
[既有报告](evidence/container-g1-stage0.json)、[P2 属性清单](evidence/container-properties-p2.json)、
[动态运行库](evidence/container-runtime-dynamic.json)、
[配套运行库](evidence/container-runtime-companion.json)和[原型说明](../container-probe/README.md)。

下一切口是把已验证的应用内 broker 接入完整 Android 10 运行时边界：补齐 ART、
通用路径/exec/APEX、跨 UID 策略及真实系统服务启动，再接系统合成与桌面。
Launcher/SystemUI、SurfaceFlinger/HWC/gralloc、应用安装、触摸和重启持久化均
尚未完成；当前结果不代表完整 Android 10 桌面。真实内核 Binder/HwBinder 语义
和 `BINDER_BUFFER_FLAG_REF` 也仍是待补能力，必须保留通道缺失负测和回滚路径。

阶段性能预算：P1b 已按下列场景通过探针预算；P3 仍为待验证目标。

- P1 在 360×640、固定 30 Hz 测试场景中测 60 秒，帧间隔 P95 ≤ 50 ms；触摸到
  对应可见序号 P95 ≤ 150 ms，至少 100 次输入。区分客体回包、宿主提交与可见呈现，
  带上采样误差，不把 `eglSwapBuffers` 返回当作物理屏幕已经更新。
- P3 先争取初始化后完整冷启动 ≤ 30 秒、存活实例重接 ≤ 2 秒；分别做至少三轮，
  报中位数和最慢值。首次解压另计，进程全退后的启动才计作冷启动。
- 达标对象是最终的 Android 10 桌面和真实交互。P1 达标仅说明图形路线值得继续。

## 5. 存储、交付与工程原则

- 两个官方 ELF 合计 **1,110,168 字节**，只读保存，未执行；本轮仅增加小型
  源码和文本证据。全部研究材料约 2 MiB，位于 `artifacts/research/twoyi-core/`。
  未新增 ROM、磁盘副本、内存快照或完整 AOSP checkout。
- 下一步仍先用小探针；必要组件从已有审计素材复用。达到 P3 前不生成完整新镜像。
  进入打包阶段后只保留一份当前 APK 和必要基底/数据链，派生中间件验证后按需清理；
  现有用户数据及磁盘引用保持不变。
- **KISS/YAGNI：**先证明两条最关键路径，不重写管理 UI、不扩大外设范围。
  **SRP/SOLID：**运行时、系统 IPC、图形输入、宿主生命周期分别举证和验收。
  **DRY：**复用现有安装校验、测量口径与探针；协议双端共享明确的版本来源。
- 原静态研究新增文档与审计清单；后续 P1a/P1b、P2 独立属性、Binder/HwBinder
  组件的代码、APK 与设备证据另有记录。
  完整桌面的启动和点击目标尚未因图形或 IPC 子关卡而通过验收。
- 静态复核通过：UTF-8/无 BOM、JSON 解析、两份 ELF 大小与 SHA-256/Git blob 哈希、
  只读属性、导出地址、opcode 跳表、APS2 符号目标、AOSP 返回布局和文档本地链接；
  Binder/HwBinder 的 App 构建、native/device 检查和清理结果分别以对应证据清单为准，
  不替代完整桌面和性能验收。

## 第一方来源与复核入口

两仪样本和源码均固定到 `dd052a07a812e742ec7583da393466ccc066a8b1`；
AOSP 历史 host 对照固定到 `9a21e8c61517ca9aa8fc244810fea96b361e383c`，
它只用于结构对照，不标作两仪的确切祖先；Android 10 goldfish-opengl 固定到
`d291bbd969a8cdb7bf9ac6f7d46af5b3d2b6c309`（`android-10.0.0_r47`）。

- **S1**：[两仪 README：版本与启动声明](https://github.com/twoyi/twoyi/blob/dd052a07a812e742ec7583da393466ccc066a8b1/README.md)。
- **S2**：[Rust 启动与 Surface 分支](https://github.com/twoyi/twoyi/blob/dd052a07a812e742ec7583da393466ccc066a8b1/app/rs/src/lib.rs#L39-L107)。
- **S3**：[输入完整发送端](https://github.com/twoyi/twoyi/blob/dd052a07a812e742ec7583da393466ccc066a8b1/app/rs/src/input.rs)。
- **S4**：[维护者关于核心库源码的历史说明](https://github.com/twoyi/twoyi/issues/105#issuecomment-1092469840)；[ROM 跨仓库改动说明](https://github.com/twoyi/twoyi/issues/53#issuecomment-1034461793)。
- **S5**：[#71 历史 Binder 栈](https://github.com/twoyi/twoyi/issues/71)。
- **S6**：[#3 维护者 HwBinder 日志](https://github.com/twoyi/twoyi/issues/3#issuecomment-1007528025)。
- **S7**：[两个官方 ELF](https://github.com/twoyi/twoyi/tree/dd052a07a812e742ec7583da393466ccc066a8b1/app/src/main/jniLibs/arm64-v8a)；[本项目静态清单](evidence/twoyi-static-audit.json)。
- **S8**：[AOSP emugl RenderThread](https://android.googlesource.com/platform/external/qemu/+/9a21e8c61517ca9aa8fc244810fea96b361e383c/distrib/android-emugl/host/libs/libOpenglRender/RenderThread.cpp)；[DESIGN](https://android.googlesource.com/platform/external/qemu/+/9a21e8c61517ca9aa8fc244810fea96b361e383c/distrib/android-emugl/DESIGN)。
- **S9**：[Android 10 HostConnection：连接、编码器与扩展协商](https://android.googlesource.com/device/generic/goldfish-opengl/+/d291bbd969a8cdb7bf9ac6f7d46af5b3d2b6c309/system/OpenglSystemCommon/HostConnection.cpp)。
- **S10**：[Android 10 renderControl opcode 表](https://android.googlesource.com/device/generic/goldfish-opengl/+/d291bbd969a8cdb7bf9ac6f7d46af5b3d2b6c309/system/renderControl_enc/renderControl_opcodes.h)。
- **S11**：[Android 10 已检入 encoder：rcCreateSyncKHR](https://android.googlesource.com/device/generic/goldfish-opengl/+/d291bbd969a8cdb7bf9ac6f7d46af5b3d2b6c309/system/renderControl_enc/renderControl_enc.cpp#1098)。
- **S12**：[同提交协议定义、生成物和 Android.mk](https://android.googlesource.com/device/generic/goldfish-opengl/+/d291bbd969a8cdb7bf9ac6f7d46af5b3d2b6c309/system/renderControl_enc/)。
- **S13**：[官方 FAQ 固定部署源码](https://github.com/twoyi/twoyi.github.io/blob/fc0352a9fbe20ae88892262471545939fc0c7d57/zh/guide/faq.html)。
- **S14**：[vold mount-free 改动](https://github.com/twoyi/system_vold/commit/f9f6c5b183d4c5d56d94f5464df88db00eaa71fb)；[已有组织/分支审计范围](CONTAINER_FEASIBILITY.md#1-公开依赖调查不只看主-readme)。本轮组织仍为 11 个公开仓库，所查关键分支 SHA 未变。
- **S15**：[官方 Android 12/13 指南固定部署源码](https://github.com/twoyi/twoyi.github.io/blob/fc0352a9fbe20ae88892262471545939fc0c7d57/zh/guide/android-12.html)。

本地增量上游笔记：`artifacts/research/twoyi-core/upstream.md`。二进制、下载源码及
工具输出留在被 Git 忽略的研究目录；可从固定 URL 与清单哈希重新取得。
重定位打印遇到旧 ELF 的 `SHT_ANDROID_RELA sh_link=0` 问题后，改为只读解析 APS2，
并与 dynsym、槽位赋值和跳表交叉复核；未修改样本节头来掩盖工具错误。

【MCP调用简报】服务：本地 Shell/gh/curl/LLVM，未调用外部 MCP；触发：两仪核心
架构与 Android 10 配对核对；参数：固定源码、两个 ELF、限定上游讨论；结果：
获得协议冲突、双连接和 Binder 适配证据，完成分阶段方案；状态：成功。
