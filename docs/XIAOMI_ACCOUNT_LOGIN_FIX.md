# MIUI12 小米账号登录修复

2026-10-12，已覆盖安装 `0.2.60-miui12-account-capabilities`（versionCode 70）。账号密码入口在 861 ms 内打开密码表单；随后客体设置显示账号管理状态，只读查询确认存在 `com.xiaomi` 类型的账号记录。

阻塞由三处问题组成：FindDevice 缺少持久存储 HAL，初始化线程持续等待；ROM 的 `XDeviceInfo.getKeyStoreTypeUnblocking()` 对 Android 10 直接报告 TZ，FindDevice 启动后覆盖运行时的凭据服务；账号入口只检查用户编号和账号环境，继续请求依赖硬件 FID 的查找设备接口，服务器返回 `10016 / cloudsp_fid 参数为空`。

本轮修复如下：

- `GuestMtdStorage.cpp` 实现 ROM 原始 HIDL 客户端使用的持久存储，补齐 VINTF 声明。二进制内容保存到 `/data/system/a10vm-mtd`，采用临时文件、fsync 和原子替换；缺失数据返回 ROM 规定的 41，非法参数返回 22。
- FindDevice 的 `publishServices()` 先查询并检查现有凭据 Binder，已有可用服务时保留它；服务缺失或已退出时沿用原来的注册流程。
- 小米账号的 FindDevice 入口保留原来的用户和账号环境判断，并读取 ROM SDK 的 `isThisDeviceSupported()`。客体缺少硬件凭据时进入普通账号登录流程。
- `patch-rom-account.py` 从原始系统 APK 生成派生版本，仅替换目标 DEX，校验其他 ZIP 条目内容一致；`stage-rom-apk.py` 更新对应系统 APK 及资源哈希。宿主 APK 使用既有构建签名，v2 校验通过。

KISS / YAGNI：直接使用现有 SDK 和 Binder 注册状态，按客体实际能力选择登录流程。DRY：两处 DEX 变换共用派生产物与非目标条目检查，系统 APK 继续使用现有资源安装函数。SOLID：存储 HAL、账号能力判断、构建变换和验收各自负责一个职责，运行时与硬件后端通过 SDK / Binder 接口连接。

已完成的验证：

- 框架 DEX 编译、宿主 APK 构建及 lint 通过；15 个 ROM 打包回归检查通过。
- 外层 APK 的 v2 签名、2628 个原生文件、5148 个运行资源及 319 个系统 APK 校验通过。
- 重启后读回原先写入的二进制测试内容，随后完成幂等删除检查。
- FindDevice 的五个 Provider 查询全部完成，合计 28 ms；进程启动后凭据服务保持“不支持硬件凭据”。
- 原始 SDK 的凭据获取、签名和重载回调完成，合计 7 ms；现有 Binder 保留检查通过。
- 按客体 View 层级计算按钮坐标，点击后出现密码输入控件，耗时 861 ms。
- 客体进程使用普通应用 UID 10326，`CapEff=0000000000000000`；显示配置保留 1080×2160、480 dpi、120 Hz 目标刷新率。

验收期间切到宿主 QQ 触发过客体后台冻结，因此桌面通用脚本的 Surface 检查中断。恢复前台后完成了账号定向验收，并从客体截取设置页面确认显示链路。该截图含账号资料，仅保存在私有工件目录；交付记录保存账号存在状态。服务端令牌有效性尚未单独验证。

交付 APK：`/storage/emulated/0/Download/A10VM-MIUI12-1080x2160-v0.2.60.apk`，3181521307 字节。

SHA-256：`930abb9232861b4eb078ca5a87b0494d6fce453ca3caaf42ee605a307cf003f1`。

后续直接在客体设置中使用小米账号。云服务的后续操作按实际反馈单独验收，避免扩大本次登录修复。
