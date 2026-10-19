# Android 10 私有运行时

`0.2.15-multicore` 接入真实 Android 10 `dalvikvm64`、`app_process64` 和系统服务依赖闭包，
复用 `container-probe/runtime` 已构建的源码 linker/Bionic、私有属性和路径映射。
普通应用 UID 下运行 SystemServer、SurfaceFlinger、Launcher3、SystemUI 与设置，
通过宿主 GPU/Surface 显示桌面，独立触摸通道接入客体 InputManager。

当前显示参数为 1080×1920、480 dpi、120 Hz；客体查询实测 `120.00001 Hz`。
渲染器释放全局注册表锁后再等待 BufferQueue，GPU copy 使用 EGL fence，Binder
接收缓冲按线程复用，输入/合成线程与后台导入分开调度。线程只调整自身 nice，
不固定 CPU 核心，也不要求 root。设置滑动的短测样本为约 12.5--33.2 FPS，
采样包含输入命令间隔，波动原因尚未确认；120 Hz 配置不等同于稳定 120 FPS。

## 职责

- `prepare.py`：只读校验已审计镜像并提取 ART 动态依赖、核心 JAR 和 ICU 数据。
- `build-native.sh`：构建属性初始化器、ART 日志代理和检查 DEX。
- `prepare-framework.py` / `prepare-desktop.py`：提取配套系统服务、桌面应用、字体与配置。
- `property_bundle.py`：恢复源镜像属性文件，按 Android 10 顺序合并属性与客体覆盖值。
- `system_packages.py`：遍历镜像系统应用目录，恢复全部 78 个系统 APK 及 ARM64 库链接；加上 `framework-res` 为 79 个系统包。
- `system_image.py`：按源镜像 inode、类型与权限补齐其余不可变系统文件、目录和链接；现有运行库替换优先，ARM64 ELF 经 APK 原生库目录映射执行。
- `media_bundle.py`：收集 dlopen/JNI 加载的媒体库、软件解码组件及配套资源，纳入 ELF 依赖闭包。
- `HostConnect`：保留旧 netd 连接协议，遇到 `EBADMSG` 时适配宿主扩展 `ON_CONNECT`，通过宿主 fwmarkd 标记真实 socket。
- `HostLinearMemory`：给 CPU Codec2 组件提供共享 memfd，并在非客体环境转发原 ION 接口。
- `HostBatteryBridge` / `HostSensorBridge` / `HostVibratorBridge` / `HostAudioBridge`：通过宿主公共 API 提供设备桥，方向事件共享 `SensorEventValues` 校验。
- `build-checks.sh`：构建系统服务启动及桌面、输入验收入口。
- `stage.py`：按逻辑名称、字节数和 SHA-256 生成 APK 输入清单。
- `RuntimeFiles`：校验包内库、安装私有数据并创建客体库链接。
- `GuestRuntime`：准备属性/linker 配置并启动 Android 10 ART。
- `FrameworkSession`：编排私有 Binder/HwBinder、系统服务、合成器和输入进程的启停。
- `GuestCommand` / `FrameworkSession.installApk`：通过客体 Binder 命令安装第三方 APK，不调用宿主安装器或 `su`。
- `PrivateKeyStore`：目前无密钥存储；`clear_uid` 对空存储返回 Android 10 的成功码 1，使 PackageManager 清理与卸载应用正常完成。
- `RuntimeIdentity`：核验 UID、capability、SELinux、执行库映射和文件回读。

## 源镜像路径补全

`prepare-desktop.py` 生成独立的 `artifacts/container/system-image/inputs.json`，
覆盖源镜像的 4463 个路径，其中 `/system/bin` 为 390 项。恢复包括 shell、toybox、
toolbox、cmd、sqlite3、系统脚本、APEX 配置、权限文件与其余原始系统资源。
普通文件保留模式位，共享 inode 文件用硬链接恢复，符号链接保留原始目标。
`.bc` / `.gz` 在 APK 中增加 `.asset` 后缀，并按 `installPath` 恢复原名，
避免安装器误判 ABI 或打包器改写文件。

