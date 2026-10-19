# 原生图形路线与桌面性能

## MIUI12 最新交付：0.2.53-incremental-reclaim（2026-10-11）

已覆盖安装 `io.a10vm.miui`，保留数据，保持免 root、1080×2160 / 480 dpi / 120 Hz 配置。
APK：`artifacts/apk/a10vm-0.2.53-miui12-incremental-reclaim-debug.apk`；下载副本：
`/storage/emulated/0/Download/A10VM-MIUI12-1080x2160-v0.2.53.apk`。
SHA-256：`619079c5b61b4214d9c3f474923501bf9c3eb82369bd8ab455c6a5c6d4b2289f`。

原实现每次释放引用后，扫描所有进程的 handles/deaths 和全部节点。v0.2.53 用
`BrokerNodeReclaim` 记录句柄/死亡通知的容器引用数，只有节点创建、引用释放、ACK、
异步缓冲释放或进程退出时登记候选，回收只检查候选节点。强弱引用、待确认引用、
context manager、异步队列与跨进程死亡通知的保活条件保持一致。

1.2 万个保留节点、300 次真实 import/trim/collect 路径的独立基准，平均回收线程
CPU 时间由 442795 ns 降到 531 ns；它仅计回收，排除 IPC、导出和应用渲染。
25 项 Binder、16 项 HwBinder、完整可达性独立对照、零回收分配、最后引用/ACK、
异步队列、跨 context、两种进程退出顺序、嵌套回调及 peer security context 回归通过。
旧生命周期测试固定使用协议 2，与当前工作树协议不符；已从实际 Wire.h 读取版本，
真实回复在发送进程退出后仍可检查和释放。启动测量工具也新增 MIUI 包名参数。

| 实机样本 | v0.2.52 | v0.2.53 |
| --- | ---: | ---: |
| QQ 保留数据强制停止后重开 WaitTime | 1.881 s | 1.279 s |
| 微信同方式重开 WaitTime | 未测 | 1.616 s |
| 抖音同方式重开 WaitTime | 2.419 s | 2.221 s |
| 抖音 8 次滑动 FPS | 72.84 | 96.44 |
| 抖音 P95 / 最大呈现间隔 | 33.194 / 390.029 ms | 16.599 / 107.884 ms |
| MIUI 4 次左右滑屏 FPS | 117.90 | 97.41（前台恢复后） |
| MIUI P95 / 最大呈现间隔 | 8.300 / 33.193 ms | 16.599 / 116.186 ms |
| 桌面启动 / 稳定观察 | 22.970 / 5 s | 19.289 / 5 s |
| 回收在 6 秒 CPU 采样中的占比 | 36.42% | 0.02% |

QQ/微信/抖音分别确认 89/18/59 个缓存 DEX 映射，应用绘制与同一 system_server
存活检查通过。重开不是首次无缓存启动；AM WaitTime 不包含自动化命令与独立绘制
检查的开销。每个应用本轮只采一次冷/热重进，没有把测量扩展成全功能兼容性验收。

带 CPU 采样器的抖音首次样本为 91.11 FPS / P95 24.895 ms / 最大 124.474 ms；
完成采样后的样本为上表 96.44 FPS。最初的桌面测量发现用户已切到宿主 QQ，宿主
VM 进程处于 `do_freezer_trap`，该次没有滑动数据，已排除。恢复前台后的桌面样本
仍有 116 ms 间隔，本轮未证明桌面更快或所有场景稳定 120 FPS。

Surface 时间戳含输入命令间隔和静止画面，内容、后台负载及热状态未固定。两次
抖音 CPU 样本为 3.401/3.576 核，未证明整机耗电或发热下降。新 CPU 热点主要在
通信的内核开销和视频 YUV/RGB 转换，后续优先处理这些路径、长帧和首次无缓存启动。
完整记录见 [v0.2.53 性能证据](evidence/app-performance-miui-v053.json)。

