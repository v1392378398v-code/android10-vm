# A10VM 流畅度 / 刷新率 / 应用启动卡顿 —— 优化方案

> 面向实施者（GPT）。本文档只描述「改什么、为什么、怎么验证」，不含已完成改动。
> 仓库根目录：`/data/data/com.termux/files/home/android10-vm`
> 设备：Android 15 / aarch64 / 宿主面板 1440×3168 @ 120 Hz
> 容器形态：twoyi 式，免 root，guest = Android 10 私有 linker + Bionic + ART

## MIUI12 实施记录（2026-10-12，v0.2.58）

- 本轮推进实际运行开销：仅写 Binder 命令跳过重复 Rearm，最后一条命令与读取合并为 `CommandRead`；Hello ACK 宣告能力，旧服务端继续分开发送。1000 次写命令的 Rearm 从 1000 次降至 0 次，独立的读取、ACK/Event 顺序及错误时的事件保留语义不变。
- 调度路径缓存实际宿主 UID，仍对每次请求核对进程启动时间，对变更优先级时的每个 TID 核对启动时间。`/proc/*/stat` 使用复用缓冲区直接解析 nice/starttime，移除正则拆分及临时字符串；客体虚拟 `getuid()` 不用于宿主身份校验。
- `GuestMemory` 每个连接复用一个 ByteBuffer，移除只写未读的优先级副本；状态由 `GuestScheduling` 单独管理。遵循 KISS/YAGNI/DRY/SRP，只处理已采样热点，保留模块边界和原有调度规则。
- 安装版调度回归通过：nice 10 → 5 → 原始 RenderThread nice -4；同一优先级下保留线程自设 nice，包含括号和空格的线程名解析与实际内核值一致。
- 修正桌面验收对旧日志的处理：等待本轮 ready 增量，取最新 `desktop_pid`，重启检查也比较最新 PID。v058 通过正常 app-service 启动，约 20.271 秒，普通 UID 10326、CapEff=0，5 秒检查中服务持续运行。
- v058 已覆盖安装并保留应用数据，安装包位于 `/storage/emulated/0/Download/A10VM-MIUI12-1080x2160-v0.2.58.apk`。构建/lint、v2 签名、2628 个原生文件、5147 个运行资源、319 个系统 APK 内容校验通过。
- 核对显示时发现 MIUI 保存的逻辑密度覆盖为 411 dpi；上述应用启动/版本对比均保留此旧设置。通过客体系统 Binder 接口恢复为 480 dpi，最终实机检查通过 1080×2160、120.00001 Hz、480 dpi，仍以普通宿主 UID 运行。

| 同场景样本 | v056 | v057 仅 Binder 优化 | v058 Binder + 调度优化 |
| --- | ---: | ---: | ---: |
| 抖音 6 次滑动 FPS | 93.88 | 101.17 | 97.06 |
| P95 帧间隔 ms | 16.598 | 16.594 | 16.597 |
| 最长帧间隔 ms | 99.581 | 33.187 | 116.160 |
| UID 进程平均 CPU 核数 | 3.530 | 3.558 | 3.191 |

- 保留数据、强制停止后重开 WaitTime：B 站 4946 → 4616 ms，QQ 2647 → 2208 ms，微信 1976 → 1307 ms，抖音 2573 → 2448 ms；四个应用首屏都绘制完成，system_server PID 保持 9544。
- 恢复 480 dpi 后的独立抖音样本为 88.38 FPS、P95 24.891 ms、最长间隔 149.360 ms、CPU 4.044 核；该样本的显示配置和内容与前表不同，不与前表混作同条件改善。最终显示配置下的流畅度目标尚未达成。
- 上述为每个场景一轮样本，热状态、网络内容和后台进程数量未固定；v058 的 110 FPS 门槛仍失败，长帧没有消除，未据此宣称稳定 120 FPS或整机发热已解决。
- 下一步围绕 B 站仍需约 4.6 秒的冷启动阶段与剩余长帧做定向采样；小米账号登录仍未完成。完整数字及验证边界见 [v0.2.58 证据](evidence/app-performance-miui-v058.json)。

## MIUI12 实施记录（2026-10-11，v0.2.53）

