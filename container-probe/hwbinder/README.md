# P2：Android 10 私有 HwBinder API

本模块在普通 APK UID 的独立进程中运行 Android 10 `libhwbinder` API。context
manager、service、client 和断开 looper 通过应用内 Unix socket broker 组成可复现的
HwBinder wire channel，覆盖服务注册、同步 RPC、回调、嵌套 RPC 和 calling identity
恢复。这是源码 API 子关卡，不是宿主内核 HwBinder 驱动或完整 G2 验收。

## 构建与复现

在仓库根目录执行：

```sh
sh container-probe/hwbinder/prepare-apk.sh \
  artifacts/guest/android10-display-v4.raw \
  artifacts/container/gate-0-repeatable/report.json
python3 container-probe/hwbinder/test-native.py
sh tools/build-termux.sh -PcontainerProbe -PcontainerBinder \
  :container-probe:assembleDebug :container-probe:lintDebug --offline
sh container-probe/test-device.sh --local-root --binder
python3 container-probe/test-cleanup.py
```

设备脚本也支持 ADB：省略 `--local-root`。准备脚本复用 companion、动态 Bionic、
属性和 Binder 的已核对闭包，再编译 `libhwbinder.so` 与 probe，写入
`hwbinder-inputs.json`。Root 只用于开发安装、Instrumentation 调度和报告回收；
受测程序及其子进程始终运行在普通 APK UID。

## 模块边界

- `archives.txt`、`sources.sha256` 和 `select-sources.py` 固定 Android 10
  `android-10.0.0_r47` 的 `libhwbinder` 源码及实际编译输入。
- `build-libraries.sh` 使用 Binder 的私有 transport、同版运行库和最小平台补丁，
  生成 source-built `libhwbinder.so`；原件与派生输入分开保存。
- `build-probes.sh` 构建 registry、service、client 和 looper 场景；`test-native.py`
  在本机复现相同的 broker、回调、资源回收和断开流程。
- `HwBinderRuntimeProbe` 校验 SDK 29 私有属性 seed、完整检查集合、子进程身份、
  服务生命周期、统计回收、looper 退出和临时目录清理。

## 本轮结果：2026-10-07

本机宿主 SDK 36、ARM64、4 KB 页实测通过；APK min SDK 30 / target SDK 35，本轮
受测 UID 为 `10764`。native 与设备端均通过 16/16 client checks：context manager
发现、service lookup、同步 RPC、回调投递、回调嵌套 RPC、回调 calling identity
以及 identity 恢复；另有嵌套 SG 缓冲、native_handle 双 FD、FD_ARRAY 生命周期、
`hidl_vec<hidl_string>`、终止符校验和 `hidl_memory` 共享修改。registry context、
service registration、同 UID 子进程、资源回收和 broker 断开后的 looper 正常退出均通过；
service/registry 的 `143` 是主动终止清理步骤的预期退出码。

设备报告和 native 报告分别保存在：

```text
artifacts/container/runtime/binder/device/report.json
artifacts/container/runtime/hwbinder/local-report.json
```

精简验收记录见 [HwBinder 证据](../../docs/evidence/container-runtime-hwbinder.json)。
归档 APK 为 `artifacts/container/runtime/hwbinder/probe.apk`（与 Binder 合并包相同），
版本 `10 / p2-hidl-values`，3,751,216 字节，SHA-256 为
`664f5e511bc6533b8c9986528ff9f83424045fb0abc5ce590baf34c9d2a3725a`。APK v2 签名、
4 KB ZIP 对齐通过；native libs 为压缩条目，本轮未宣称整包 16 KB ZIP 对齐；Lint 为 0 errors / 8 warnings；安装清理回归为 9 项。

## 限制与后续

broker 使用应用内 Unix socket，不访问宿主 `/dev/hwbinder`，因此当前结果不代表
内核驱动、跨 UID 安全策略、系统服务或完整 Android 10 桌面。`completeG2` 仍为
`false`；下一阶段推进 ART、系统合成和完整桌面验收。

KISS / YAGNI：只实现当前 HwBinder API 子关卡，不复制完整系统服务框架。SRP / DRY：
源码构建、transport、native 场景和 APK 生命周期各自负责明确职责，并复用 Binder、
运行时和属性准备路径。
