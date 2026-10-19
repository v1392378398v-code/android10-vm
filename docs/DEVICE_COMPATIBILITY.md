# 跨设备启动兼容记录

日期：2026-10-18。联想最后验证版本：`0.2.82-miui12-guest-oom-priority`（versionCode 92）。
当前开发机交付版本为 `0.2.88-miui12-android9-aosp-ime`（versionCode 98）。

联想排查已按用户要求暂停。v0.2.82 在该机完成覆盖安装，启动验收约 114 秒后
ADB 命令超时并断开，未取得观察结束时的进程及内存记录；整机稳定性尚未通过。
后续 v0.2.85 的启动终端与管理页在开发机验收，记录见
[管理页与启动日志](MANAGEMENT_UI.md)，不作为联想稳定性通过的证据。

## 实机原因

Lenovo L78071 的宿主系统报告 Android 16 / SDK 36，但运行 Linux
`4.9.186-perf+`，ARM64、4 KiB 页、SELinux Enforcing。已安装的 v0.2.75
能启动宿主服务、ART、私有 Binder 和 Adreno 616 图形链路，但客体在安装
SettingsProvider 时中断：

```text
ashmem: fcntl(F_ADD_SEALS) failed: Invalid argument, no memfd support.
CursorWindow: ashmem_create_region() failed: errno=13.
CursorWindowAllocationException: Could not allocate CursorWindow ... due to error -13.
System: Failure starting core service
```

该内核支持基本 memfd，但缺少 `F_SEAL_FUTURE_WRITE`。ROM libcutils 因此退回
直接打开 ashmem 的路径，遭遇权限错误。随后 SettingsProvider、系统服务初始化失败，
再出现的 Binder bad descriptor 是启动中断后的连锁错误。

开发机 PJZ110 使用 6.6 内核且支持所需封印。这解释了两台手机的差异：
Android 大版本和 ARM64 ABI 相同，不代表内核接口与厂商策略相同。

## 修复边界

`GuestSharedMemory.cpp` 为客体的 ashmem API 提供统一入口，通过实际系统调用
探测封印能力。支持时直接创建 memfd；缺少能力时，经既有私有 socket 通道请求
宿主 `SharedMemory.create`，通过 `SCM_RIGHTS` 接收描述符。宿主桥接模块使用
公开 SDK，连接仅接受宿主应用自身 UID。

只读保护对 memfd 使用封印，对 ashmem 使用其原有 ioctl。保留已有写映射可用、
新增写映射被拒绝的行为，避免把封印错误忽略后继续运行。此路径不要求 Root，
也不依赖设备型号、关闭 SELinux 或降低应用 targetSdk。

宿主桥接在客体启动前创建，随会话关闭；内存、传输、启动生命周期保持独立职责。
复用已有 `HostStreamServer` 和 `HostDeviceSocket`，不新增另一套 IPC。

v0.2.78 实机首次接入桥接后还暴露出流式传输问题：宿主 `writeInt(0)`
逐字节写入状态，携带 `SCM_RIGHTS` 的首次接收即使指定 `MSG_WAITALL`，也可能
只返回一个字节。原接收函数要求一次收满四字节，将有效描述符关闭并返回
`EPROTO`（71）。v0.2.79 循环收满状态并保留各次接收的描述符，发送端使用
一次数组写入；错误、截断路径仍关闭已接收描述符。

## 图形 HAL 的目录顺序问题

v0.2.79 在联想手机上已通过 SettingsProvider 初始化，完成系统开机和用户解锁，
但绘制持续失败。`GraphicBufferAllocator` 对 1×1 和桌面大小的请求均返回错误 1，
该值是 HAL 的 `BAD_DESCRIPTOR`；框架随后将它表现为内存分配失败。

客体同时保留了配套 `android.hardware.graphics.mapper@2.0-impl-2.1.so` 和 ROM 的
`android.hardware.graphics.mapper@2.0-impl-qti-display.so`。Android 10 libhidl 按
`readdir` 顺序尝试匹配库。开发机目录里配套实现先出现，联想手机上原厂实现先出现。
两个实现都可成功创建描述符，但与当前 allocator 的编码不同：