- MIUI APK 固定使用 `io.a10vm.miui`，复用原生 ARM64 与宿主 GPU，显示为 1080×2160、120 Hz 配置。
- 根据实际 HAL 注册状态处理 SLA/CACert 常驻包，消除缺 HAL 导致的重启开销；保留包与数据，并在 HAL 接通后恢复状态。
- 补齐 ROM JNI、WebView provider、同进程多次打开 Binder/HwBinder 的上下文，以及媒体 prepare/reset 的空 renderer 访问。各项由独立模块处理，详见 [MIUI 应用兼容性](MIUI12_APP_COMPAT.md)。
- 下载字节已齐仍安装失败已缩小到文件收尾：补齐三个 truncate 路径入口，复用 `guestPath`；APK 构建刷新实际运行库，避免缓存带回旧实现。
- 使用下载 provider → 大小/哈希校验 → 客体包管理器这一条链路验收，完成必要检查后交付；原生文件系统回归在当前工作树通过 79 项。
- 开发者选项闪退由 MIUI WiFi 扩展查询缺失引起。补齐实际调用的查询与更新接口，沿用 ROM 动态 Binder 映射；v0.2.48 已安装，开发者选项与输入法页面绘制、异常检查通过。QQ 空间视频的图形连接退出仍独立排查。
- v0.2.49 修复带尾斜杠的新目录创建，恢复抖音 KEVA 状态保存的底层接口；文件系统当前通过 87 项检查。该问题会让应用重新启动时丢失同意状态，实际应用重开结果单独验收。
- 同版复现并修复 2048×2048 RGBA 加协议字段超过 16 MiB 上限导致的 GPU 退出；上限按需容纳 4096×4096 RGBA，保留超限和流边界校验。大纹理上传、像素读回、字幕透明度和媒体缓冲回归通过，实际 QQ 视频回放另行记录。
- v0.2.49 抖音重开直接进入视频流，隐私状态文件落盘，评论按钮打开面板。实际 4 次滑动基线为 50.18 FPS、P95 58.087 ms、最大 99.574 ms、3.804 核，连接数量为主 Binder 979、HwBinder 283。
- 6 秒 CPU 采样显示 Broker 循环与分发约占 32.5%，`poll` 及其锁操作明显，节点回收只占 3.22%。v0.2.50 将连接等待放入独立 `BrokerPoller`，使用持续的 level-triggered epoll，仅在发送队列阻塞状态变化时调整可写监听，保留立即回复、发送预算、连接身份与 Binder 分发语义。空闲时阻塞等待，SIGTERM 中断退出，不进行 100 ms 周期扫描。
- 768 个空闲连接、3000 次真实请求：旧版 0.429037 秒 / Broker CPU 0.41 秒，新版 0.163647 秒 / CPU 0.13 秒；吞吐从 6992 到 18332 次/秒。25 项独立进程通信回归、资源回收、输出背压排空与空闲零 CPU ticks 检查通过。该结果只证明 Binder 层，应用帧率和冷启动在安装版另行比较。
- v0.2.50 安装版实际抖音 4 次滑动为 69.06 FPS / P95 24.894 ms，仍有 331.899 ms 长帧；10 次滑动样本为 88.27 FPS / P95 24.893 ms / 最大 66.381 ms。桌面 4 次滑动为 59.33 FPS / P95 33.194 ms，含 531.089 ms 长间隔。CPU/热状态和网络内容未固定，不把样本改善等同于稳定 120 FPS。
- 该版 8 秒 CPU 采样中抖音与 QQ 的 ZIP 解压、DEX 结构校验突出，客体应用缓存目录实际缺失。MIUI 缓存输入使用了原 ROM `libdexfile`，且 Android 10 zygote 请求可能没有 `--app-data-dir`。v0.2.51 打包已有验证过的 DEX 缓存库，新增单一职责的 `AppDexCache`，按真实 UID 查询包管理器并使用 `ApplicationInfo.dataDir`，不按进程名猜目录。缓存留在包自己的 `code_cache` 内，清数据与卸载跟随 Android 原有目录生命周期。APK 更新、缓存损坏/截断、别名 FD、非法 DEX、只读映射与缓存不可用等 14 项检查通过，安装版命中与应用耗时另行记录。
- v0.2.51 已覆盖安装，抖音/QQ 分别确认 59/92 个 DEX 缓存映射，保留数据、强制停止后重开 WaitTime 为 2.342/3.284 秒；首次抖音缓存生成仍需 7.602 秒。抖音 4 次竖向滑动为 73.96 FPS / P95 33.190 ms / 最大 66.384 ms，MIUI 桌面 4 次左右滑屏为 93.63 FPS / P95 16.598 ms / 最大 24.896 ms。剩余长帧、首启与跨设备行为继续分别记录，详见 [性能结果](PERFORMANCE.md) 和 [结构化证据](evidence/app-performance-miui-v051.json)。
- v0.2.52 将 Binder 分发与输出改为状态变化驱动，线程注册按 context 查询；25 项 Binder、16 项 HwBinder、嵌套分发、背压、回收与多 context 检查通过。新包已覆盖安装，QQ/抖音重开为 1.881/2.419 秒；MIUI 4 次左右滑屏为 117.90 FPS / P95 8.300 ms，抖音 8 次滑动为 72.84 FPS / P95 33.194 ms，仍有 390.029 ms 间隔。新 CPU 采样定位到 `collectDeadNodes()` 的 36.42% 开销，下一步推进增量回收，详见 [v0.2.52 记录](evidence/app-performance-miui-v052.json)。
- v0.2.53 已覆盖安装，把节点回收改为候选队列与容器引用计数，回收不再扫描完整节点/句柄图。1.2 万保留节点的回收基准为 442795 → 531 ns，25 项 Binder、16 项 HwBinder、完整可达性对照和生命周期回归通过；实际 6 秒 CPU 采样中的回收占比为 36.42% → 0.02%。QQ/微信/抖音重开 WaitTime 为 1.279/1.616/2.221 秒，抖音 8 次滑动为 96.44 FPS / P95 16.599 ms / 最大 107.884 ms。前台恢复后的桌面样本为 97.41 FPS，仍有长间隔；热状态和内容未固定，未证明所有场景稳定 120 FPS或整体发热下降。后续热点为通信内核开销和视频 YUV/RGB 转换，详见 [v0.2.53 记录](evidence/app-performance-miui-v053.json)。
- v0.2.46 的应用商店 8 次滑动样本为 88.92 FPS、P95 16.595 ms；它是历史实际 Surface 呈现样本，120 Hz 配置与持续实际帧率分开。最新 APK 验收结果见 [交付证据](evidence/miui12-apk-release.json)。

## 实施记录（2026-10-10，v27）

下面的原始方案保留用于追溯；本节记录按当前源码和运行时证据采用的修正。

- v26 本会话退化基线为 5.45 FPS、P95 389.979ms。主 broker 的 6 秒
  `cpu-clock` 采样共 23671 个样本，`collectDeadNodes()` 占 30.89%；树平衡、
  分配和释放也占明显份额。原有集合化修复仍在，但每条 Read/Command 都重建树集合。
- 已保持同一可达性判定，进一步用节点代际标记替代临时树集合，只有释放引用、
  导出新节点或进程退出使集合变脏时才回收。定向回归验证零堆分配、所有保活条件、
  handle/死亡通知/待确认引用释放及嵌套 dispatch 语义。
- P0-1 原假设已被现场证据否定：普通应用 CapEff=0，但 `RLIMIT_NICE=40`，
  `a10-input`/`a10-compositor` 实际 nice=-4。保留此设置和 worker nice=0，
  新增设置返回值及实际 nice 的一次性日志；不按原文将 worker 一律降到 +5。
- P0-2 改为 worker 完成通知 + listener 及时 join；停止服务时仍关闭连接并等待
  所有 worker。原文直接 detach 且析构不等待的方案存在后端生命周期问题，未采用。
- P0-3 保留释放 GPU registry/root context 后再 swap 的锁边界。`rcColorBufferCacheFlush`
  新增计数和 root/guest 排序，CPU lock 的同步仍保留；按实际调用率决定后续优化。
  v26 已有 GPU fence，原文两个承重 `glFinish` 的描述对应旧代码。
- P1-1 采用绝对单调时钟期限，EINTR 重试、退出和落后跳帧均处理；回调快照改用
  device 的 callback mutex。`eglSwapBuffers` 返回不是物理呈现完成，不采用该
  返回直接充当宿主 vsync 的建议。
- P1-2 已接入 swap interval 请求；1080×1920、480 dpi、120Hz 配置不变。
- P2-1 当前包已有 79 个系统 APK，该条不重复扩充。P2-2 新增 spawn/entry/ready
  单调时钟计时，boot image/真 zygote 独立后续推进，不与稳态修复混改。
- P2-4 已把 `task_profiles.json` / `cgroups.json` 纳入 system assets；缺失文件错误已消失，
  但普通应用命名空间没有可用 cgroup controller，`JoinCgroup` 仍不能作为调度提升证据。
- P2-5 framework/ART 测试夹具与生产 JIT 启动参数对齐。
- 本版验收已完成：覆盖安装、3 次实际 Surface 采样、10 次切换、冷启计时和持续触摸；
  证据路径见 `docs/PERFORMANCE.md` 的 v27 实机结果。
- 3 次设置滑动：98.40/102.90/100.69 FPS，P95 均约 16.60ms，最大间隔
  49.791/24.896/24.897ms；FPS 极差按最大值归一为 4.37%，达到本次 P95/稳定性指标。
- 残余项：broker 12 个 2 秒窗口为 4–20 CPU ticks，12/13 次状态为 `S`（窗口终点
  11/12 为 `S`）；严格的每窗口 ≤4 ticks 指标尚未达成。热状态/后台进程未被控制。
- 本轮未修改堆参数、分辨率、boot image 或 zygote，不把未证实的 GC/宿主相位猜测
  作为改动依据。后续用冷启计时推进 ART 镜像/预热，保留本版作可试用基线。

---

## 0. 先读这一节：已经修好的，别重复劳动

**Binder broker 用户态自旋（已修复，已实测验证）**

