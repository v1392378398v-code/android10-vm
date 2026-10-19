# 当前版本验证

版本：`0.2.88-miui12-android9-aosp-ime`，versionCode 98。
日期：2026-10-18。完整包已覆盖安装并导出至手机下载目录。
可提交摘要见 [本轮证据](evidence/android9-aosp-ime-v088.json)。

## 本轮结果

| 验证项 | 结果 |
| --- | --- |
| 构建 / 应用 Lint | 通过，0 Error、0 Fatal、8 Warning |
| 客体运行库 / 显示模块 Lint | 分别 0 Error、0 Fatal；2 / 0 Warning |
| APK 签名和逐文件校验 | 通过；2631 个原生文件、5152 个资源、320 个系统 APK |
| Android 9 宿主原生依赖 | 两个宿主 ELF 均为 API 28，378 个强符号导入均有对应 NDK stub |
| ROM 打包 / 配置回归 | 15 / 6 项通过 |
| 输入法打包回归 | AOSP APK 与 JNI 配对、重复准备和旧系统文件清理通过 |
| 完整包实机冷启动 | 47.125 秒，桌面 Surface、输入就绪和随后 30 秒稳定观察通过 |
| 运行身份 | system_server / 输入进程均为 UID 10326、CapEff=0、untrusted_app |
| AOSP 输入法 | 真实文本框内正常弹出，用户确认可用；升级保留用户后来选择的其他输入法 |
| 已安装应用导入 | 应用列表实际服务记录“已导入 1/1”；另一次拆分包会话检查确认 base 与 split 均已安装 |
| UI 自动化范围 | 读取采用唯一 XML 路径；连续动画及用户操作会中断自动脚本，完整 UI 自动化本轮未通过 |
| Android 9 实机 | 待验证 |

输入法首次版本缺少压缩 APK 中的 JNI，导致加载失败；本轮改用同一份 Android 10
输入的 AOSP LatinIME APK 和原生库，并加入系统预装库目录检查。
全屏页在窗口创建前获取系统栏控制器的问题已修正调用时机，完整包实机通过。
MIUI 对 shell 安装的限制通过使用既有客体系统管理身份解决；宿主仍为普通应用 UID。

完整 APK：`/sdcard/Download/A10VM-MIUI12-v0.2.88-android9-aosp-ime.apk`。
大小：3,189,855,302 字节。SHA-256：
`0ff401f529c1be98d9f26dcea206ada2d89f9727ae492f408486e1c84d55ad42`。
导出副本摘要与构建产物一致。

## 构建与静态检查

- 宿主最低 API 28，客体 API 29；应用、客体运行库和显示模块分别执行 Lint。
- 宿主 renderer、编码客户端重新以 API 28 编译，强导入符号与 Android 9 NDK stubs 核对。
- 完整 APK 逐项校验原生 ELF、数据资源、系统 APK、输入法、JNI 导出和 v2 签名。
- ROM 增量打包 15 项回归通过，运行身份映射及 GPU 呈现另有独立回归。

## 实机验收范围

使用本机 PJZ110、Android 16、Linux 6.6、4 KiB 页。启动控制、截图和测试读取使用 Root；
客体 system_server 和输入进程仍核验普通应用 UID、CapEff=0。

本轮完成冷覆盖安装、系统和输入就绪、桌面画面、拆分 APK 导入、AOSP 键盘弹出，
并观察到重启后用户的输入法选择保留。英文、数字、删除的独立自动断言仍待补充。

Android 9 设备尚待实机回归；联想设备的整机稳定性仍待验证。
QQ 网页的历史结果与本轮未验证项见 [QQ 网页记录](QQ_WEB_FIX.md)。

原始报告、截图及日志保存在本地 `artifacts/device-compat/`；
仓库仅保存便于复核的摘要，测试应用和用户数据分别管理。

## 使用的验证入口

```sh
python3 tools/check-host-api28.py
python3 tools/test-rom-apk-stage.py
python3 tools/verify-native-display-apk.py \
  --runtime-prepared guest-runtime/build/rom-prepared/miui12
python3 tools/test-apk-desktop.py --package io.a10vm.miui --direct-start \
  --timeout 120 --stability-seconds 30 --output artifacts/device-compat/local-v088-final
python3 tools/build-keyboard-fixture.py
```
