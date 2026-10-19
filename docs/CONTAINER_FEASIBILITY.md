# 两仪式 Android 10 容器后端：依赖核对与原型关卡

日期：2026-10-06。目标是同时缩短冷启动和改善桌面交互，不把“保存后恢复快”
等同于“系统运行快”。用户选择优先验证容器路线；Android 11+、免 Root、安装
APK 即用、客体 Android 10 的产品条件保持不变。

初始调研检查第一方源码、仓库结构和现有镜像的静态报告；随后完成独立小 APK 的
G1 stage-0 原生装载实测，见下文。没有启动 A10VM、安装两仪 APK 或修改宿主配置。
当前产品路线与使用方法见根目录 README；本文件记录后端可行性证据。

## 结论与证据标记

**建议继续做容器原型，但起点是可构建的加载器与私有 IPC，不是把现有磁盘
直接交给两仪 App。** 当前公开材料足以确定改造边界，尚未组成一套可直接
构建的 Android 10 免 Root 容器系统。

- **已证明：**本次读到的源码、仓库结构或静态工件事实；不代表运行态通过。
- **作者声明：**README、文档及源码注释中的设计目标，未单独实测。
- **推断/方案：**根据源码推导的工程选择，标明边界和验收条件。
- **待验证：**需要新增实现、构建或后续普通 APK UID 测试的项目。

## 1. 公开依赖调查：不只看主 README

已列出 `twoyi` 组织的 11 个公开仓库及各自全部公开分支；递归核对 App、
四个 AOSP 组件、辅助仓库的默认源码树，并额外检查 `system_vold` 的新分支。
相关源码树 API 均返回 `truncated=false`。检索范围限于这些公开仓库及其
已列分支/子模块，不包含私有仓库或未公开资料。[T1]

| 仓库 | 本次分支/源码证据 | 对 Android 10 容器的意义 |
| --- | --- | --- |
| `twoyi` | 只有 `main`，`dd052a07…`；无 Git 子模块；`libloader.so`、`libOpenglRender.so` 为预编译文件 | 有 App 入口，没有对应完整加载器/ROM 构建闭环 [T2] |
| `hardware_libhardware_legacy` | 只有 `twoyi-8.1.0`，`0e5bd31e…`；无子模块 | 单个 Android 8.1 硬件组件，不是系统 manifest [T3] |
| `platform_art` | 只有 `twoyi-8.1.0`，`dac2a2e0…`；无子模块 | `init for twoyi` 补丁只修改内联阈值、默认重定位两个常量；不是 syscall/Binder 兼容层 [T4] |
| `platform_system_connectivity_wificond` | 只有 `twoyi-8.1.0`，`5b1efdab…`；无子模块 | 单个 Wi-Fi 组件，没有整机产品定义 [T5] |
| `system_vold` | `twoyi-8.1.0` 为 `02ef37b9…`；另有 `twoyi-17.0.0`，`f9f6c5b1…`；两棵树均无子模块 | 发现近期组件实验，但不是 Android 10 ROM 清单，详见下文 [T6] |
| `Superuser` | `cm-10.1`、`master`、`twoyi`、`wip`；默认 `twoyi` 无子模块 | 命中的 `local_manifest.xml` 只包含 `koush/Superuser`、`koush/Widgets` 两个附加项目，不是 Twoyi 系统清单 [T7] |
| `Magisk` | `master`、`fix/vndr4_dump`；默认树含 15 个子模块 | 子模块是 busybox、压缩库、SELinux、xHook 等依赖，没有 Twoyi ROM/loader 源码入口 [T8] |
| `Widgets` | `master`、`native`、`support`、`twoyi`；默认树无子模块 | UI 辅助组件 |
| `Superuser-UI` | 只有 `master`；无子模块 | 管理界面 |
| `GApps` | 只有 `main`；无子模块 | 附加应用材料，不是容器运行时 |
| `twoyi.github.io` | `master`、`gh-pages` | “制作 ROM”指南实际从发行 APK 提取 rootfs 后修改、重打包，不是 AOSP 源码编译指南 [T9] |

因此，**在本次审查范围内，未发现可构建的 `libloader.so` 对应实现，也未发现
Android 10 的完整 repo manifest、device/product 配置和配套核心补丁集。**
`platform_art` 中的 JNI/class loader 文件与这里所需的 ELF/系统兼容加载器是
不同职责，搜索命中不等于补齐运行时。