- 位置：`container-probe/binder/native/BrokerCleanup.cpp` → `Broker::collectDeadNodes()`
- 原实现是 `for (每个 node) { for (每个进程) { for (每个 handle) } }`，即 **O(nodes × 进程 × handles)**，且由 `Broker.cpp:138` 在**每处理完一条 binder 命令后**调用一次。
- 实测后果（`simpleperf record -p <broker> --duration 6`）：**19552 个样本中 16012 个（82.02%）落在 `collectDeadNodes()`**，而 `Broker::run()` 仅 0.22%、`dispatch()` 仅 0.18%。
- 症状链：broker 单线程 state=`R`、`/proc/PID/io` 的 `syscr=18 / syscw=1` **完全冻结**（因为它回不到 `poll()`）、`/proc/PID/syscall` 采样 11/12 次为 `running`。guest system_server 因 binder 停滞触发 Watchdog，60 秒后 `*** GOODBYE!` → `SIG: 9`，`DesktopCheck` 报 `DeadObjectException` + `Bad file descriptor`。这就是用户感知的「非常卡 / 进入应用卡顿」。
- v26 已改为一次性汇总被引用节点集合；v27 继续改为节点代际标记和 dirty gate，
  只在引用生命周期变化时扫描；由于 `nodes` 为 `std::map`，扫描复杂度为
  **O(nodes + 引用数 × log(nodes))**，且零堆分配，语义等价（`contextNode`、
  strong/weak/pending/asyncBusy/asyncQueue 判定全部保留）。
- 修复后实测：broker `state=S`，连续 12 个 2 秒采样窗口 `du=0~1 / ds=0~1`（即**几乎不占 CPU**），`binder_transactions` 从 15848 涨到 23789（同样的墙钟时间做了更多实事）。

**截至 v27 的检查点**：`collectDeadNodes()` 应有 `deadNodesDirty_` gate、
  `referencedGeneration` 标记和溢出回绕处理；不要恢复每次调用都创建 `std::set` 的实现。

其余已修复项（不要回退）：

| 项 | 位置 | 状态 |
| --- | --- | --- |
| ART 解释器模式移除 | `guest-runtime/src/.../FrameworkSession.java`、`GuestRuntime.java:141` | 7 处 `-Xint -Xusejit:false` 已删，仅保留 `-Xnoimage-dex2oat` |
| 触摸历史样本放大 | `native-display/.../WindowBridge.java` | 删掉了「重放 N 个历史样本」的循环，只转发当前位置 |
| 触摸队列满抛异常 | `container-probe/graphics/window/TouchQueue.h` | 满队列改为丢弃最旧 Move，不抛（原会崩 UI 线程） |
| 输入通道 read==0 空转 | `guest-runtime/check/DesktopInput.java` | 加 `read <= 0` 判定 |
| netd 未实现方法 | `guest-runtime/check/GuestNetworks.java` | 改为 no-op 返回，避免 ConnectivityService BOOT FAILURE |
| `eglSwapInterval` 设错 surface | `container-probe/graphics/desktop/DesktopPresenter.cpp:74` | 已改为在 window surface 上设 |
| 2 个承重 `glFinish` | `container-probe/graphics/desktop/GpuBackend.cpp` | 跨 context 可见性屏障，**不要删** |
| 解释器专项夹具 | `guest-runtime/test-jit.py` | 仅保留作为对照基准；生产/集成夹具已与 JIT 启动参数对齐 |

---

## 1. 实测基线与测量工具

### 1.1 当前性能数字（来自 `docs/PERFORMANCE.md`，需重测）

| 样本 | FPS | 中位帧间隔 ms | P95 ms | UID 进程 CPU 核数 |
| --- | ---: | ---: | ---: | ---: |
| 基线 | 16.81 | 58.091 | 74.698 | 1.689 |
| 新版 | 33.17 | 33.198 | 41.503 | 4.212 |
| 新版重复 | 12.55 | 66.401 | 174.301 | 1.678 |

**重复样本波动极大（33 → 12.5 FPS）**，这说明当前瓶颈不是稳定吞吐，而是**间歇性停顿**。所有优化必须以 P95 / 最大帧间隔为准，平均值会骗人。

### 1.2 可用工具

```sh
# 宿主侧函数级采样（权威，别再靠读代码猜）
su -c "cd /data/local/tmp && simpleperf record -p <PID> --duration 6 -o perf.data"
su -c "simpleperf report -i /data/local/tmp/perf.data --sort comm,symbol -n"

# 进程 CPU 精确测量（USER_HZ=100，du+ds=200 表示满一个核）
su -c "cat /proc/<PID>/stat"   # 字段 3=state, 14=utime, 15=stime
su -c "cat /proc/<PID>/io"     # syscr/syscw 冻结 = 用户态空转，不是 IPC 风暴
su -c "cat /proc/<PID>/syscall"  # 反复采到 "running" = 在算；"73" = ppoll

# 帧率
tools/measure-desktop-performance.py --label <tag> [--swipes 8]

# 找 guest 进程（NAME 列被截断到 15 字符，不要用 ps grep）
# 用 /proc/*/cmdline 匹配 /data/app/*liba10vm-*
```

**测量纪律**：`/proc/PID/io` 的 `syscr`/`syscw` 是区分「空转」和「真忙」的关键。`poll`/`ppoll`/`accept4`/`close` **不计入**这两个计数器 —— 所以「CPU 高 + 计数器冻结」= 用户态循环或 poll 立即返回，而不是 I/O 瓶颈。

---

## 2. 目标与因果链

用户诉求拆成三条独立链路，**不要混着改**：

```
【A. 进应用卡顿】首次打开 App 慢 → ART 无 AOT + 无 zygote 预加载 + dexopt=verify
【B. 刷新率】guest 报 120Hz 但节奏与宿主不对齐 → 自身定时 vsync + 每帧 context 切换
【C. 流畅度】稳态掉帧（P95 高）→ 逐帧同步点过多 + 线程优先级未生效 + guest 堆偏小
```

建议实施顺序：**P0（C 的同步点）→ P1（B 的 vsync 对齐）→ P2（A 的启动加速）**。
理由：P0 改动最小、风险最低、对 P95 影响最直接；P2 改动最大且需要重新打包镜像。

---

## 3. P0 —— 稳态流畅度（预计 1 天，风险低）

### P0-1 线程优先级实际上没生效（先验证）

**位置**：`container-probe/graphics/desktop/DesktopThread.h`

```cpp
inline void configure(const char* name, int priority = 0) {
    pthread_setname_np(pthread_self(), name);
    setpriority(PRIO_PROCESS, 0, priority);   // ← 返回值被丢弃
}
```

调用点（注意都是负值）：
- `DesktopDecoder.cpp:201` → `desktopthread::configure("a10-compositor", -4)`
- `DesktopInputChannel.cpp:58` → `desktopthread::configure("a10-input", -4)`
- `DesktopGpuServer.cpp:68` / `:101` → 默认 0

**问题**：app 以 `untrusted_app` UID 运行，实测 `cap_eff = 0000000000000000`。
**降低 nice 值（负值）需要 `CAP_SYS_NICE`，必定 `EPERM`**，而返回值没人检查 —— 所以合成线程和输入线程的优先级**从来没生效过**，文档和注释却写成了「已调优」。