- 原厂 mapper：七个字，首字 `0x76312e30`。
- 配套 mapper / allocator：七个字，首字 `0x94870000`。

独立 native 检查已重现原厂候选失败、配套候选通过。v0.2.80 在现有 HAL 选择模块
`GuestHardware.cpp` 中接入 `android_load_sphal_library`，客体的 mapper 2.0 实现
候选统一加载配套库；其他 HAL 以及宿主调用继续交给原加载函数。保留 ROM 文件，
消除对目录枚举顺序的依赖。

## 慢设备的输入进程启动

v0.2.80 在联想上已完成系统开机、用户解锁和桌面绘制，原有
`BAD_DESCRIPTOR` 与 `EGL_BAD_ALLOC` 未再出现。随后启动流程清理了客体：
本轮 `framework-input.log` 已创建但大小为零，输入进程尚未输出就绪标记。
原流程只给输入 ART 进程 3 秒，系统服务 ART 进程则为 30 秒。

v0.2.81 复用同一 30 秒 ART 启动期限，并在启动异常中保留具体失败原因、
client 和 input 日志，便于区分超时与进程退出。验收脚本等待本轮输入就绪，
核对输入进程 UID、capabilities 和观察结束时的存活状态。该调整的实机效果
以本节后续验收结果为准。

## 整机卡死现场

用户报告 v0.2.79 验收期间整机卡死，ADB 随后失联，该版本未通过整机验收。
重启后已停止 A10VM 并保留客体日志。实机是 4 GB 内存机型，`MemTotal=3769016 KiB`；
停止客体后的 `MemAvailable` 为约 1.27–1.55 GiB。启动现场存在批量后台进程拉起、
图形分配失败和 HOME 重试。v0.2.81 及之前的 `GuestMemory` 仅接收 LMKD 指令
并调整 CPU 优先级，没有向宿主内核发布客体应用的 OOM 优先级。

同一时间段宿主 `qcrild` 两个进程在 `ProfileHandler::releaseQdpAttachProfile` 中
发生空指针崩溃。重启后的 pstore 为空，没有上一轮内核日志；这些记录尚未建立
整机卡死的完整因果链。后续验收使用独立 Root 内存观察器，连续两次可用内存低于
320 MiB 时仅停止本次 A10VM 运行，并保存采样。该观察器属于测试工具。

v0.2.81 的受控启动在第 108、109 次采样分别只有 313572、321228 KiB 可用内存，
应用 UID 进程达到 73 个，观察器按约定停止了 A10VM；宿主保持响应。这次客体
已完成桌面检查，输入尚未就绪，未通过完整验收。该结果证实本轮启动存在内存压力，
仍不足以还原 v0.2.79 整机卡死的完整因果链。

## 客体 OOM 优先级

独立检查通过真实 LMKD 优先级报文将一个临时子进程标记为后台 `950`。
旧接收代码执行后，内核 `/proc/PID/oom_score_adj` 仍为 `0`。CPU nice 只影响调度，
宿主已有的低内存回收需要 OOM 优先级来选择后台进程。

v0.2.82 在既有 `GuestMemory` 接收端同步写入该内核字段，仅处理客体应用 UID，
通过已打开 proc 文件的实际所有者限制为宿主应用自身 UID。负的客体优先级映射
到 `0`，后台值按原报文写入；宿主内核和既有 LMK 继续决定是否回收。CPU 调度
仍由 `GuestScheduling` 独立负责，没有新增轮询杀进程或型号分支。

`GuestMemoryPriorityCheck` 在同一真实应用域内以临时子进程检查真实报文效果：
旧代码稳定失败（期望 `950`、实际 `0`），新代码验证后台 `950`、前台恢复 `0`、
负值归 `0` 和系统 UID 忽略均通过。联想 instrumentation 记录 UID 10212、
SELinux `untrusted_app`；完整桌面及内存压力效果另行验收。

## 验证