KISS/YAGNI：只消除已测到的全局回收扫描，不加轮询线程或调度配置。DRY/SRP：
释放登记共用入口，节点生命周期放在独立模块，沿用现有传输、缓存与分发。
签名和全部包内输入通过，lint 为 0 Error/Fatal、3 Warning；运行 UID/EUID 10326、
CapEff=0，开发安装所用 root 与产品运行身份分别记录。

## MIUI12 历史交付：0.2.52-ready-dispatch（2026-10-11）

已覆盖安装 `io.a10vm.miui`，保留数据、免 root、1080×2160 / 480 dpi / 120 Hz 配置。
APK 为 `artifacts/apk/a10vm-0.2.52-miui12-ready-dispatch-debug.apk`，Download 副本为
`/storage/emulated/0/Download/A10VM-MIUI12-1080x2160-v0.2.52.apk`，SHA-256 为
`24a15a9e473f55cf731caa03697e13be0d7b261903847985bd95eef9d6defbc6`。

`BrokerDispatch` 按进程的状态变化调度读者、唤醒和嵌套回调；发送循环仅处理有待发
数据的连接，线程注册只检查所属 Binder context。背压继续交给 epoll，清理产生的新
事件先分发再等待。复用已有传输与缓存，局部拆分等待、分发和资源生命周期，落实
KISS/YAGNI、DRY 与 SRP。25 项 Binder、16 项 HwBinder、嵌套回调/唤醒/回收、
多 context 和 peer security context 检查通过，APK 签名和全部包内输入校验通过。

| v0.2.52 实机样本 | 结果 |
| --- | ---: |
| QQ / 抖音保留数据重开 WaitTime | 1.881 / 2.419 s |
| MIUI 4 次左右滑屏 | 117.90 FPS；P95 8.300 ms；最大 33.193 ms |
| 抖音 8 次竖向滑动 | 72.84 FPS；P95 33.194 ms；最大 390.029 ms |
| 桌面启动 / 稳定观察 | 22.970 / 5 s |

样本受内容、热状态与后台负载影响，实际呈现间隔包含输入命令间隔与静止画面。
当前仍有长帧，尚未达到所有场景稳定 120 FPS，抖音滑动没有显示出明确提升。新 6 秒采样中
`collectDeadNodes()` 占 36.42%，`dispatch()` 占 1.79%；后续优先做增量节点回收。
256 个已注册空闲进程、3000 次 Broker 请求耗时从 0.102038 到 0.061547 秒，
CPU 从 0.05 到 0.03 秒，背压排空后空闲 0 ticks；它是独立通信样本。

旧宿主进程现场停在 `do_freezer_trap`，该次滑动没有新帧，已排除于帧率对比。
新包安装后旧进程结束，正常启动、应用绘制与 Surface 呈现通过。测量工具增加冻结
检查和可选 FPS/P95 判据，避免把冻结或低帧率仅按“采到数据”标成通过。
完整记录见 [v0.2.52 性能证据](evidence/app-performance-miui-v052.json)。

## MIUI12 历史交付：0.2.51-app-cache（2026-10-11）

已覆盖安装 `io.a10vm.miui`，保留应用数据、免 root、1080×2160、480 dpi、120 Hz 配置。
下载副本为 `/storage/emulated/0/Download/A10VM-MIUI12-1080x2160-v0.2.51.apk`；
签名、包内内容与 5 秒启动稳定性检查通过，实际 UID/EUID 10326、CapEff=0。

本轮按实际 CPU 采样修正两条路径：Binder/HwBinder 以持续 epoll 等待活跃连接，
减少全量 `poll` 描述符构造与内核扫描；MIUI 刷新已有 DEX 缓存库，应用数据目录由
包管理器按真实 UID 查询，兼容 zygote 缺省的 `--app-data-dir`。独立 `BrokerPoller`
只处理等待与背压，`AppDexCache` 只处理缓存目录，原有分发与缓存校验继续复用。

