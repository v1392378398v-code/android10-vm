# QQ 包查询兼容性与 MIUI 相机

版本：`0.2.71-miui12-camera-query`，versionCode 81。
交付路径：`/storage/emulated/0/Download/A10VM-0.2.71-miui12-camera-query.apk`。
保持普通应用 UID、原生 ARM64、1080×2160、480 dpi、120 Hz。

## QQ 接口兼容性

原适配在每个应用进程中将 `ActivityThread.sPackageManager` 替换成 Java 动态代理。
新增实机检查在旧实现下得到 `package_query_client=$Proxy0`，标准客户端断言失败。
这证实了接口偏离，尚不足以证明它就是 QQ 风险通知的唯一触发原因。

当前应用入口用 ROM 的 `IPackageManager.Stub.asInterface` 创建其标准客户端，
通过独立的 `QueryBinder` 委托原服务，转换 `getApplicationInfo`、`getPackageInfo`
和 `getPackageInfoVersioned` 的成功回复。事务号从当前 ROM 的 Stub 字段读取。
委托只替换应用侧 `ActivityThread.sPackageManager`，ServiceManager 中的原 Binder、
原生 BpBinder、应用直接获取的服务与框架原生方法继续使用原实现。

系统调用与系统 APK 使用客体坐标，应用查询的基础包和 split 使用实际可读的物理
坐标。原对象、启动 parcel、数据目录和应用身份保持原语义；异常、空值、非目标
事务及 StrictMode 回复头按原语义处理。委托转交 ping、存活、dump 和死亡通知。

QQ 使用现有 APK，账号与聊天数据保留。安全中心旧通知继续属于历史记录；
新的风险通知及服务端判断需要以通知时间和实际运行结果核验。

## MIUI 自带相机

相机桥分为宿主会话与帧队列、HAL1、CameraProvider 和系统 cameraserver。
Camera API 已实际获得前后摄预览回调、SurfaceTexture 帧及 JPEG。
GPU AEMU fence 接口用 EGL KHR 同步实现，无 KHR fence 时通过 `glFinish` 完成。

MIUI 首个崩溃来自缺少可选私有 tag `xiaomi.ai.asd.enabled`，通过其现有
`VENDOR_TAG_NFE_RETHROW` 日志开关选择 warning 策略。其后的 `0x9005`
会话要求小米并行 YUV 算法，LEGACY 相机没有这项能力。
相机 APK 的派生版本在实际硬件级别为 LEGACY 时选择已有普通 JPEG 路径及
标准会话模式，其他硬件级别仍走原分支。LEGACY 会话等待实际预览 Surface 创建，
随后用该 Surface 建立普通会话。原 APK 保存在镜像准备目录。

桥未传送人脸元数据，因此查询能力正确报告零个人脸检测槽；设置参数时恢复宿主
实际只读能力，避免把转换后的能力字段写给硬件。连续对焦移动命令通过宿主
`Camera.setAutoFocusMoveCallback` 接通，真实移动事件转为 HAL `CAMERA_MSG_FOCUS_MOVE`。
这两处缺口分别使 LEGACY 映射器进入 ERROR 状态，现已按实际能力与回调修复。

悬浮管理按钮支持拖动、贴边与位置保存，点击显式返回管理 Activity。

## 验证与交付

编译、lint、APK 输入哈希及 v2 签名按最终产物校验。普通 UID 回归覆盖
真实 APK 直接 SVC 读取、split、序列化回复、原对象、启动 parcel、系统
namespace 内 APK 库加载、WebView 辅助 main、子 zygote 与 isolated 入口。

私有日志、截图及报告位于 `artifacts/container/camera/`，保留在私有目录。
最终安装版验收结果及剩余问题见下方记录；短时间启动通过不代表 QQ 服务端
设备风险通知已永久停止。用户确认今天重新弹出，应继续按新通知的实际时间核验。

### 2026-10-12 最终安装版记录

`v0.2.71` 已覆盖安装并保留现有数据。冷启动进入 MIUI 桌面用时 22.700 秒，
普通 UID 10326、`CapEff=0`；稳定窗口中 system_server 保持存活。
MT 与已登录 QQ 各观察 5 秒，首屏绘制完成且未捕获崩溃。
实机包查询客户端为 `android.content.pm.IPackageManager$Stub$Proxy`，
基础查询、versioned 查询及路径一致性断言均通过。

QQ 当前消息列表显示安全中心最近一条记录为昨天晚上 9:15，本轮短观察没有新弹窗。
用户报告今天重新弹出仍作为待核验的新问题，接口断言通过仅证实本次兼容改动。
包查询委托保留原生 Binder 入口，避免之前候选版引入的 MT 初始化回归。

旧版对照安装曾撤销新版新增的宿主相机权限，最终验收通过管理页的普通权限对话框
重新授予“使用时允许”。恢复权限后，MIUI 相机收到实际预览帧并完成拍照，
`onPictureTakenFinished: succeed = true`，照片写入 MediaStore ID 137。
最终 JPEG 为 4096×3072、878864 bytes，结构解析通过。验收等待拍照完成回调，
避免把先写入的 720×960 临时预览图误当成最终 JPEG。
预览和最终照片仍接近黑，缩小后的亮度范围为 2–4；光照或镜头遮挡尚未确认，
有光场景的画面验证仍待完成。

悬浮按钮的左右贴边、拖动、点击管理页与位置恢复已通过同实现实机验收。
GPU fence 的 GLES2/GLES3 协议检查通过，覆盖跨 decoder、等待、查询、删除和错误返回。

QQ 四次 500 ms 竖向滑动的 Surface 样本为 73.55 FPS，P95 24.893 ms，
最大帧间隔 306.998 ms，CPU 3.226 核。旧版样本是在 Gradle 编译期间取得，
两次热状态与后台负载未固定，因此仅记录当前数值，稳定 120 FPS 仍未达成。
采样包含输入命令间隔，不能等同于输入到显示延迟。

构建和 lint 成功，Error/Fatal 为 0，Warning 为 3；APK v2 签名通过，
2631 个 native 输入、5149 个运行时数据输入及 319 个系统 APK 的哈希全部匹配。
最终 APK 为 3180205716 bytes，SHA-256：
`075ed4ec3571e78f80b421ee1450b849fe4e19ced021854c6500c4c43573ea52`。
结构化结果见 [验收证据](evidence/qq-camera-v071.json)。

独立 `CameraQueryCheck`/`GuestCameraCheck` 命令入口在当前 MIUI 配置中仍有 main 前的
Binder 初始化问题；上述相机结果来自实际 MIUI 应用，不将该命令入口记为通过。

## 原则与后续

KISS/YAGNI：只处理实际的包查询回复和相机会话能力差异。
DRY：复用代码路径映射及 DEX 归档写入，非目标条目逐项检查。
SRP：包查询客户端、回复转换、相机会话、GPU 同步和悬浮 UI 分属独立模块。
原始框架 DEX 与 boot image 保持配对，应用兼容适配集中在查询委托中。

下一步按今天新出现的 QQ 通知核验结果，并完善当前相机桥尚未覆盖的
设备专有拍摄模式；实际性能优化继续按 `SMOOTHNESS_PLAN.md` 的测量推进。
