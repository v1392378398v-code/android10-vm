# MIUI12 应用商店兼容性与运行开销

本轮针对 `io.a10vm.miui` 中的抖音状态保存与 QQ 视频图形错误，并保留应用商店和设置修复。继续使用 raphael 20.12.9 的 MIUI framework、1080×2160 显示模式和 120 Hz 配置。

## 修复内容

- 原 Google WebView 83 报 `Ashmem region has a wrong protection mask`。加入 Android 10 / ARM64 的独立 WebView 139.0.7258.143，原 provider 保留。`GuestWebViewProviders` 向 ROM 的 provider 清单注册新包并写入 provider 设置，由 Android 正常启动阶段准备 RELRO。保留 memfd、封写和 `MAP_PRIVATE` 的原有语义。
- 应用进程曾缺少 `Performance.native_perf_get_prop` 的 JNI。系统启动和应用入口共用 `BootNativeLibraries`，按 ROM 清单加载 `qti_performance`。
- ROM linker 配置增加可见 `vndk`、`sphal` namespace，搜索范围继续使用客体私有目录。
- 新加载的 OEM JNI 与媒体库会在同一进程内分别打开 HwBinder。桥接原先按 PID 拒绝第二次打开，返回 `EEXIST`，随后 `Codec2Client` 终止 MIUI launcher。现在每次打开创建独立 Binder 上下文，线程连接继续按上下文、真实 PID 和 UID 校验，关闭一个上下文只回收其资源。
- 调试器捕获了 ROM 媒体服务在 `NuPlayer::closeAudioSink()+16` 的空 renderer 访问。`patch-rom-media.py` 从导出符号和 ELF 可执行段定位入口与空白尾部，向派生库加入 null 判断。原 CFI 检查和非空路径保留，实际 ROM 共 19 个字节变化；原件保持原样。ARM64 动态夹具验证修复前 SIGSEGV、修复后空路径返回和非空路径操作。
- SLA 与 CACert 常驻包依赖的 HAL 当前没有注册，曾持续崩溃重启。`GuestHardwareApplications` 根据实际服务注册状态保存、调整 enabled 状态；HAL 接通时恢复记录的状态。应用文件与数据保留。
- MIUI 下载引擎通过 `truncate` 移除下载文件尾部的任务元数据。原入口直接使用客体绝对路径调用宿主内核，下载字节已齐后仍报 `SD_INVALID_FILE_SIZE(111130)`，任务结束为 490 并清掉 `_data`。补齐 `truncate`、`truncate64` 和 `syscall(__NR_truncate)`，共用 `guestPath`，保留实际内核返回值；无需修改下载 provider 或商店 APK。构建同步刷新 linker、libc、libdl，防止旧 ROM 输入缓存覆盖修复。
- 开发者选项查询 MIUI 的 `isWifiCoverageExtendFeatureEnabled` 时，桥接未处理该方法，抛出 `UnsupportedOperationException` 并使设置反复重启。补齐查询及 `enableWifiCoverageExtendFeature`：宿主网络转接没有物理射频扩展能力，查询保持关闭，更新请求按 void 接口返回。共用原有动态 Binder 方法映射，不写固定事务号，也不改宿主无线配置。回归识别当前 ROM 实际方法；AOSP 接口没有该扩展时记录 absent。
- 抖音 KEVA 日志显示 `files/keva/repo/`、`privacy_dialog_repo/`、`account_saas_accept_term_privacy/` 等目录创建返回 `ENOENT`。路径映射把尾斜杠视为仍有子路径，提前要求新目录存在。新增仅供目录创建使用的 `guestMkdirPath`，去掉尾斜杠后共用原有映射；`mkdirat` 和原始 `syscall(__NR_mkdirat)` 共用此入口，内核继续决定已有文件、链接与缺父目录的错误。八项回归覆盖新目录、相对 dirfd、原始 syscall、错误返回和状态文件写入回读。
- 合法 2048×2048 RGBA 上传本身占 16 MiB，加上协议字段就超过原 GPU 包长度上限，复现 `Invalid desktop GPU command size`。调整同一传输上限为 64 MiB 加 64 KiB，容纳 4096×4096 RGBA 及协议字段，缓冲仍按需分配。真实客体 EGL 回归上传 2048×2048 纹理并通过 FBO 读回像素，检查后续指令仍对齐；超限检查保留。
- GPU 错误增加当前 opcode、包长度、上限与上一条成功指令信息。MIUI 构建同步刷新客体 EGL/GLES、gralloc、hwcomposer 与 HAL 库，防止 `prepared-v2` 缓存带回旧协议实现。
- 应用性能采样发现 MIUI 版反复解压并验证 DEX，原有包内缓存未接通。v0.2.51 刷新已验证的 `libdexfile`，按实际 UID、包信息与数据目录启用已有 DEX 缓存，兼容 Android 10 缺省的 `--app-data-dir`。缓存属于应用 `code_cache`，首次仍做完整校验，APK 更新失效，坏缓存重新解压；不关闭全局 DEX 校验或 JIT。Binder 同时改用持续监听活跃连接的 epoll，具体测量见 [流畅度实施记录](SMOOTHNESS_PLAN.md)。