| 实机样本 | 优化前 | v0.2.51 |
| --- | ---: | ---: |
| 抖音强制停止后打开 WaitTime | 8.993 s（v0.2.50） | 2.342 s（已有缓存） |
| QQ 强制停止后打开 WaitTime | 10.598 s（v0.2.50） | 3.284 s（已有缓存） |
| 抖音 4 次竖向滑动 FPS | 50.18（v0.2.49） | 73.96 |
| 抖音滑动 P95 / 最大间隔 | 58.087 / 99.574 ms | 33.190 / 66.384 ms |
| MIUI 桌面 4 次左右滑屏 FPS | 未采同轴基线 | 93.63 |
| 桌面左右滑屏 P95 / 最大间隔 | 未采同轴基线 | 16.598 / 24.896 ms |

抖音首次生成缓存的 WaitTime 仍为 7.602 秒；QQ 首次检查为 2.212 秒，第二轮为
3.284 秒，保留波动记录。两个主进程分别确认 59 / 92 个 `.adex` 映射。
应用样本为每轮各一次、2 秒异常观察，不等同于登录、全功能或长期稳定性验收。
Surface 数字来自实际呈现时间戳，包含输入命令间隔；网络内容、后台负载和热状态
未固定，配置 120 Hz 与持续实际帧率分开。桌面竖向脚本另有 531 ms 间隔，包含
静止场景，不能用它直接证明左右滑屏卡顿；测量工具新增显式 `--axis horizontal`。

768 个空闲连接、3000 次真实 Broker 请求中，耗时由 0.429037 到 0.163647 秒，
Broker CPU 由 0.41 到 0.13 秒。25 项通信检查、引用回收与嵌套分发、背压排空后
空闲零 CPU ticks、14 项 DEX 缓存损坏/更新/回退检查通过。抖音总进程 CPU 样本
仍为约 4.22 核，不宣称整机开销或发热已同步下降。

完整路径、方法与结果见 [MIUI 性能证据](evidence/app-performance-miui-v051.json)。
KISS/YAGNI：只修已测的扫描与重复加载；DRY：复用包管理器和已有缓存；
SRP/SOLID：连接等待、包目录解析、加载校验分别归属独立模块。
后续优先定位抖音残余长帧、首次无缓存启动和跨设备差异。

## 历史交付：0.2.17-frame-pacing（2026-10-10）

APK：`artifacts/apk/a10vm-0.2.17-frame-pacing-debug.apk`，417270572 字节，
SHA-256 `b8e977230f44141f995cea4b923533759628244e955b2f41dfa24e29ff347e73`。
下载副本：`/storage/emulated/0/Download/A10VM-0.2.17-frame-pacing.apk`。
离线核验通过：v2 签名、463 个 ARM64 native 文件、828 个 assets 数据文件、79 个系统 APK、
13 个 JNI 导出；lint 为 0 Error/Fatal、3 Warning。覆盖安装返回 `Success`，保留 guest 数据。

本轮沿用 v26 的 GLES3 framebuffer blit、跨 context fence、1080×1920、480 dpi、120 Hz、
免 root 原生 ARM64 ART/Surface 路线，新增四个可验证修复：

- Binder `collectDeadNodes()` 改用节点代际标记，只在引用生命周期变脏时扫描；6 秒 broker
  profile 中占比由 v26 的 30.89% 降到 5.67%，定向回归确认 0 堆分配且资源语义保持。
- GPU worker 使用完成通知及时 join，析构仍等待全部连接；32 次断开重连和 10 次真实 Surface
  替换均通过，采样会话中实机 worker 数量保持 26，system_server PID 保持 26328。
- guest HWC vsync 改为单调时钟绝对期限，处理 `EINTR`、退出和落后跳帧；guest swap interval
  透传到宿主 presenter，并记录 cache-flush 次数。跨 context 可见性屏障保留。
- 应用启动日志增加 `desktop_application_spawn_ms`、`guest_application_entry_ms`、
  `guest_application_ready_ms`；本次 48 个样本 spawn 为 1–31 ms，entry 为 469–1431 ms，
  ready 为 551–1636 ms。boot image/真 zygote 未与本轮稳态修复混改。

### v27 实机结果