Binder、Bionic、图形与媒体兼容库继续优先于原始同名库，`/data` 用户数据不进入
不可变恢复包。原镜像传感器 2.0 声明以空片段保留路径，服务由宿主传感器 1.0
清单声明；未启动的 GNSS 2.0 也以空片段保留路径，避免 SystemServer 无限等待。
系统文件齐全与硬件桥接可用性
分别验收，不以文件存在代替实际执行结果。

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-system-image.py
# 在已启动的安装版中检查全部路径，以及 shell、属性、链接与 pm 脚本。
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/apk-guest-command.py --main io.a10vm.guest.SystemToolsCheck
```

准备并验证：

```sh
sh tools/prepare-native-display.sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-art.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-desktop-egl.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-system-server.py
sh tools/build-termux.sh :app:assembleDebug :app:lintDebug
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/verify-native-display-apk.py
```

普通 Termux UID 下的 DEX 线程和文件往返检查通过；五种错误身份/映射负例均被检出。
图形回归使用与 APK 一致的单一 native 目录，避免分散的 `/data` 宿主路径被映射进客体。
ART 检查使用解释执行，其耗时仅衡量检查进程，不代表 Android 桌面冷启动时间。

完整桌面离屏验收包含 Launcher 窗口完成绘制、上滑应用抽屉、点击设置和 HOME 返回，
并确认 Launcher 全程存活且没有重启。APK 实机结果单独记录，详见
[交付证据](../docs/evidence/native-system-apps.json)。

全量系统包已通过客体 PackageManager 枚举，图库已显示真实界面。相机 APK 的恢复
与相机硬件桥接、宿主网络接通、宿主媒体共享分别推进，不以安装包存在代替能力验收。

微信 `8.0.77` / `com.tencent.mm` 已实际安装，安装命令返回 `Success` 和
`guest_command_result=0`。`utimensat` 采用客体路径映射并保留 `futimens` 的空路径语义；
`GuestNetworks` 接收安装收尾的 `trafficSetNetPermForUids`，避免 PermissionMonitor
抛出异常杀死 PackageManager。该接口不修改宿主网络权限或内核规则。

`0.2.15` 保留数据覆盖升级后，经 App 服务入口启动 12.48 秒进入桌面，
5 秒稳定观察通过；管理页与全屏切换后，同一 system_server 存活且替换 Surface 完成呈现。
服务入口绕过管理页点击；该耗时不是点击启动耗时。UID 为 `10698`、CapEff 为零、SELinux 为 `untrusted_app`。
设备 root 仅用于开发安装及自动化采集，应用和客体本身保持免 root。

以下联网、WebView 与媒体结果来自历史 `0.2.9` 验收，未在 `0.2.15` 全量重跑。
当时实际点击启动 16.44 秒，15 秒稳定观察通过；联动后 system_server 在
208.85 秒时仍为同一 PID，HOME 返回 Launcher3。

启动修复覆盖非法设备方向枚举、Wi-Fi typed List/初始回调和 `libmedia_jni.so` 缺库。
`MediaCheck` 实际创建并释放 `MediaPlayer`，覆盖充电提示触发的 JNI 初始化路径；
`DeviceCheck` 已通过电池广播、25 个传感器及加速度计事件检查。
本轮补齐 Codec2 VINTF 清单、Stagefright 动态插件及产品提示音。软件 YUV 上传保持
无 DMA 通道；`ColorPixels` 使用 RGBA8 读回后转换 RGB/RGB565，覆盖奇数宽度的紧密
多行读写，修复媒体读帧残留 GL 错误导致桌面会话退出。

Chromium renderer 的 seccomp 拒绝 `readlinkat`，常规路径检查因此阻止字体配置读取。
`GuestPaths` 只对已打包为普通副本的字体配置和单层字体文件直接映射；其他路径保留
既有链接解析。回归先验证 `readlinkat` 确实返回 `EPERM`，再检查字体配置及字体内容。

历史 `0.2.9` APK 的普通 HTTPS 与 `Network.openConnection` 均返回 200 并读取正文；WebView
`139.0.7258.143` 显示微信官网中文、图标及本地 JavaScript 文字，canvas 测量为 42.4。
`MediaCheck` 枚举 33 个解码器，解出 160×96 的 H.264 视频帧，1 秒 H.264/AAC MP4
播放完成。WebView 提供程序和微信保留在既有客体数据中；本轮覆盖安装保留这些数据。

录音、拍摄、定位、蓝牙、完整 keystore 和微信完整登录日用继续分别推进。

`0.2.22-clear-data` 修复客体内清理应用数据时 `clear_uid` 抛出
`UnsupportedOperationException`、继而杀死 system_server 的问题。回归通过真实
PackageManager 安装独立测试 APK，写入 CE/DE 文件、缓存和偏好，两轮清理后确认
删除、重启重置及 HOME 绘制；成功后移除测试 APK。复现与验收共用同一入口：

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-apk-clear-data.py --label current
```