**改法**：

1. 先取证，不要直接改：

```cpp
inline void configure(const char* name, int priority = 0) {
    pthread_setname_np(pthread_self(), name);
    if (priority >= 0) { setpriority(PRIO_PROCESS, 0, priority); return; }
    // Negative nice needs CAP_SYS_NICE; the guest runs as untrusted_app with cap_eff=0,
    // so record the refusal once instead of silently pretending the hint applied.
    if (setpriority(PRIO_PROCESS, 0, priority) != 0)
        __android_log_print(ANDROID_LOG_WARN, "a10vm", "thread %s nice=%d refused: %s",
                            name, priority, strerror(errno));
}
```

2. 接受「优先级提不上去」这个事实，改为**减少竞争资源**：
   - 把 `a10-gpu-worker`（每个 GPU 连接一个线程，见 P0-2）的默认 nice 设为 **+5**（正值正权限可以设），把 `a10-compositor` / `a10-input` 留在 0，用**相对差**达到同样的目的。
   - 宿主侧 `VmService.kt:87 / :117` 已经在用 `Process.setThreadPriority`（Java 层，同 UID 内有效），保持一致。

**验证**：

```sh
# 启动 VM 后读取真实 nice 值（字段 19）
su -c 'for d in /proc/[0-9]*/task/[0-9]*; do s=$(cat $d/stat 2>/dev/null) || continue; \
  n=$(echo "$s" | sed "s/.*(\(.*\)).*/\1/"); case "$n" in a10-*) echo "$n $(echo $s | awk "{print \$19}")";; esac; done' | sort -u
```

预期：`a10-compositor` / `a10-input` 为 0（提不上去，但已记录），`a10-gpu-worker` 为 +5。
**如果所有 a10-* 线程 nice 全是 0 且日志里没有 warning，说明补丁没生效。**

**收益**：消除合成线程被解码线程抢占导致的周期性掉帧。**风险**：无。

---

### P0-2 GPU 服务每连接一线程，且永不回收

**位置**：`container-probe/graphics/desktop/DesktopGpuServer.cpp`

```cpp
// run() 里，每 accept 一个新连接就起一个线程
decoders_.emplace_back([this, fd] { client(fd); });   // :95
...
// client() 结束时只从 clients_ 里删 fd，线程对象留在 decoders_ 里
std::lock_guard<std::mutex> lock(mutex_);
clients_.erase(fd);                                    // :112
```

**问题**：
1. `decoders_` 是 `std::vector<std::thread>`，`emplace_back` 后**从不 join 已结束的线程**，只在整个 server 析构时才 join（`:39`）。guest 每次重连（surface 重建、app 重启、`DesktopCheck` 探测）都泄漏一个 joinable thread 对象。
2. guest 有 20+ 个进程，每个都可能建立 GPU 连接 → 线程数持续增长 → 调度压力上升。
3. 这些 worker 线程默认 nice=0，与合成/输入线程同权（见 P0-1）。

**改法**（最小且正确）：

```cpp
// client() 末尾：线程自己 detach，而不是把 joinable 线程堆进 decoders_
}  // 去掉 decoders_ 成员，改为：
decoders_.emplace_back([this, fd] { client(fd); });
decoders_.back().detach();
```

同时把 `decoders_` 从 `std::vector<std::thread>` 改为计数（`std::atomic<int> decoders_`），析构时不 join。**注意**：析构顺序仍需保证 `closing_` 先置位、`clients_` 里的 fd 先 shutdown，再让线程自然退出。

**验证**：

```sh
# 反复切换 管理页 <-> 全屏 10 次，观察线程数是否单调增长
su -c "ls /proc/<gpu-server-pid>/task | wc -l"   # 不应随切换次数增长
```

**收益**：消除长时间运行后的线程泄漏与调度抖动。**风险**：低（需确认 detach 后线程仍能安全访问 `backend_`，用 `closing_` + `shared_ptr` 或确保对象生命周期覆盖线程即可）。

---

### P0-3 每帧一次 `eglMakeCurrent` 上下文切换 + 一次 `glFinish`

**位置**：`container-probe/graphics/desktop/DesktopPresenter.cpp` / `GpuBackend.cpp`

现状（每帧执行）：

```cpp
// DrawPresenter::draw()  →  GpuBackend::post() :388
std::lock_guard<std::mutex> posting(postMutex_);
{
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    Current current(*this);
    presenter_->draw(buffer.texture);     // blit + glFlush
    sampledColor(buffer);                 // ← 等上一帧的 fence，再建新 fence
    ...
}
presenter_->swap();                        // ← 拿走 swapContext_，eglSwapBuffers，再换回
```

`swap()` 内部（`:102`）：

```cpp
auto context = eglGetCurrentContext();
auto draw = eglGetCurrentSurface(EGL_DRAW), read = eglGetCurrentSurface(EGL_READ);
EGLBoolean result = eglMakeCurrent(display_, surface_, surface_, swapContext_);  // 切换
if (result) result = eglSwapBuffers(display_, surface_);
eglMakeCurrent(display_, draw, read, context);                                    // 切回
```

外加 `DesktopDecoder.cpp:186`：

```cpp
rc_.rcColorBufferCacheFlush = [](uint32_t, EGLint, int) -> EGLint { glFinish(); return 0; };
```

**问题**：
1. **每帧两次 `eglMakeCurrent`**：driver 内部要刷新状态、重建 current 绑定，在 GLES 上是毫秒级开销。
2. `sampledColor()` 每帧 `waitFence(上一帧)` —— 这是**故意的 1 帧流水**，本身合理，但它把 GPU 与 CPU 串成严格的 1 帧深，任何抖动都会直接变成丢帧。
3. `rcColorBufferCacheFlush` 的**无条件 `glFinish()`** 是整条管线停顿：调用点若在合成路径上，直接杀掉流水并行。

**改法（按优先级）**：

1. **先确认 `rcColorBufferCacheFlush` 的实际调用频率**。加计数：

```cpp
rc_.rcColorBufferCacheFlush = [](uint32_t, EGLint, int) -> EGLint {
    static std::atomic<uint64_t> calls{0};
    ++calls;
    glFinish(); return 0;
};
```

   若每帧 >1 次 → 这是 P0 的一号目标。**改为 fence 等待而非全管线停顿**（仓库已有 `GpuBackend::fence()` / `waitFence()`，直接用）。

2. **消除 `swap()` 的 context 往返**：根因是用独立 `swapContext_` 做交换。可以改成在 present 前一次性 `eglMakeCurrent(display_, surface_, surface_, context_)` 并**保持 current 到 swap 之后**，去掉 `draw/read/context` 的保存恢复。需要确认 `swapContext_` 存在的原因（大概是避免 blit 用的 context 与 swap 争用）—— **保留 `swapContext_` 但不要每帧切换**，改成只在 `bind()`（surface 变化）时切一次。

**验证**：

```sh
# 采样中 glFinish / eglMakeCurrent 占比应显著下降
su -c "simpleperf record -p <gpu-host-pid> --duration 6 -o p.data && simpleperf report -i p.data --sort symbol -n" | head -30
```