首次验收启动为 11.683 秒（system_server PID 26328），随后完成下述性能与生命周期采样。
最终覆盖安装返回 `Success`，另一次服务入口启动为 11.719 秒（PID 23324），Launcher/Surface
完成显示并通过 5 秒稳定观察；对应 `artifacts/performance/v27-desktop-acceptance.json`。
两次为不同会话，APK 哈希相同，启动耗时不等同于管理页点击耗时。

`tools/measure-desktop-performance.py --label v27-run{1,2,3} --swipes 8`，设置页交替滑动：

| 样本 | FPS | 中位帧间隔 ms | P95 ms | 最大间隔 ms | UID CPU 核数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| v27-run1 | 98.40 | 8.299 | 16.598 | 49.791 | 1.255 |
| v27-run2 | 102.90 | 8.299 | 16.597 | 24.896 | 1.604 |
| v27-run3 | 100.69 | 8.299 | 16.598 | 24.897 | 1.631 |

三次均为真实宿主 SurfaceFlinger 时间戳，包含输入命令间隔，不是输入到光子延迟；配置是
120 Hz，测量结果不宣称稳定 120 FPS。持续触摸回归通过，录屏去重可见运动约 63.36 FPS，
该值不替代 Surface 提交帧率。无 Watchdog、ANR 或 system_server 重启。

12 个 2 秒 broker 静止窗口仍为 4–20 CPU ticks（约 2–10% 单核），12 个终点中
11 个 `S`、1 个 `R`。严格的每窗口 ≤4 ticks 指标尚未达到；不能把 profile 热点下降
写成 broker 完全无开销。`syscr/syscw` 保持 52/35，Binder 的 `sendmsg/recvmsg`
不由这两个计数完整表征，冻结计数也不单独证明自旋。

`task_profiles.json` / `cgroups.json` 已随 system assets 打包，缺失文件日志消失；普通应用
命名空间没有可用 cgroup controller，因此控制器加入仍会记录 `controller ... is not found`，
不把它冒充为调度提升已生效。

证据：`artifacts/performance/v27-run1.json`、`v27-run2.json`、`v27-run3.json`、
`v27-broker-profile.txt`、`v27-thread-stat.txt`、`artifacts/performance/surface-lifecycle.json`、
`artifacts/device-desktop/interaction-v27-frame-pacing/report.json`。

KISS/YAGNI：只修改已测瓶颈和生命周期边界，保留 GLES2/MSAA 回退，不引入 TCG、绑核或 root。
SRP/SOLID：Binder 回收、GPU worker、HWC 调度、应用计时和打包清单分别归属各自模块。
DRY：新增 `tools/stage-native-display.sh` 复用原生显示清单生成，避免重建后 renderer 哈希漂移。

下一步：沿已记录的应用 entry/ready 时间推进 ART boot image 和预热；继续定位 broker
的 dispatch/poll 残余占用。堆大小、宿主 vsync 驱动和分辨率不在本轮声称完成。

## 历史交付：0.2.16-gpu-blit（2026-10-10）

APK：`artifacts/apk/a10vm-0.2.16-gpu-blit-debug.apk`，415401357 字节，
SHA-256 `3b43f3879d29f96398466ca781fb48b90e1506e4ac84cbecfdccdfba63b27652`。
下载副本：`/storage/emulated/0/Download/A10VM-0.2.16-gpu-blit.apk`。
完整签名、ZIP、463 native 文件、826 数据文件、79 系统 APK 和 13 JNI 导出核验通过；
lint 为 0 Error/Fatal、3 Warning。覆盖安装保留数据，微信安装记录仍在。

本轮将 GLES3 无 MSAA 的窗口拷贝替换为一次 `glBlitFramebuffer`，同时转换颜色格式和
垂直方向，省去中间纹理及 root shader pass。GLES2/MSAA 保留旧实现；客体对外仍是
GLES2，不新增 TCG、CPU 绑核或 root 依赖。每个 EGL context 独立持有拷贝 FBO，
`FramebufferCopy` 恢复 draw/read binding 和 scissor，`GpuBackend` 维护跨 context 的
写入/采样 fence，`DesktopPresenter` 继续只负责显示窗口。