- 旧版在远端通过实际 VmService 启动入口重现同一 CursorWindow 错误。
- 远端宿主公开 SharedMemory API 的创建、映射、内容和只读保护检查通过。
- `sh guest-runtime/test-shared-memory.sh` 覆盖正常 memfd 和封印探测失败两条路径，
  验证描述符传输、CLOEXEC、跨映射内容与写保护不可回退。
- 分段状态测试在旧接收函数下稳定失败，在新接收函数下通过，保留红、绿日志。
- 联想手机上使用真实 `HostSharedMemoryBridge` 与 native 客户端联测通过，
  UID 10212，覆盖创建、CLOEXEC、读写、已有写映射保留、新写映射受限与保护不可回退。
- `build-mapper-check.sh` 与 `test-guest-mapper.py` 不启动桌面，调用真实 mapper
  工厂创建 1×1 描述符；旧版原厂候选失败，修复后原厂与配套候选均通过。
- 原有文件系统 87 项、进程身份和四个负例通过。
- APK 文件及签名校验通过；lint 0 Error、0 Fatal、3 Warning。
- v0.2.79 开发机的系统开机与 30 秒稳定观察通过；前台 Surface 检查期间焦点切到
  其他应用，该轮可见界面检查未通过。联想手机完成开机但图形描述符错误持续出现，
  随后用户报告整机卡死。
- v0.2.80 开发机完整 APK 冷启动 45.871 秒，桌面、前台 Surface 和 30 秒观察通过；
  客体 UID 10326、CapEff=0、SELinux untrusted_app。QQ 两轮网页验收见
  [QQ 网页修复](QQ_WEB_FIX.md)。联想已完成桌面绘制，但输入启动阶段未通过，
  产品主动清理了客体；本轮宿主保持响应，600 次采样最低可用内存
  451280 KiB，最多 70 个应用 UID 进程，内存观察器未触发停止。
- v0.2.81 开发机完整 APK 冷启动 21.748 秒，输入就绪与同一 system_server
  30 秒稳定观察通过。system_server / input UID 均为 10326、CapEff=0，
  域为 untrusted_app。验收时前台曾切到其他应用，未保存本轮宿主截图；
  现有安装器 `com.miui.packageinstaller` 版本 55600 保留。

远端 ROM 禁止 shell 注入触摸，私有服务也不向 shell 导出。旧版复现曾使用独立
`io.a10vm.devicecheck` instrumentation APK。用户确认设备有 Root 后，启动控制与
日志采集使用 `su`；产品代码不调用 `su`，实机验收继续核对普通应用 UID、
`CapEff=0` 和 SELinux Enforcing。测试脚本的 `--root-control` 仅影响远端测试控制。
原始证据保存于私有 `artifacts/device-compat/`。

mapper 的独立回归命令如下，`SERIAL` 为已配对的 ADB 连接地址；测试运行在应用 UID：

```sh
sh container-probe/graphics/build-mapper-check.sh
adb -s SERIAL push artifacts/device-compat/mapper/check /data/local/tmp/a10vm-mapper-check
adb -s SERIAL shell 'run-as io.a10vm.miui sh -c "cp /data/local/tmp/a10vm-mapper-check files/guest-runtime/mapper-descriptor-check; chmod 555 files/guest-runtime/mapper-descriptor-check"'
python3 tools/test-guest-mapper.py --serial SERIAL --output artifacts/device-compat/mapper-installed
```

完整桌面验收使用下列命令，另行启动上述内存观察器保存现场：

```sh
python3 tools/test-apk-desktop.py --serial SERIAL --root-control \
  --package io.a10vm.miui --direct-start --timeout 300 \
  --stability-seconds 180 --output artifacts/device-compat/installed
```

v0.2.87 将 ARM64 宿主最低版本设为 Android 9 / API 28。宿主显示库与编码客户端
使用 API 28 构建，公开 NDK 强符号核对通过；应用及两个库模块的 NewApi 检查通过。
API 28/29 使用旧版窗口边距和沉浸式接口，Wi-Fi 设置、前台服务、网络信息和帧率
接口按系统版本处理。Android 9 实机回归仍待补充。

16 KiB 页设备及其他 GPU、ROM、
内核组合仍需分别验证，两个 Android 版本号相同的设备不能替代这一验收。