## 验证入口

多次打开同一个设备的回归先在旧 broker 上失败，修复后通过。两条连接完成 64 轮往返，关闭其中一条后另一条继续通信。既有 25 项独立进程 Binder 检查与真实 `SO_PEERSEC` 传递检查通过。

```sh
sh container-probe/binder/test-multi-open.sh
sh container-probe/binder/test-security-context.sh
python3 container-probe/binder/test-native.py
python3 tools/test-rom-apk-stage.py
python3 tools/test-rom-media-patch.py
sh container-probe/runtime/filesystem/build-probe.sh
python3 container-probe/runtime/filesystem/test-native.py
python3 guest-runtime/test-desktop-egl.py
python3 guest-runtime/test-dex-cache.py
python3 container-probe/binder/measure-broker-idle.py --output artifacts/performance/broker-idle.json
artifacts/container/graphics/bin/stream-test
python3 tools/test-apk-download-install.py --package io.a10vm.miui --label current
python3 tools/apk-guest-command.py --package io.a10vm.miui --main io.a10vm.guest.WifiDeveloperCheck
python3 tools/apk-guest-command.py --package io.a10vm.miui --main io.a10vm.guest.AppDexCacheCheck com.ss.android.ugc.aweme com.tencent.mobileqq
python3 tools/test-apk-app-compat.py --package io.a10vm.miui --case developer --case input-method --label current
```

安装版验收使用 `--package io.a10vm.miui`，检查 HOME 为 `com.miui.home`、运行身份为普通 UID、CapEff 为零，再检查应用商店绘制、进程存活和 Surface 呈现。最终结果保存在 `docs/evidence/miui12-apk-release.json`。

下载回归通过真实下载 provider 获取独立 APK，检查任务状态、落盘大小和 SHA-256，再把该文件的原字节流交给客体包管理器。测试只删除自己的下载任务。底层回归在旧运行库上复现三个截断入口失败，修复后当前工作树的 79 项检查通过；安装版的结果单独记录。

v0.2.48 已覆盖安装，签名与 2628 个原生文件、5147 个运行资源及 319 个系统 APK 的内容校验通过。旧版开发者页面在 `isWifiCoverageExtendFeatureEnabled` 处抛异常；新版真实 Binder 代理回归完成查询和开关请求，开发者页面与输入法页面均绘制完成，3 秒观察无崩溃，系统服务仍存活。证据位于 `artifacts/app-compat/miui-v048-settings/report.json`。当前键盘由用户选择，未额外打包输入法。

v0.2.48 的 QQ 空间视频日志包含 `eglMakeCurrent` 的 `EGL_BAD_MATCH`，随后出现 `GL send: Broken pipe` 与 SIGABRT，用户回放反馈宿主错误 `Invalid desktop GPU command size`。该版本未包含图形补丁。整机启动检查曾受宿主切换应用影响而超时；恢复前台后的独立检查发现 SystemUI 累计启动三次，超过既有检查上限。设置页面通过不等同于整机长期稳定性通过。

v0.2.49 底层检查已通过：文件系统 87 项、四个校验器反例和逐进程 UID/caps/maps 检查；客体 EGL 的大纹理上传与像素读回、字幕透明度、共享纹理和媒体缓冲检查；流传输的分片、超限、EOF、checksum 与断连检查。修复前证据在 `artifacts/download-install/keva-before.log` 与 `gpu-large-before-host.log`，修复后证据在 `keva-after.log` 与 `gpu-large-after.log`。安装后抖音隐私状态仓库落盘，强制停止后重新打开显示推荐视频，没有重复显示指引，3 秒观察无崩溃；保留了用户此前同意的状态和既有数据。证据在 `artifacts/app-compat/miui-v049-douyin-reopen/report.json` 与 `artifacts/download-install/douyin-privacy-start-v049.log`。QQ 原空间视频仍待回放，未以纹理回归代替实际视频结果。

KISS/YAGNI：直接恢复实际需要的 Binder 打开语义、ROM JNI、目录创建与传输上限，不增加新的显示或存储后端。DRY：启动与应用入口共用 JNI 加载器，两种目录创建入口共用 `guestMkdirPath` 和 `guestPath`，安装回归复用 `GuestCommand`。SRP/SOLID：provider 配置、硬件常驻包状态、Binder 上下文生命周期、文件系统与图形传输各守独立职责。

后续按具体应用调用补齐仍未接通的 HAL；120 Hz 配置与实际测得的帧率分别报告，兼容性结论以已验收的软件和宿主版本为界。