最初直接复制 RGB Pbuffer 到 RGBA 纹理遇到 `GL_INVALID_OPERATION`，现用 framebuffer
blit 完成格式转换。legacy 定向检查还发现驱动可返回高于请求的 EGL context 版本；
代码改为按实际版本恢复 read FBO，避免状态污染。direct/legacy、RGB/RGBA 透明度、
上下方向、viewport/纹理/FBO/scissor、MSAA 回退、并发顺序、呈现后重写和资源回收通过。
普通 Termux UID 10373 下，客体真实 EGL/GLES 驱动、gralloc/HWC、YUV、shader 像素、
交错顶点、行布局及顶点属性边界通过。

### 1080p 拷贝测量

命令：`desktop-presentation-check --benchmark`。每条路径预热 8 帧后测 120 帧，
包含 clear、窗口 flush 和末尾同步像素读回；未包含整套 Android 应用、合成与物理显示。

| Pbuffer | legacy ms/帧 | blit ms/帧 |
| --- | ---: | ---: |
| RGB8 | 1.966 | 0.585 |
| RGBA8 | 0.789 | 0.466 |

证据：`artifacts/container/graphics/desktop/copy-benchmark-final.log`。

### 实机桌面测量

1080×1920、480 dpi、120 Hz 配置保持不变。开发安装和采集用设备 root，客体实际
身份为 UID 10698、CapEff 0、`untrusted_app`。App 服务入口启动样本 15.234 秒，
Launcher 已绘制，5 秒稳定观察通过；管理页/全屏 Surface 替换后 system_server
仍为 PID 20043。该入口绕过管理页点击，耗时不等同于点击启动耗时。

沿用 `tools/measure-desktop-performance.py`，客体设置页交替 500ms 滑动 8 次：

| 样本 | FPS | 中位帧间隔 ms | P95 ms | UID 进程 CPU 核数 |
| --- | ---: | ---: | ---: | ---: |
| 本轮 v25 基线 | 29.12 | 33.197 | 58.093 | 1.505 |
| v26 blit | 44.12 | 24.893 | 33.197 | 1.475 |
| v26 同会话重复 | 51.45 | 16.598 | 33.194 | 1.406 |

FPS 来自真实宿主 SurfaceFlinger 时间戳，包含输入命令间隔；它不是输入到光子延迟。
拷贝成本和这两次滑动样本有改善，宿主负载与热状态未受控，结果未证明稳定 120 FPS。
启动不是本轮优化对象，系统应用、WebView、媒体和第三方兼容性的历史验收不冒充
v26 全量验收。证据见 [v26 图形清单](evidence/gpu-blit-v26.json)。

KISS/YAGNI：一次平台 blit、旧路径回退，仅处理本次拷贝瓶颈。
SRP/DRY：拷贝与测试各自独立模块，共用生产后端和 fence；未扩展客体协议。
下一步依据实际应用的卡顿场景分析 Binder/ART/图形命令往返，保留当前版本用于实用反馈。

## 历史交付：0.2.15-multicore（2026-10-10）

APK：`artifacts/apk/a10vm-0.2.15-multicore-debug.apk`，415394973 字节，
SHA-256 `77cbc1b895c078e80d2649b3daa3fa3e8948a924473b6f86f37af69d2f360797`。
下载副本：`/storage/emulated/0/Download/A10VM-0.2.15-multicore.apk`。

| 项目 | 结果 |
| --- | --- |
| 显示配置 | 1080×1920、480 dpi、120 Hz |
| 客体显示查询 | 1080×1920、`120.00001 Hz`、480 dpi |
| 客体身份 | UID 10698、CapEff 0、`untrusted_app` |
| 桌面启动 | App 服务入口 12.48 秒；Launcher 绘制；稳定观察 5 秒 |
| Surface 重建 | 通过；同一 system_server PID 保持 |
| GPU 并发回归 | 通过；并发拷贝顺序保持 |
| Binder 回归 | 25 项通过；资源回收通过 |
| Lint | 0 Error、0 Fatal、3 Warning |