对照项：`eglMakeCurrent`、`glFinish`、`__eglMustCastToProperFunctionPointerForHW` 等符号占比。
另外看 `desktop_gpu_frame=` 日志行的间隔（`GpuBackend.cpp:371` 每 120 帧打一次）是否稳定。

**收益**：直接降低 P95 帧间隔。**风险**：中 —— 动 current 绑定可能引起状态错乱，**必须逐帧比对像素**（`tools/measure-tap.py` + `readPresentedPixel`）。

---

### P0-4 guest Java 堆偏小

**位置**：`guest-runtime/native/guest.prop:13-15`

```properties
dalvik.vm.heapstartsize=16m
dalvik.vm.heapgrowthlimit=128m
dalvik.vm.heapsize=256m
```

**问题**：guest 里跑 `system_server` + `Launcher3` + `SystemUI` + Settings + 各 app。128m 的 growth limit 会触发频繁 GC，GC 停顿在 120Hz（8.3ms/帧）下极易丢帧。

**改法**：宿主是 23GB 内存的机器，guest 侧放宽：

```properties
dalvik.vm.heapstartsize=32m
dalvik.vm.heapgrowthlimit=256m
dalvik.vm.heapsize=512m
```

**注意**：`GuestRuntime.java:73` 用 `dataHash("guest-runtime/guest.prop")` 做种子缓存（`seed_inputs=`），改完 prop **必须让种子失效**（删掉 `files/guest-runtime/seed.log` 或让哈希变化自动触发重建）。这是设计如此，不要绕过。

**验证**：guest logcat 里 `GC` / `Background concurrent copying GC` 行数应下降。

```sh
su -c "grep -c 'GC' /data/data/io.a10vm/files/guest-runtime/framework-server.log"
```

**收益**：减少 GC 引起的周期性丢帧。**风险**：低（注意不要超过宿主可用内存）。

---

## 4. P1 —— 刷新率与帧节奏（预计 2 天，风险中）

### P1-1 guest vsync 是自己定时睡的，和宿主不对齐

**位置**：`artifacts/container/graphics/desktop/derived/hwc2/EmuHWC2.cpp:1157`（`VsyncThread::threadLoop`）

```cpp
struct timespec wait_time;
wait_time.tv_sec = 0;
wait_time.tv_nsec = mDisplay.mVsyncPeriod;      // = 8333333 ns（120Hz）

while (!exitPending()) {
    int err = nanosleep(&wait_time, NULL);      // ← 相对睡眠，不扣掉本次循环耗时
    ...
    clock_gettime(CLOCK_MONOTONIC, &rt);
    int64_t timestamp = int64_t(rt.tv_sec) * 1e9 + rt.tv_nsec;
    vsync(callbackInfo.data, mDisplay.mId, timestamp);   // 把时间戳发给 guest 合成器
}
```

配置来源：`artifacts/container/graphics/desktop/derived/hwc2/EmuHWC2.cpp:407`

```cpp
mVsyncPeriod(desktopdisplay::vsyncNanos),   // DesktopDisplay.h: vsyncNanos = 1000000000 / refreshHz
```

`DesktopDisplay.h`：

```cpp
constexpr int width = 1080;
constexpr int height = 1920;
constexpr int density = 480;
constexpr int refreshHz = 120;
constexpr int vsyncNanos = 1000000000 / refreshHz;   // 8333333
```

**问题（两层）**：

1. **相对睡眠导致周期漂移**：`nanosleep(8.333ms)` 之后还要执行 `clock_gettime` + 回调派发，实际周期 = 8.333ms + 循环体耗时。没有「扣掉已用时间」的逻辑，所以 guest vsync 会**系统性慢于** 120Hz，且随负载变化。
2. **与宿主 vsync 无相位关系**：guest 合成器的 vsync 由这个自由运行的线程产生，宿主 SurfaceFlinger 有自己的 120Hz vsync。两者频率相同但相位漂移 → **拍频（beat）**：周期性出现「guest 恰好赶上宿主 vsync」和「刚好错过」的交替，表现为**肉眼可感的规律性顿挫**。这正好解释 PERFORMANCE.md 里 33 FPS 与 12.5 FPS 的巨大波动。

**改法（分两步，先易后难）**：

**第一步（低风险，立刻可做）**：把相对睡眠改成绝对期限调度。

```cpp
// 预先算好下一个期限，睡眠只睡「距离期限还差多少」，循环体耗时自动被扣掉。
struct timespec next;
clock_gettime(CLOCK_MONOTONIC, &next);
while (!exitPending()) {
    addNanos(&next, mDisplay.mVsyncPeriod);
    clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
    ...
}
```

注意仍需处理：`mVsyncEnabled` 为 false 时不派发、`EINTR` 时的行为、以及长时间挂起后 `next` 落后于当前时间需要跳帧补齐。

**第二步（根治）**：让 guest vsync 由**宿主 present 完成**驱动，而不是自己定时。
`GpuBackend::post()` 在 `presenter_->swap()` 返回后即为「宿主已接受这一帧」，此时通过现有的回调链向下发 vsync。这样 guest 合成器与宿主严格同相位，拍频消失。
**代价**：需要确认 guest 侧 `HWC2_PFN_VSYNC` 回调的下游（`SurfaceFlinger` 的 `VsyncThread`/`Scheduler`）能接受「present 反馈驱动」而非「固定周期驱动」，可能要在 guest SF 侧配合改 `hwc.patch`。

**验证**：

```sh
# 1. 帧间隔分布（关键指标：P95 与最大间隔）
tools/measure-desktop-performance.py --label vsync-absolute

# 2. 从 guest 侧读 HWC 上报的 vsync 周期
#    见 DesktopDecoder.cpp:155 (rcGetFBParam case 5) 与 WindowJni.cpp:27
#    1080×1920 / 120.00001 Hz 是当前上报值（见 PERFORMANCE.md 表格）

# 3. 连续跑 3 次，看 FPS 方差是否收敛
```

**判据**：三次测量 FPS 极差 < 15%（当前极差 33→12.5 = 62%）。
**风险**：中。第一步纯本地、可回退；第二步涉及 guest SurfaceFlinger，需单独分支。

---

### P1-2 guest 请求的 swap interval 被丢弃

**位置**：`container-probe/graphics/desktop/DesktopDecoder.cpp:206`

```cpp
rc_.rcFBSetSwapInterval = [](EGLint) { };   // ← 空实现，guest 的请求被吞掉
```

同时宿主侧 `DesktopPresenter.cpp:74` 无条件下 `eglSwapInterval(display_, 1)`。

**问题**：guest 合成器可能请求 swap interval 0（非阻塞呈现），宿主却强制 1。语义不一致 → guest 以为呈现是异步的，实际每帧都在 vsync 上阻塞 → 阻塞点出现在 guest 合成线程里，表现为 `a10-compositor` 线程被阻塞而其他线程空转。

**改法**：把 guest 的请求透传到 `eglSwapInterval`，而不是硬编码 1。

```cpp
rc_.rcFBSetSwapInterval = [](EGLint interval) {
    current_->backend_.setSwapInterval(interval);
};
```