### `twoyi-17.0.0` 的基线交叉核实

这里没有根据分支数字猜版本：`f9f6c5b1…` 的父提交为
`6d20a0078c2bcaa2499dc5d032f337bfe1182d9e`；该提交在 Android 官方
`platform/system/vold` 仓库中存在，消息为 2026-03-21 的
`Snap ... to 26Q2-release`。[T6][T10]

新补丁主要移除块设备冷扫描、挂载清理和 BootControl/checkpoint 依赖，
为 user-0 的 `/data/media` 存储目录实现 mount-free 生命周期；注释明确描述
`shared-kernel`、`mount-free`。这证明该组件有新工作，**不是 LineageOS 17
名称猜测，也不是完整 Android 10 系统已公开的证据**。其注释描述的架构不应
反向当成旧版两仪所有内部实现都已公开。[T6]

## 2. Android 10 普通 APK UID 的必要改造

源码基线固定为 AOSP `android-10.0.0_r47`，各仓库实际提交见文末。
它用于定位接口和依赖，不冒充当前 reDroid 工件逐字节对应的完整构建源码。

### 2.1 加载、路径与属性：首先分开宿主和客体运行时

**已证明：**现有 Android 10 工件使用绝对 ELF 解释器路径；AOSP linker 配置
同时引用 `/system`、`/vendor`、`/data` 和 `/apex/com.android.runtime`。
Bionic 属性实现访问 `/dev/__properties__/property_info`。[A1][A2]

**最小方案：**使用独立客体进程与可重建加载器，明确客体库搜索路径、APEX
目录映射和私有属性区；以小型 supervisor 管理客体服务，而不是先执行完整
系统 `init`。宿主 UI 继续使用宿主 ART/Bionic，客体运行时留在独立进程。

- 只设置 `ANDROID_ROOT`/`LD_LIBRARY_PATH` 不是完整路径虚拟化；
  `openat/stat/readlink`、Unix socket、`exec`、符号链接和 `/proc` 视图需要
  一致规则。优先修改可构建的客体组件；动态拦截方案还需验证静态链接和直接 syscall。
- 客体属性读写应进入私有区；以宿主 `getprop` 返回值代替客体 Android 10
  属性会让版本检测和系统服务决策失真。
- 当前材料缺少通用加载/路径兼容核心。第一个原型只承诺装载一个受控 ELF，
  不将其扩大解释为全部 Android 用户空间已适配。

### 2.2 Binder 与 servicemanager：最早的系统级关键关卡

**已证明：**Android 10 `ProcessState` 默认打开 `/dev/binder`，进行
`BINDER_VERSION`、线程设置与事务区 `mmap`；`IPCThreadState` 通过
`BINDER_WRITE_READ` 传递事务。`servicemanager` 要成为 context manager。
Linux Binder 驱动对已存在的 context manager 返回 `EBUSY`，并执行权限检查。
AOSP 普通应用策略也禁止向宿主 service manager 添加系统服务。[A3][A4][A5][A6]

**推断：**复用宿主 `/dev/binder` 不会得到一套独立客体 servicemanager。
可用的独立 binderfs 实例是另一种前提，但需要相应挂载/设备访问条件；
Linux 文档说支持 user namespaces，不等于每台 Android 普通 APK 都具备条件。[A7]

**免 Root 原型选择：**先做应用私有的 Binder 兼容传输与服务注册表，明确支持
范围；客体 `libbinder` 和 C 版 servicemanager 都要进入它。后续图形 HIDL 路径
还涉及 `libhidlbase`/hwservicemanager，需要一并处理，而非只适配 Java Binder。

- 首个闭环至少验证同步 RPC、嵌套回调、对象句柄/引用、死亡通知、FD 传递。
  只做 Unix socket 的字符串 echo，未覆盖 Binder 语义。
- `IPCThreadState` 从事务读取 `sender_pid`/`sender_euid`，因此私有 IPC 的身份
  模型要与客体进程模型一致；套接字同一宿主 UID 不代表所有客体都应表现成 root。
