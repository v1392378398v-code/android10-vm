# A10VM

在手机上运行独立的 Android 10 应用空间。当前主线为 **A10VM MIUI12**，包名 `io.a10vm.miui`，
版本 `0.2.88-miui12-android9-aosp-ime`（versionCode 98）。

## 运行原理

项目直接运行 Android 10 的 ARM64 linker、Bionic、ART 和系统服务，与手机共享 Linux 内核。
私有 Binder/HwBinder、属性服务、文件路径与应用身份映射组成客体运行环境；
客体 SurfaceFlinger 经配套 EGL/GLES 协议使用手机 GPU，画面显示在宿主 Surface，
触摸通过独立通道进入客体 InputManager。

可以简单介绍为：**共享手机内核，在独立的 Android 10 用户空间里运行应用，并把图形和输入接到手机上。**

产品运行使用普通应用 UID，安装后直接启动。开发测试脚本使用的 Root/ADB 用于安装、
采集和自动化控制，客体运行身份仍核验为普通 UID、`CapEff=0`。

## 系统要求与验证范围

- 宿主最低 **Android 9 / API 28**，ARM64；客体为 **Android 10 / API 29**。
- 新旧系统的窗口边距、全屏、Wi-Fi 设置、前台服务和显示帧率 API 按版本处理；
  宿主显示库和编码客户端以 API 28 构建。
- API 28 的应用及库模块检查、NDK 强符号核对已通过。当前实机回归设备为 PJZ110、
  Android 16、Linux 6.6、4 KiB 页；Android 9 实机、16 KiB 页及其他 GPU/ROM 组合仍需分别验证。
- 联想 L78071 的旧内核共享内存、mapper 和慢速输入启动问题已有针对性修复，
  整机稳定性仍待验证，设备排查已暂停。详见 [设备兼容记录](docs/DEVICE_COMPATIBILITY.md)。

最低安装版本与整机稳定性是分开的验证项，开发机结果只覆盖记录的设备和场景。

## 使用

1. 安装完整 APK，打开 **A10VM MIUI12**，点击“启动 Android 10 桌面”。
2. 启动页以黑底绿字向上滚动真实进度，中文提示当前步骤及实际等待时间。
3. 系统就绪后进入 MIUI 桌面；悬浮按钮可返回管理页。
4. “导入应用到 Android 10”可选择手机已安装应用，或使用系统文件选择器选择 APK。
5. “导入图片、视频和文件”支持多选，导入客体下载目录并更新媒体索引。
6. 麦克风和相机需分别允许宿主及客体应用使用；Wi-Fi 设置使用手机自己的连接。
7. 启动卡住或操作失败时，打开“查看运行记录”，可选中文字或复制整份记录。

### 内置输入法

内置 **Android 10 AOSP 原生键盘 LatinIME**，支持英文等拉丁字母语言、数字和符号。
首次初始化自动启用；升级保留已有有效默认输入法和用户设置。
可在 Android 10 的输入法设置中切换到“Android 键盘（AOSP）”；中文输入法可另行安装。

键盘 APK 和 ARM64 原生库取自同一份已审计的 Android 10 输入，按固定 SHA-256 校验，
原生库接入系统预装应用库目录。升级清理旧内置键盘系统文件，用户数据保留。
来源与许可证见 [输入法说明](guest-runtime/keyboard/NOTICE.md)。

### 从手机导入应用

“从手机已安装应用选择”显示应用图标、名称和包名，支持搜索与多选。
导入在后台逐个进行，并显示当前进度。拆分 APK 的基础包和全部 split 使用同一
PackageInstaller 会话安装，失败时撤销该应用的未完成安装会话。

导入的是安装包，登录状态和应用私有数据需在客体内重新设置。
要求 Android 11 或更高版本的应用会显示版本提示，其他安装失败会保留具体原因。
应用安装完成也需另行验证其设备服务、媒体和登录功能。

## 构建

主要模块：

| 路径 | 职责 |
| --- | --- |
| `app` | 管理页、启动显示、应用和文件导入、会话控制 |
| `guest-runtime` | 私有文件与身份映射、ART、系统服务、设备桥、输入法初始化 |
| `native-display` | JNI、Surface 生命周期、窗口边距与触摸入口 |
| `container-probe/graphics` | 图形协议、GPU 解码与呈现、原生回归 |
| `container-probe/runtime`、`binder`、`hwbinder` | 客体运行库与通信实现 |
| `tools` | ROM 导入、构建、包内核验与实机验收 |

已清理停用的整机模拟后端、独立旧核心模块、截图显示桥、键盘映射资源与对应记录。
当前构建仅包含 `app`、`native-display`、`guest-runtime`；
独立图形探针通过 `-PcontainerProbe` 按需加入。

ARM64 Termux 构建环境使用 Java 21、Android SDK 35、NDK、Gradle 8.11.1 和 Termux `aapt2`。
ROM、提取后的运行库、APK 和私有测试数据保存在被 Git 忽略的本地目录；
从源码检出后需要先准备对应输入。

```sh
# 原生基础版：先审计输入，再准备配套运行库。
sh guest-runtime/audit-inputs.sh RAW_IMAGE NEW_AUDIT_DIRECTORY
sh tools/prepare-native-display.sh RAW_IMAGE G0_REPORT

# MIUI12：已有指定 ROM 及提取目录时，刷新框架、原生库、输入法并构建。
sh tools/build-miui-apk.sh artifacts/experiments/miui12-20.12.9

# 已准备好的 MIUI12 输入可增量构建界面。
sh tools/build-termux.sh \
  -PguestRuntimePrepared=guest-runtime/build/rom-prepared/miui12 \
  -PguestRuntimeProfile=miui12 --max-workers=1 \
  :app:assembleDebug :app:lintDebug
```

完整包超过 2 GiB。全量打包前应使用新的输出 ZIP；构建脚本负责相应输出准备。
本地输出为 `app/build/outputs/apk/debug/app-debug.apk`，交付摘要见
[本轮验证](docs/VALIDATION.md)。

本机下载目录：`/sdcard/Download/A10VM-MIUI12-v0.2.88-android9-aosp-ime.apk`。
SHA-256：`0ff401f529c1be98d9f26dcea206ada2d89f9727ae492f408486e1c84d55ad42`。
当前包冷启动、输入就绪、桌面出图和 30 秒稳定观察通过；输入法已由用户确认。

## 验证

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/check-host-api28.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-rom-apk-stage.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/verify-native-display-apk.py \
  --runtime-prepared guest-runtime/build/rom-prepared/miui12
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-apk-desktop.py \
  --package io.a10vm.miui --direct-start --timeout 120 --stability-seconds 30
```

验证记录分别说明构建、包内哈希与签名、桌面启动、输入就绪、键盘输入、
应用导入及重启保留的结果。QQ 网页、媒体、账号与跨设备稳定性按各自记录验收。

- [管理页、启动动画与运行记录](docs/MANAGEMENT_UI.md)
- [设备兼容记录](docs/DEVICE_COMPATIBILITY.md)
- [QQ 网页问题](docs/QQ_WEB_FIX.md)
- [QQ 与相机适配](docs/QQ_CAMERA_COMPAT.md)
- [MIUI12 启动记录](docs/MIUI12_BOOT_TRIAL.md)
- [性能记录](docs/PERFORMANCE.md)
- [第三方来源](docs/THIRD_PARTY.md)

项目自有源码许可见 [LICENSE](LICENSE)，第三方组件保留各自许可。