在 `GpuBackend` 里加一个 `std::atomic<int> swapInterval_`，`DesktopPresenter::bind()` 里用它替代硬编码的 `1`。

**验证**：guest log 里不应再出现重复的 `IPCThreadState: mOut.dataSize() > 0 after flushCommands()`（当前 framework-server.log 里有**大量连续**出现，是写入未被消费的直接症状）。

```sh
su -c "grep -c 'mOut.dataSize() > 0 after flushCommands' /data/data/io.a10vm/files/guest-runtime/framework-server.log"
```

**风险**：低。若 guest 请求 0 导致撕裂，可回退为透传但下限 1。

---

### P1-3 分辨率不匹配：1080×1920 → 1440×3168

**位置**：`container-probe/graphics/desktop/DesktopDisplay.h`（1080×1920）、宿主实际 1440×3168。

**问题**：
- 宽高比不同（9:16 = 0.5625 vs 1440:3168 ≈ 0.4545），宿主窗口必须做 letterbox（`NativeSurfaceView.java` 的 `onMeasure`）。
- 每帧 blit 都要**缩放**：`DesktopPresenter::blit()` 用 `glViewport(0,0,width_,height_)` 直接拉伸纹理到整个窗口，非整数倍缩放 → 采样开销 + 边缘锯齿。

**改法（二选一）**：

- **A（低成本）**：把 `width/height` 改成 **1440×3168**，消除缩放。代价是 guest 侧渲染面积增大 2.1 倍，GPU 负载上升 —— 在当前「卡」的前提下**不建议**。
- **B（推荐）**：保持 1080×1920，但让宿主窗口 **保持整数比**（如 2:1 letterbox 或用 `glViewport` 做像素对齐的最近邻）。改 `NativeSurfaceView.onMeasure` 的 letterbox 计算为「按整数倍缩放」。
- **C（备选）**：把 guest 分辨率改为 **1080×2376**（宿主 mode 4/5/6/7 的分辨率，见 `dumpsys SurfaceFlinger`），两边宽高比一致，缩放退化为纯整数倍。

**验证**：`dumpsys SurfaceFlinger` 的 `activeMode`；宿主侧抓 SurfaceFlinger 时间戳的帧间隔。

**风险**：A 明确会导致更卡，别选。B/C 低风险。

---

## 5. P2 —— 应用启动卡顿（预计 3–5 天，风险高）

这是「**为什么只有设置一个应用 / 进应用很卡**」的根因区。

### P2-1 只有 10 个 APK 被打包（当前只有 Settings 可见）

**现状**：`artifacts/container/desktop/inputs.json` 的 `packages` 只声明 10 个：

```json
{
  "framework":          "/system/framework/framework-res.apk",
  "launcher":           "/system/product/priv-app/Launcher3QuickStep/Launcher3QuickStep.apk",
  "systemui":           "/system/product/priv-app/SystemUI/SystemUI.apk",
  "settingsProvider":   "/system/priv-app/SettingsProvider/SettingsProvider.apk",
  "settings":           "/system/product/priv-app/Settings/Settings.apk",
  "permissionController": "/system/priv-app/PermissionController/PermissionController.apk",
  "packageInstaller":   "/system/priv-app/PackageInstaller/PackageInstaller.apk",
  "shell":              "/system/priv-app/Shell/Shell.apk",
  "extServices":        "/system/priv-app/ExtServices/ExtServices.apk",
  "extShared":          "/system/app/ExtShared/ExtShared.apk"
}
```

镜像里有 **114 个 .apk**。所以 Launcher 里只有 Settings。

**改法**：扩充 `packages`，把启动必需的系统应用补进来（**不要全量**，先补关键集）：

- `com.android.providers.settings`（SettingsProvider 已有）
- `com.android.providers.media.module`
- `com.android.providers.downloads`
- `com.android.documentsui`
- `com.android.bluetooth` / `com.android.nfc`（按需）
- `com.android.webview`（若需要浏览器能力，见 P2-4 的 WebView 预加载）

**关键约束**：放在 **assets**，**绝不能放 `lib/<abi>/`**。原因：包管理器会解析 `lib/arm64-v8a/` 下所有文件的 ELF 头，非 ELF 内容会触发 `INSTALL_FAILED_NO_MATCHING_ABIS (res=-113)`。之前把整镜像塞进 `lib/` 导致 APK 无法安装（765MB，1600 个 lib 条目全部是合法 aarch64 ELF，仍装不上）—— **这条路已被证伪，不要再试**。

**验证**：

```sh
# 打包后确认 APK 可安装
su -c "pm install -r <apk>"          # 期望 "Success"
# 确认 lib/ 下只有 .so
python3 -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); \
  print([n for n in z.namelist() if n.startswith('lib/') and not n.endswith('.so')])" <apk>
# 确认 guest 侧 APK 数量
su -c "ls /data/data/io.a10vm/files/guest-runtime/rootfs/system/{app,priv-app,product/priv-app}/*/*.apk | wc -l"
```

**风险**：中高（APK 体积、安装成功率）。**务必先跑 `pm install` 验证再继续。**

---

### P2-2 没有 zygote：每个 app 冷启一个完整 `app_process64`

**位置**：`guest-runtime/check/AppLaunch.java`（完整源码见仓库）

```java
List<String> command = new ArrayList<>();
command.add(System.getenv("A10VM_EXEC_LINKER"));        // ld-android.so
command.add(System.getenv("A10VM_APP_PROCESS"));        // app_process64
command.add("-Xnoimage-dex2oat");                       // ← 每次冷启都无镜像运行
command.add("-Djava.library.path=" + System.getenv("A10VM_LIBRARY_PATH"));
command.add("/system/bin");
command.add("--application");
command.add("--nice-name=" + name);
command.add("io.a10vm.guest.GuestApplication");
command.add(sdk);
...
Process child = builder.start();                        // fork + exec 全新进程
```

而 `DesktopProcesses.java:30` 虽然绑了 `/dev/socket/zygote`：

```java
start(new LocalSocketAddress("/dev/socket/zygote", LocalSocketAddress.Namespace.FILESYSTEM), 0, Integer.MAX_VALUE);
```

但 `accept()` 收到连接后走的是 `AppLaunch.start(arguments, ++sequence)` → `ProcessBuilder.start()`，**这是 fork+exec，不是 zygote 的 fork-from-warm-parent**。所谓 `--preload-default` 也只是 `output.writeInt(1)`，没有任何预加载。

**后果**：每开一个 app 都要付出：加载私有 linker → 加载 ART → 加载 boot classpath jar → 校验 dex → 解释执行框架类 → 然后才是 app 自己的类。这就是「**进入应用卡顿**」最大的单项成本。

**改法（分阶段）**：

1. **先量化**：在 `AppLaunch.start()` 前后加时间戳，写进 `application-<pid>-<seq>.log`：

```java
long t0 = System.nanoTime();
Process child = builder.start();
System.out.print("desktop_application_spawn_ms=" + (System.nanoTime()-t0)/1000000 + "\n");
```

   再在 `GuestApplication.main()` 首次进入时打 `guest_application_ready_ms=`。两者之差 = 冷启成本。