- AOSP `ProcessState::initWithDriver()` 在自定义路径访问失败时会回退
  `/dev/binder`。容器构建应去掉这种静默回退，并测试私有通道中断时明确报错，
  防止误把宿主响应当成客体服务已启动。[A3]

### 2.3 UID、zygote 与 exec：原生速度需要真实兼容层

**已证明：**Android 10 `app_process` 的 zygote 路径会创建 dalvik-cache 并
`chown(..., AID_ROOT, AID_ROOT)`；Zygote JNI 包含 `unshare(CLONE_NEWNS)`、
存储挂载、`setgroups`、`setresgid/setresuid` 及 SELinux 域设置。[A8][A9]

**最小方案：**宿主进程保持普通应用 UID；客体 UID/GID、权限判定、所有者元数据
和 IPC 身份由客体兼容层一致维护。原型先用一个测试应用，之后再验证不同客体
应用之间的数据隔离。仅把所有失败调用伪装成成功会留下身份与存储语义缺口。

**执行条件：**AOSP Android 10 对 target API 29+ 的应用数据目录 `execute_no_trans`
已有约束，两仪旧 `targetSdk=27` 路径不宜直接沿用为新产品基础。[A6]
加载器/启动器应从 APK 安装的原生库位置运行；客体 ELF 装载、可执行映射、
`dlopen` 和子进程派生仍须逐项验证。普通 APK 测试结果与 Termux/root 测试分开记录。

### 2.4 图形与输入：去掉 TCG 不是桌面流畅的充分条件

**已证明：**Android 10 SurfaceFlinger 会注册 Binder 服务；Composer 通过 HIDL
取得 `IComposer`、创建 client、提交 buffer 和 fence；分配器使用 Gralloc 3/2。
所以仅把 SurfaceFlinger 进程启动起来，并未补齐显示硬件抽象层。[A10][A11][A12]

**最小方案分两步：**

1. 客体虚拟 HWC/gralloc → 明确的缓冲区/帧序号协议 → 宿主 `Surface`；
   先用软件画面验证尺寸、stride、格式、fence/生命周期和触摸往返。
2. 验证客体 GLES 调用/缓冲区桥接至宿主渲染端的可构建方案，测 CPU 占用、
   帧时间与触摸反馈。第一步的彩色测试图或软件拷贝通过不代表 GPU 加速通过。

两仪公开 App 的 `libOpenglRender.so` 仍是预编译边界；当前证据没有补齐它和
Android 10 客体端配套实现。宿主驱动 ABI、HAL 与同步对象也不应按“同为 ARM64”
直接混用。现有全屏 UI、安装与校验逻辑可保留，显示协议与运行后端分别适配。

## 3. 最短原型关卡

| 关卡 | 可衡量通过条件 | 当前状态 |
| --- | --- | --- |
| **G0：静态输入审计** | 镜像身份、六个核心 ELF 的解释器/依赖/SHA；原镜像前后哈希一致 | **已完成静态验证**，见下文 |
| **G1：加载与私有环境** | 可从源码构建的 APK loader 装载受控 Android 10 ELF；客体库/属性来自指定来源；退出码与日志可回收；执行入口不依赖 root | **部分验证**：stage-0 普通 APK 原生 ELF/客体库装载通过；源码重建、私有属性与路径仍待实现 |
| **G2：私有 Binder** | 两个客体测试进程通过 Android 10 Binder API 完成 RPC、回调、FD 和死亡通知；注册表不落到宿主 Binder | **待实现**；协议状态机和断线/句柄测试先离线完成 |
| **G3：ART/zygote** | 使用客体 Android 10 ART 执行 Java 测试，再派生一个客体应用；属性、UID 和数据目录行为一致 | **待验证**；宿主 app_process 跑通不计入本关 |
| **G4：显示输入** | 客体 SF 测试层 → 宿主 Surface 可见；触摸反向确认；重建窗口后恢复；记录帧时间；另列 GLES 加速结果 | **待验证**；软件首帧与加速首帧分别记录 |
| **G5：最小完整桌面** | system_server + SystemUI/Launcher 可交互；一次冷启动、一次显示重连、应用安装及重启持久化通过 | **待验证**；到此再对照原后端冷启动/卡顿数据 |

顺序采用 G0 → G1 → G2 → G3/G4 → G5。G1/G2 任何一关没有明确实现来源与
可重复结果时，不进入“完整 Android 10 秒开”宣传或大规模 UI 重写。