启动使用 `tools/test-apk-desktop.py --direct-start`，绕过管理页点击并显式打开全屏；
该耗时不等同于点击启动耗时。覆盖安装保留客体数据。

`Desktop present swap EGL=12301` 对应 `EGL_BAD_SURFACE`（`0x300d`）：
BufferQueue 可在 `surfaceDestroyed` 回调前断开。交换遇到失效 Surface 时，只退役
对应 generation，保留客体会话和较新的附着；管理页/全屏切换后的呈现检查通过。

属性恢复覆盖源镜像 `build.prop` / `default.prop` 并合并 172 条属性。
本版关于手机完成绘制；应用宝没有 Fatal，但仍未完成绘制。MT 的 native
初始化仍失败；已捕获 `libmtprotect.so` 内联 `openat` 访问逻辑 APK 路径返回
`ENOENT`，未修改第三方 APK。这两项仍待修复。

### 性能对照

测试脚本：`tools/measure-desktop-performance.py --label final-multicore`。
场景为客体设置页交替滑动 8 次，采集真实宿主 SurfaceFlinger 时间戳和 UID
进程 CPU。FPS 取首末实际呈现时间戳之间的平均值，包含输入命令间隔；
这不是输入到物理屏幕的延迟测量。

| 样本 | FPS | 中位帧间隔 ms | P95 ms | UID 进程 CPU 核数 |
| --- | ---: | ---: | ---: | ---: |
| 基线 | 16.81 | 58.091 | 74.698 | 1.689 |
| 新版 | 33.17 | 33.198 | 41.503 | 4.212 |
| 新版重复 | 12.55 | 66.401 | 174.301 | 1.678 |

重复样本存在明显波动；宿主负载和操作干扰是候选原因，尚未证明因果。
这些结果既未证明稳定 120 FPS，也未证明总 CPU 开销下降。

本轮改动集中在四个边界：GPU registry 锁在绘制后释放、EGL fence 替代整帧
CPU `glFinish`、Binder 小包接收缓冲复用并优先发送 ACK、客体前后台重要性映射
到同 UID 线程 nice。没有绑大核、修改宿主调度器或引入 root 依赖。

以下章节保留早期版本和历史测量，用于追溯，不覆盖上面的最新实测。

更新日期：2026-10-08。历史主工程为 `0.2.0-native-display`（versionCode 10）。
主入口已切到免 root ARM64 客体、GLES 命令流、宿主 GPU/Surface 和独立多指输入。
本轮交付画面/触摸试用 APK；完整 Android 10 桌面和实际屏幕性能仍待接通、测量。

## 本轮可验证结果

APK：`artifacts/apk/a10vm-0.2.0-native-display-debug.apk`，4,234,769 字节；
下载目录副本：`/storage/emulated/0/Download/A10VM-0.2.0-native-display.apk`。
摘要、构建和回归范围见 [原生显示清单](evidence/native-display.json)。

普通 Termux UID 10373 下，真实 Adreno 830 的生产渲染器/客体离屏链路完成
50 帧和 205 条输入；图形传输暂停期间，客体独立输入线程仍收到全部事件。
立即停止的回归发现旧实现抢先发送 STOP、丢弃排队输入：应用数为 2/205。
STOP 改为排在队尾后，客体处理完 205/205 条再退出；满队列停止也有独立回归。

这些结果验证输入隔离与停止顺序。当前没有新版 APK/Surface 实测，60 Hz 是节拍目标；
未测完整 Android 启动、点击、前后台与持久化。完整 libEGL/renderControl、
gralloc/HWC/SurfaceFlinger 与 ART/私有系统服务集成继续按
[两仪方案](TWOYI_ANDROID10_PLAN.md)推进。

KISS/YAGNI：单一原生入口；SRP/DRY：主应用与探针共享窗口、JNI 和库校验，
输入通道独立于渲染。