2. **短期（低风险）**：用**绝对启动镜像**替代 `-Xnoimage-dex2oat`。
   镜像里已有完整的 AOT 产物（`artifacts/container/rootfs-arm64/system/framework/arm64/`）：

   | 文件 | 大小 |
   | --- | ---: |
   | `boot.art` | 2.7M |
   | `boot.oat` | 3.6M |
   | `boot-framework.art` | 9.2M |
   | `boot-framework.oat` | 13M |
   | `apex-framework.art` / `.oat` | 9.2M / 640k |
   | `apex.art` / `apex.oat` | 2.7M / 3.6M |
   | 其余（core-libart / conscrypt / okhttp / bouncycastle / ext / ext 等） | ~3M |

   合计约 **29 MB**。这些目前**完全没有被打包**（`-Xnoimage-dex2oat` 明确禁用了镜像）。
   做法：把这批 `.art`/`.oat`/`.vdex` 按原路径放进 **assets** 解包到 guest rootfs，然后把 `-Xnoimage-dex2oat` 换成 `-Ximage:/apex/com.android.runtime/etc/boot-image...`（具体 flag 需按 ART 版本确认，见下）。
   **注意**：`dex2oat` 是 32 位 ARM，在 arm64-only 环境**不可用**，所以只能**复用镜像里现成的 AOT 产物**，不能在设备上重新生成。

3. **中期（中风险）**：真正的 zygote。
   把 `DesktopProcesses` 从「fork+exec 每个 app」改为「预热一个 zygote 进程，app 通过 socket 请求 fork」。
   现有骨架已经在了（`/dev/socket/zygote` 已绑定、`--start-child-zygote` 已有处理、`GuestChildZygote.java` 已有），缺的是**主 zygote 的 fork 语义**。
   这一步收益最大，但涉及进程身份切换（`--setuid`）与 binder 线程池在新进程里的重建，**建议单独立项**。

**验证**：

```sh
# 冷启耗时（改动前后对比）
su -c "grep 'desktop_application_spawn_ms' /data/data/io.a10vm/files/guest-runtime/application-*.log | tail -20"

# 端到端：从点击到首帧
tools/measure-tap.py
```

**风险**：高。ART 镜像的 flag 名称与校验和必须与 guest 的 `libart.so` 完全匹配，否则 ART 会拒绝加载并回退解释执行（比现在更慢）。**先用 `test-app-launch.py` 做隔离验证，不要直接上真机。**

---

### P2-3 `pm.dexopt.*=verify`：所有应用都不做 AOT

**位置**：`guest-runtime/native/guest.prop:16-22`

```properties
pm.dexopt.first-boot=verify
pm.dexopt.boot=verify
pm.dexopt.install=verify
pm.dexopt.bg-dexopt=verify
pm.dexopt.ab-ota=verify
pm.dexopt.inactive=verify
pm.dexopt.shared=verify
dalvik.vm.dex2oat-filter=verify
```

**问题**：`verify` 只做校验、不生成机器码，所以每个 app 的**每次启动**都要走 JIT 预热。
配合 `dalvik.vm.usejit=true`（`guest.prop:11`，已启用，保留），首帧后的几秒会持续编译，表现为「**打开后前几秒特别卡，之后才顺**」。

**改法**：
- **保守**：`pm.dexopt.install=speed-profile`、`pm.dexopt.first-boot=speed`。前提是 `dex2oat` 可用 —— **当前不可用**（32 位 ARM），所以这条**在修好 dex2oat 之前走不通**。
- **可行替代（推荐）**：利用 P2-2 的 boot image。boot image 提供了**框架类**的 AOT，app 自己的 dex 仍靠 JIT，但栈上大部分时间在框架里，收益已经很大。
- **降低 JIT 阈值**：加 `dalvik.vm.jitthreshold=1000` 之类，让热点方法更快被编译（需实测，可能适得其反）。

**验证**：`grep -c 'JIT' framework-server.log`；冷启到首帧的耗时分布。

**风险**：低（改属性），但**收益依赖 P2-2**。

---

### P2-4 `task_profiles.json` / `cgroups.json` 没被打包

**位置**：镜像里有，打包产物里没有。

```sh
# 镜像里有
artifacts/container/rootfs-arm64/system/etc/task_profiles.json   # 9.0k
artifacts/container/rootfs-arm64/system/etc/cgroups.json         # 905

# 打包输出里没有（staged payload 的 system/etc 只有 permissions/security/... 没有 .json）
ls guest-runtime/build/prepared/assets/guest-runtime/rootfs/system/etc/
```

**后果**（guest log 实证）：

```
GUEST_LOG 6 libprocessgroup: CgroupMap::LoadRcFile called for [9337] failed
GUEST_LOG 6 libprocessgroup: Failed to read task profiles from /etc/task_profiles.json
GUEST_LOG 6 libprocessgroup: Loading /etc/task_profiles.json for [9337] failed
GUEST_LOG 5 libprocessgroup: Failed to find HighPerformancetask profile: No such file or directory
GUEST_LOG 5 libprocessgroup: Failed to find TimerSlackNormaltask profile: No such file or directory
```

AMS 想给前台应用设 `HighPerformance` profile 却找不到文件 → **前台应用拿不到应有的调度提升**，与 P0-1 的 nice 失败叠加，前台 app 和后台服务同权竞争。

**改法**：把这两个文件加入 `stage.py` 的打包清单（走 assets，与其它 `system/etc` 文件一样的路径规则）。

**验证**：

```sh
su -c "ls /data/data/io.a10vm/files/guest-runtime/rootfs/system/etc/task_profiles.json"
su -c "grep -c 'task_profiles.json' /data/data/io.a10vm/files/guest-runtime/framework-server.log"   # 应为 0
```

**收益**：前台 app 调度提升可能真正生效。**风险**：低。

---

### P2-5 测试夹具仍在用生产已废弃的模式

**位置**：以下文件硬编码 `-Xint -Xusejit:false`，而生产代码早已移除：

- `guest-runtime/test-system-server.py:126,197`
- `guest-runtime/test_desktop_support.py:53,98,110`
- `guest-runtime/test-fonts.py:25`

**问题**：集成测试**测的不是生产配置**。任何 JIT/性能相关的回归都测不出来 —— 这正是之前「JIT 微基准 6.49×」被错误外推到生产的原因（该基准跑的是 `dalvikvm64` 而非 `app_process64`）。

**改法**：把这三个文件里的 `-Xint -Xusejit:false` 删除，与 `FrameworkSession.java:194` 的 `command()` 保持一致（只留 `-Xnoimage-dex2oat`，或按 P2-2 的结果替换）。

**验证**：`python3 -m pytest guest-runtime/*.py` 或对应测试入口全部通过。

**风险**：低。但可能暴露原本被掩盖的真实缺陷 —— 那是好事。

---

## 6. 验证矩阵（每项改动都必须跑）

