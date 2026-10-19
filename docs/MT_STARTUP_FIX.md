# MT 启动回归修复

版本：`0.2.43-mt-startup`，versionCode 53。
下载：`/storage/emulated/0/Download/A10VM-0.2.43-mt-startup.apk`。
SHA-256：`ff052462d950c3bbcef6d21939b2b57c6f6d4e67dd7f6d813934f0a700ef0475`。

## 故障与修复

`0.2.41` 把应用安装包代码路径转为物理路径后，linker 解析 namespace 的
搜索目录时混入客体路径映射，丢弃 APK 路径。`0.2.42` 在 `resolve_paths`
入口复用 `guestPhysicalPath` 统一坐标，真实 APK 内 ELF 加载用例通过。

MT 的实机启动仍抛出 `UnsatisfiedLinkError`，提示原生 `<clinit>` 缺少实现。
定向系统调用记录确认 `libmtprotect.so` 已成功映射。保持同一 linker/libc、
MT APK 和应用数据，仅撤去全局 `ApplicationInfo.CREATOR` 转换，MT 即正常绘制。

`ApplicationCodePaths` 改为委托应用进程的 `IPackageManager` 查询。
基础包、split 与 `PackageInfo.applicationInfo` 的复制对象提供实际可读路径；
启动 parcel、原对象、Binder 对象与系统 APK 路径保留原语义。
应用入口安装委托，系统启动与 WebView 辅助入口使用共享初始化。
转换依赖运行环境的 rootfs 与现有路径判断，没有 MT 或宿主版本特例。

## 验证

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD sh guest-runtime/test-code-paths.sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-app-launch.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-apk-desktop.py --direct-start --stability-seconds 3 --output artifacts/xclone-hook/device/v43
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-apk-app-compat.py --case mt --label mt-v43 --settle-seconds 10
```

- 安装包直接 SVC 读取、隔离 namespace 内 APK 库加载及符号调用通过。
- 包查询转换、启动 parcel、原 Binder 身份、空值、重复安装与 split 通过。
- 真实 WebView 子 zygote 监听及普通辅助 main 通过。
- 最终包冷启动 11.276 秒进入 Launcher，3 秒稳定检查通过。
- MT `bin.mt.plus/.Main` 已绘制，10 秒观察没有崩溃，system_server 存活。
- 实机截图已人工检查，显示 MT 双栏文件列表。
- 客体 UID/EUID 10698、CapEff=0、SELinux 为 untrusted_app。
- APK v2 签名、1060 个原生输入、2209 个运行时文件、114 个系统 APK 校验通过。
- 构建与 lint 通过，lint 为 0 Error / 0 Fatal / 3 Warning。

私有证据：`artifacts/app-compat/mt-v42/` 是失败记录，`mt-v43/` 为最终包验收；
`artifacts/xclone-hook/device/mt/mt-v43-host.png` 是最终界面截图，
`device/v43/apk-desktop-report.json` 是冷启动记录。完整日志保留在 artifacts。

## 实现原则与后续

KISS/YAGNI：仅修正复现的路径坐标和转换范围。
DRY：基础包和 split 共用映射，复用现有 rootfs 判断。
SRP：包查询转换放在独立模块，linker 负责 namespace 路径解析。

本轮验收范围是 MT 主界面启动。小X的 hook 初始化保持成功，应用上下文路径
引发的原生 APK 读取问题仍待继续处理，详见 `XCLONE_HOOK_DIAGNOSIS.md`。
其他宿主安卓版本仍需分别做启动验收。