### 已完成 G0 的可重复证据

```sh
sh guest-runtime/audit-inputs.sh \
  artifacts/guest/android10-display-v4.raw \
  artifacts/container/gate-0-repeatable
```

本次读取 `artifacts/container/gate-0-repeatable/report.json`：

- `inputsVerified=true`、`sourceUnchanged=true`、`runtimeTested=false`。
- 工件声明 `SDK=29`、`release=10`，四个系统程序为 Android 29/AArch64 ELF。
- `init` 的解释器为 `/system/bin/bootstrap/linker64`；其余三个为
  `/system/bin/linker64`，镜像运行时布局依赖 APEX linker。
- 六个 ELF 为 init、servicemanager、app_process64、surfaceflinger、bootstrap
  linker64 和 runtime APEX linker64；两份 linker64 的 SHA-256 一致。
- 原基底 SHA-256：
  `fc10aa9478729b1795ede64c0f5b996759262dc6bb43271b19c7d88615a16373`。

该关证明素材身份和切入点，不证明全部递归库依赖齐全、宿主执行成功或容器可启动。

### 已完成 G1 stage-0 的运行证据

独立模块 `container-probe` 在本机 SDK 36 / ARM64 / 4 KB 页通过三个对照：
客体 linker 装载成功、宿主库对照被识别、移除 libc 链接后明确报缺库而非回退。
安装后的五个原生文件 SHA 均核对，受测子进程为普通 APK UID、零 capabilities、
`untrusted_app` 域。安装和报告导出借用开发手机 Root，APK 启动逻辑没有该依赖。
没有启动主 App 或复制整盘，测试包取回报告后自动卸载。

这一结果证明**受控 Android 10 原生 ELF 装载路线**，不代表完整私有运行时。
属性读取仍返回宿主 SDK 36，客体 Bionic / linker 尚未由本工程源码构建，故 G1 保持部分完成。
复现入口和限制见 [`container-probe/README.md`](../container-probe/README.md)；
精简证据见 [`evidence/container-g1-stage0.json`](evidence/container-g1-stage0.json)。
静态脚本及工件由主任务生成，本次文档调查只读取报告。

## 4. 实施边界与下一步

当前最缺的依赖是：**可构建加载/路径核心、私有 Binder/HIDL 运行时、匹配的
Android 10 产品补丁集、客体与宿主两端可构建的图形桥**。AOSP 公共源码提供
基础，不会自动补上这些兼容层。

下一步优先 G1 的源码重建、私有属性与绝对路径适配；G2 的 Binder 最小语义另建
独立测试。沿用现有镜像审计/安装与 UI，先不替换用户数据。遵循 KISS/YAGNI，
把风险集中在两个最早决定可行性的接口；SRP/DRY 体现为运行后端、私有 IPC、
图形输入分别测试，而非复制一套管理 App。

## 固定来源

### 两仪组织