| 指标 | 工具 | 采集方式 | 通过判据 |
| --- | --- | --- | --- |
| broker 不空转 | `/proc/PID/stat` + `/proc/PID/io` | 12×2s 窗口采样 `utime/stime` 增量 | `du+ds ≤ 4`，state 为 `S` |
| 无用户态热点 | `simpleperf record -p <PID>` | 6 秒，`--sort symbol -n` | 任何单符号占比 < 30% |
| 帧率稳定性 | `tools/measure-desktop-performance.py` | 连跑 3 次 | FPS 极差 < 15%，P95 < 40ms |
| 无 Watchdog 击杀 | `framework-server.log` | `grep 'GOODBYE'` | 0 命中 |
| 无 binder 停滞 | `framework-server.log` | `grep 'mOut.dataSize() > 0'` | 显著下降 |
| 无 ANR | `framework-server.log` | `grep 'appNotResponding\|ANR'` | 0 命中 |
| 线程不泄漏 | `/proc/<pid>/task \| wc -l` | 管理页/全屏切换 10 次前后 | 不单调增长 |
| 优先级生效 | `/proc/<tid>/stat` 字段 19 | 读所有 `a10-*` 线程 | 与 P0-1 设计一致 |
| 冷启耗时 | `application-*.log` | `desktop_application_spawn_ms` | 逐版本下降 |
| APK 可安装 | `pm install -r` | — | `Success` |

**回归基石**：`tools/test-apk-desktop.py --direct-start`（验收 = `passed: true`，含 `launcherDrawn` / `surfaceOpened`）与 `tools/test-apk-interaction.py`。

---

## 7. 明确不要做的事

1. **不要**把镜像塞进 `lib/<abi>/`。已验证会导致 `INSTALL_FAILED_NO_MATCHING_ABIS (res=-113)`，即使 1600 个 lib 条目全是合法 aarch64 ELF 也装不上。整镜像路径走 **assets**。（此前 765MB APK 的失败教训。）
2. **不要**删除 `GpuBackend.cpp` 里的两个 `glFinish()`。它们是跨 context 的可见性屏障（一个在 `presenter_->blit` 前，一个在 `glTexSubImage2D` 后保护调用方内存）。删了会呈现撕裂帧或读到已释放内存。
3. **不要**把 `-Xint -Xusejit:false` 加回来。生产代码已移除，只应出现在历史记录里。
4. **不要**用 `pkill -f "<pattern>"` 清理 guest 进程 —— pattern 会匹配到自己的命令行，之前已经因此杀掉过 shell。用 `/proc/*/cmdline` 遍历 + `kill -9`。
5. **不要**用 `os.stat()` 统计硬链接/符号链接大小（会跟随后目标，导致体积虚高 3 倍）。用 `os.lstat()` / `Path.is_symlink()`。
6. **不要**在 Termux 里用裸 `grep`/`find` —— shell 快照函数会遮蔽它们，报 `-S: cannot open shared object file`。用 `command grep` / `command find`。
7. **不要**假设 `/tmp` 可写。用 `$HOME/.cache/a10vm-tmp/`。
8. **不要**通过 `su -c` 调 `python3`（无 Termux PATH），用绝对路径 `/data/data/com.termux/files/usr/bin/python3`。
9. **不要**在没有实测的情况下声称性能提升。之前「慢 dispatch 20083ms → 173ms」的结论是错的（173ms 来自被 40 秒 deadline 截断、根本没跑到卡顿阶段的运行）。
10. **不要**改 `guest.prop` 后忘记让种子缓存失效（`GuestRuntime.java:73` 的 `seed_inputs=`）。

---

## 8. 构建与部署流程（改动后必走）

```sh
cd /data/data/com.termux/files/home/android10-vm
export PATH=/data/data/com.termux/files/usr/bin:$PATH

# 1) 只改了 broker / 原生图形 → 重编原生
unset LD_LIBRARY_PATH LD_PRELOAD
sh container-probe/binder/build-probes.sh          # 只动 Broker* 时
sh tools/prepare-native-display.sh                 # 动 desktop/window 时（较慢）

# 2) 二进制变了 → 清单哈希必须同步（RuntimeFiles.verify() 会校验 sha256）
python3 guest-runtime/prepare-framework.py         # 重算 framework/inputs.json
python3 guest-runtime/stage.py                     # 刷新打包目录
#    若报 AssertionError: {'source': ... 'sha256': ...} → 说明清单与磁盘不一致，
#    不要手改清单，回去重跑上一步。

# 3) 构建 APK
sh tools/build-termux.sh :app:assembleDebug

# 4) 安装 + 验证（顺序不能反）
su -c "am force-stop io.a10vm"
su -c "pm install -r app/build/outputs/apk/debug/app-debug.apk"   # 期望 Success
python3 tools/test-apk-desktop.py --direct-start
```

**校验 APK 内确实是新二进制**：

```sh
python3 -c "
import sys, zipfile, hashlib
z = zipfile.ZipFile(sys.argv[1])
d = z.read('lib/arm64-v8a/liba10vm-binder-broker.so')
print(len(d), hashlib.sha256(d).hexdigest())
" app/build/outputs/apk/debug/app-debug.apk
# 与 artifacts/container/runtime/bin/binder-broker 的 sha256 对比
```

---

## 9. 交付检查清单

- [ ] `collectDeadNodes()` 的集合化修复仍在，未被回退
- [ ] `a10-*` 线程 nice 值已按 P0-1 记录/调整，且日志能证明
- [ ] GPU server 线程数在 10 次 surface 切换后不增长
- [ ] `rcColorBufferCacheFlush` 的实际调用频率已测量，若 >1/帧 已改为 fence
- [ ] `rcFBSetSwapInterval` 已透传
- [ ] guest vsync 至少改为绝对期限调度
- [ ] `framework-server.log` 中 `GOODBYE` 为 0、`ANR` 为 0
- [ ] `tools/measure-desktop-performance.py` 连跑 3 次，FPS 极差 < 15%
- [ ] APK `pm install` 返回 `Success`，`lib/` 下无非 `.so` 文件
- [ ] 冷启耗时已测量并记录（P2-2 的基线）
- [ ] `test-apk-desktop.py` 与 `test-apk-interaction.py` 全部通过
- [ ] 未回退第 0 节表格里的任何一项

---

## 10. 附：关键常量速查

| 常量 | 值 | 位置 |
| --- | --- | --- |
| 宿主分辨率 / 刷新率 | 1440×3168 @ 120 Hz | `dumpsys SurfaceFlinger` activeMode id=0 |
| guest 分辨率 | 1080×1920 | `DesktopDisplay.h:4-5` |
| guest density | 480 | `DesktopDisplay.h:6` |
| guest refreshHz | 120 | `DesktopDisplay.h:7` |
| guest vsyncNanos | 8333333 | `DesktopDisplay.h:8` |
| GPU socket 缓冲 | 64 KiB | `DesktopGpuServer.cpp:105` |
| 输入 socket 缓冲 | 4 KiB | `DesktopInputChannel.cpp:63` |
| 触摸队列上限 | 512 | `TouchQueue.h` |
| heapgrowthlimit | 128m | `guest.prop:14` |
| 首次帧超时 | 120 s | `NativeGraphicsSession.kt:22` |
| DesktopCheck deadline | 180 s | `DesktopCheck.java` |

---

*本文档基于 2026-10-09 的代码与设备实测。所有行号以该时点为准；改动前请重新定位。*
