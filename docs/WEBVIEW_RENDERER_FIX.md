# WebView 隔离渲染进程启动修复

版本：`0.2.44-webview-renderer`，versionCode 54。
下载：`/storage/emulated/0/Download/A10VM-0.2.44-webview-renderer.apk`。
SHA-256：`e7e1825c41b49debd9d62a5695d192235edc6fabf2fee85cce5ad02712b8bad2`。

## 根因与修改

`0.2.43` 的 WebView 提供程序和原生库已成功加载，但隔离 renderer 在
`GuestApplication.main` 调用 `ApplicationCodePaths.install()` 时抛出
`IllegalStateException: Guest package manager unavailable`，未进入
`ActivityThread.main`。ActivityManager 随后报告 `failed to attach` 和
`start timeout`，浏览器窗口显示但网页停在加载阶段。

包查询路径适配用于普通应用读取实际 APK。隔离进程的系统服务访问边界不同，
这里查询 PackageManager 就会提前退出。`ApplicationCodePaths.install()`
在查询前使用 `android.os.Process.isIsolated()`，隔离进程直接返回。
判断来自客体 Android API，包含系统自身的 UID 和用户处理，不依赖宿主版本、
应用包名、具体 renderer UID 或 WebView 版本。

普通应用继续使用独立的包查询委托；代码路径、split APK、原 Binder 身份及
启动 parcel 的既有处理保持一致。

## 回归与实机结果

新增回归通过生产 `AppLaunch` 启动隔离 UID 的独立进程，在实际 Android 10
运行库内调用路径适配，要求 PackageManager 保持未初始化且子进程成功退出。
测试在修复前因包管理服务查询失败而退出，修复后通过；普通辅助 main 和
真实 WebView 子 zygote 监听也通过，总耗时 5.662 秒。

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD sh guest-runtime/build-checks.sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-app-launch.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-code-paths.py
sh tools/build-termux.sh :app:assembleDebug :app:lintDebug
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/verify-native-display-apk.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-apk-webview-loading.py \
  --label webview-v44-fixed --url https://m.v.qq.com/ \
  --url https://weixin.qq.com/ --url https://m.bilibili.com/
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-apk-app-compat.py \
  --case mt --label mt-v44-webview --settle-seconds 5
```

- 普通应用包查询、直接 SVC 读取 APK、split 和隔离 namespace 原生库加载通过。
- 构建通过；lint 为 0 Error / 0 Fatal / 3 Warning。
- APK v2 签名、1060 个原生输入、2209 个运行时文件和 114 个系统 APK 校验通过。
- 本机 PJZ110 / Android 16 保留数据覆盖安装成功。
- 首次冷启动 9.856 秒进入 Launcher；Surface 接入和 3 秒稳定检查通过。
- 腾讯视频、微信官网、B 站三页均为 HTTPS 200、`readyState=complete`；
  正文、JavaScript 查询、图片加载、WebView 附着和主进程存活检查全部通过。
- MT Activity 已绘制，5 秒观察没有崩溃，system_server 当时存活。
- 客体的宿主执行 UID/EUID 10698、CapEff=0、SELinux 为 `untrusted_app`。
  开发安装和采集使用设备 root，APK 运行入口保持免 root。

## 验证边界

网页检查期间宿主切至其他应用，`guest_display_interactive=false`，客体截图为
黑图。MT 验收的宿主截图也因窗口焦点不在 A10VM 而跳过。网页 DOM 和加载结果
已验证，这些黑图不作为前台像素绘制的成功证据。

后续补拍时原客体会话已经停止；重新启动的 Launcher 完成初始化，但 Surface
检查期间宿主再次切出，检查返回 `APK did not automatically open a presented
desktop Surface`。本轮前台网页画面验收仍待确认。其他宿主版本、网页视频播放
及第三方 App 内置 WebView 的完整交互尚未逐项验收。

原始记录：`artifacts/webview-viewport/webview-v43-regression/`；
三站加载：`artifacts/webview-viewport/webview-v44-fixed/report.json`；
冷启动：`artifacts/webview-viewport/webview-v44-desktop/apk-desktop-report.json`；
MT：`artifacts/app-compat/mt-v44-webview/report.json`。
可提交的摘要见 [v44 验收摘要](evidence/webview-renderer-v44.json)。

## 实现原则与后续

KISS/YAGNI：只修复首条异常所在的初始化边界，未引入新的启动机制。
DRY：复用 Android 隔离进程判断和现有包路径委托。
SOLID/SRP：包查询适配仍由独立模块负责，应用启动器仅编排初始化。
下一步在前台固定窗口下验收实际页面绘制，并在其他宿主安卓版本重复同一启动用例。