- **T1**：[公开仓库列表 API](https://api.github.com/orgs/twoyi/repos?per_page=100)；分支通过各仓库 `/branches?per_page=100` 在线核对。此项为查阅日快照，以下关键源码固定提交。
- **T2**：[App 源码树](https://github.com/twoyi/twoyi/tree/dd052a07a812e742ec7583da393466ccc066a8b1)；[启动入口](https://github.com/twoyi/twoyi/blob/dd052a07a812e742ec7583da393466ccc066a8b1/app/rs/src/lib.rs)
- **T3**：[hardware_libhardware_legacy](https://github.com/twoyi/hardware_libhardware_legacy/tree/0e5bd31e8118be5887de24cf458b79a9232661d3)
- **T4**：[ART 默认分支提交](https://github.com/twoyi/platform_art/tree/dac2a2e05d4cba88628ce30c0e0e47c6a27d3915)；[Twoyi 两行改动](https://github.com/twoyi/platform_art/commit/7b5d31111b1128081d48d015306136b97e617cc4)
- **T5**：[wificond](https://github.com/twoyi/platform_system_connectivity_wificond/tree/5b1efdabf42defb23749ec65b0b3a9e08f13a88f)
- **T6**：[vold 8.1 分支](https://github.com/twoyi/system_vold/tree/02ef37b9f12f2a721fc13505d4ae077f06c496f5)；[mount-free 补丁](https://github.com/twoyi/system_vold/commit/f9f6c5b183d4c5d56d94f5464df88db00eaa71fb)
- **T7**：[Superuser 的附加项目 manifest](https://github.com/twoyi/Superuser/blob/416660aaa94e8d963c98d6bbcd0296dff216775d/local_manifest.xml)
- **T8**：[Magisk 子模块清单](https://github.com/twoyi/Magisk/blob/558710bbdd5ba9c462d496d311d6004162164579/.gitmodules)
- **T9**：[官方自定义 rootfs 指南的部署源码](https://github.com/twoyi/twoyi.github.io/blob/fc0352a9fbe20ae88892262471545939fc0c7d57/zh/guide/customize-rootfs.html)
- **T10**：[vold 新分支的 Android 官方父提交](https://android.googlesource.com/platform/system/vold/+/6d20a0078c2bcaa2499dc5d032f337bfe1182d9e)

### Android 10 / Linux 接口

- **A1**：[linker namespace/APEX 配置](https://android.googlesource.com/platform/system/core/+/1dea9a052b7f214c10a77d5ed6ffd3602722a817/rootdir/etc/ld.config.txt)
- **A2**：[Bionic system properties](https://android.googlesource.com/platform/bionic/+/290c0cb5044b643e5d6cbcb1a5b275541ca3a89e/libc/system_properties/system_properties.cpp)
- **A3**：[ProcessState：driver、mmap 和回退](https://android.googlesource.com/platform/frameworks/native/+/013eb744f289c70e6d3fe180500d9a414ac55539/libs/binder/ProcessState.cpp)
- **A4**：[servicemanager](https://android.googlesource.com/platform/frameworks/native/+/013eb744f289c70e6d3fe180500d9a414ac55539/cmds/servicemanager/service_manager.c)；[IPCThreadState](https://android.googlesource.com/platform/frameworks/native/+/013eb744f289c70e6d3fe180500d9a414ac55539/libs/binder/IPCThreadState.cpp)
- **A5**：[Linux 6.6 binder_ioctl_set_ctx_mgr](https://github.com/torvalds/linux/blob/ffc253263a1375a65fa6c9f62a893e9767fbebfa/drivers/android/binder.c#L5109)
- **A6**：[Android 10 app_neverallows：服务、属性和执行条件](https://android.googlesource.com/platform/system/sepolicy/+/6ec9b2e9e20213a19f8a05d0c20e903399cfd581/private/app_neverallows.te)
- **A7**：[Linux binderfs 接口文档](https://docs.kernel.org/admin-guide/binderfs.html)；[固定源码](https://github.com/torvalds/linux/blob/ffc253263a1375a65fa6c9f62a893e9767fbebfa/drivers/android/binderfs.c)
- **A8**：[Android 10 app_process](https://android.googlesource.com/platform/frameworks/base/+/dff3deab5d25f8bbfd49abfb423043c9be47b7db/cmds/app_process/app_main.cpp)
- **A9**：[Android 10 Zygote JNI](https://android.googlesource.com/platform/frameworks/base/+/dff3deab5d25f8bbfd49abfb423043c9be47b7db/core/jni/com_android_internal_os_Zygote.cpp)
- **A10**：[SurfaceFlinger 主程序](https://android.googlesource.com/platform/frameworks/native/+/013eb744f289c70e6d3fe180500d9a414ac55539/services/surfaceflinger/main_surfaceflinger.cpp)
- **A11**：[Composer HAL client](https://android.googlesource.com/platform/frameworks/native/+/013eb744f289c70e6d3fe180500d9a414ac55539/services/surfaceflinger/DisplayHardware/ComposerHal.cpp)
- **A12**：[GraphicBufferAllocator](https://android.googlesource.com/platform/frameworks/native/+/013eb744f289c70e6d3fe180500d9a414ac55539/libs/ui/GraphicBufferAllocator.cpp)

工具简报：本地 Shell/curl/gh 读取限定的一手资源和静态报告；未调用外部 MCP。
匿名 GitHub API 达到配额后，切换已配置的 gh 只读请求及固定 raw/Gitiles 来源；
没有把检索失败当成源码不存在的证据。
