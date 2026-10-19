# P2：Android 10 私有 Binder API

本模块在普通 APK UID 的独立进程中运行 Android 10 `libbinder` API，并用应用内
Unix socket broker 承载 Binder wire protocol。它覆盖服务注册、同步事务、嵌套回调、
FD、oneway 顺序、并发、对象引用、死亡通知和进程资源回收；这是私有 Binder 子关卡，
不是内核 Binder 驱动、HwBinder 或完整 G2 的验收。

## 构建与复现

在仓库根目录执行：

```sh
sh container-probe/hwbinder/prepare-apk.sh \
  artifacts/guest/android10-display-v4.raw \
  artifacts/container/gate-0-repeatable/report.json
python3 container-probe/binder/test-native.py
python3 container-probe/hwbinder/test-native.py
sh tools/build-termux.sh -PcontainerProbe -PcontainerBinder \
  :container-probe:assembleDebug :container-probe:lintDebug --offline
sh container-probe/test-device.sh --local-root --binder
python3 container-probe/test-cleanup.py
```

`hwbinder/prepare-apk.sh` 会先准备现有的 companion、动态 Bionic、属性和 Binder
闭包，再构建 Binder/HwBinder probe，并生成两份输入摘要。设备脚本也支持 ADB；
省略 `--local-root`。Root 只用于开发安装、Instrumentation 调度和报告回收。
broker、registry、service、client 与 disconnect looper 都由 APK 子进程启动并继承
普通 APK UID。

## 模块边界

v0.2.52 的 `BrokerDispatch.cpp` 只遍历状态变化的进程及其线程，发送路径只处理
有数据的连接；`BrokerPoller` 保留 epoll 背压通知。`measure-broker-idle.py --registered`
可比较已注册且停在 Read 的空闲 context。回归覆盖 Read 停放、定向嵌套回调、调用
结束后的读者恢复、线程池唤醒和 Rearm，完整实机结果见
[性能记录](../../docs/evidence/app-performance-miui-v052.json)。

- `archives.txt` / `sources.sha256` 固定 Android 10 `android-10.0.0_r47` 的选定源码；
  `select-sources.py` 与 `compile.sh` 生成实际构建输入。
- `platform.patch` 只把 `ProcessState` / `IPCThreadState` 的 open、ioctl 与 close
  操作接到私有传输层，并为应用内运行裁剪 system logging / VNDK 入口。
- `native/` 的 `liba10binder.so` 和 `Broker*.cpp` 通过 Unix socket broker 转发
  Binder 命令与事务；broker 不访问宿主 `/dev/binder`。
- `test/` 构建 service、registry、client、resource inspector 和 disconnect looper。
- `BinderRuntimeProbe` 负责校验 APK UID、SDK 29 私有属性、子进程生命周期、完整
  检查集合、统计回收和工作目录清理；`test-native.py` 覆盖同一 native 闭包。

## 本轮结果：2026-10-07

本机宿主 SDK 36、ARM64、4 KB 页实测通过；APK 为 min SDK 30 / target SDK 35，
本轮受测 UID 为 `10764`。设备报告中的 Binder 24/24 client checks、registry context、
service registration、同 UID 子进程、Binder 资源回收、broker 断开后的 looper 正常
退出均通过；原生 harness 同样通过 24 项检查。registry 在资源核验后被主动终止，
其 `143` 退出码是该清理步骤的预期结果。

Binder 资源最终统计的进程/缓冲/调用计数归零，Instrumentation 临时工作目录已删除。
设备与 native 原始报告分别保存在 `artifacts/container/runtime/binder/device/report.json`
和 `artifacts/container/runtime/binder/local-report.json`；精简验收记录见
[P2 Binder 证据](../../docs/evidence/container-runtime-binder.json)。

本轮 APK 同时包含 Binder 与 HwBinder 输入，归档为
`artifacts/container/runtime/binder/probe.apk`，版本 `10 / p2-hidl-values`，
3,751,216 字节，SHA-256 为
`664f5e511bc6533b8c9986528ff9f83424045fb0abc5ce590baf34c9d2a3725a`。APK v2 签名、
4 KB ZIP 对齐通过；native libs 仍为压缩条目，因此本轮未宣称整包 16 KB ZIP 对齐；Lint 为 0 errors / 8 warnings。完整报告的
`completeG2` 仍为 `false`。

## 下一步

HwBinder 的独立结果见 [`hwbinder/README.md`](../hwbinder/README.md)；随后推进 ART、
系统合成和完整 Android 10 桌面。当前结果不代表内核 Binder/HwBinder、跨 UID 安全
策略、完整系统服务或桌面启动行为。

KISS / YAGNI：只实现当前 Binder API 子关卡，不替代系统驱动或扩大到完整服务框架。
SRP / DRY：源码构建、socket transport、native 场景和 APK 生命周期分别由独立模块
负责，并复用已有动态运行时、属性准备和进程管理。
