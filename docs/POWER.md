# 手机发热优化：v48

版本：`0.2.38-display-power`，versionCode `48`。

## 已定位的问题

v46 在静止 QQ 页面持续提交画面，退回宿主桌面后客体显示仍保持打开。
后台原生图形、SurfaceFlinger 和 Binder 继续处理显示事务，构成持续 CPU/GPU 开销。
本轮处理显示生命周期与重复提交，保留 1080×1920、480 dpi、120Hz 活跃帧率配置。

| v46 场景 | 平均占用 CPU 核数 | 宿主 Surface 提交/秒 |
| --- | ---: | ---: |
| 静止 QQ | 1.875 | 84.85 |
| QQ 切到宿主后台 | 1.462 | 0 |

六秒测量记录在 `artifacts/performance/v46-heat-qq-before.json` 和
`artifacts/performance/v46-heat-qq-background-before.json`。
后台宿主 Surface 没有呈现，客体却仍在工作；Surface 数量本身不足以判断后台功耗。
主 Binder broker 的 21563 个采样中，`collectDeadNodes` 只占 1.34%，本轮沿用现有回收实现。

## 改动

- 将原生窗口可见性放入现有 metrics 数组，服务收到状态变化后调用客体 Android 10
  `IPowerManager.goToSleep/wakeUp`。后台关闭客体显示，前台唤醒，由系统处理应用与媒体生命周期。
- HWC 在 VSync Disabled、Power Off、DozeSuspend 时使用条件变量等待；状态改变或退出时唤醒。
  恢复后重置绝对单调时钟期限，保留活跃 VSync 的防漂移和跳过错过 tick 的行为。
- HWC 仅在收到新的 `setClientTarget` 后提交 client composition。相同 handle 的再次提交
  仍算新帧，保留可重复使用的视频/合成缓冲与 fence 处理。
- 服务没有 UI 客户端时跳过状态打包，避免后台无用的 UI 指标读取。

运行接口使用普通宿主应用 UID。客体系统权限由既有私有 Binder 实现，应用运行不依赖 Root。
宿主温控、核心绑定、UID 与机型配置均未参与本轮实现。

## 回归证据

实际 HWC 回归：`python3 guest-runtime/test-hwc-idle.py --stock` 重现关闭 VSync 后的周期唤醒；
`python3 guest-runtime/test-hwc-idle.py` 验证本轮修复。

| 150ms 关闭 VSync 的观察 | v46 HWC | 新版 HWC |
| --- | ---: | ---: |
| voluntary context switches | 19 | 1 |
| 线程阻塞检查 | 失败 | 通过 |

1 次为测试主线程等待本身；本轮 HWC 线程不再周期唤醒。
还覆盖 Power Off、恢复回调、同一真实 gralloc framebuffer 的新提交、300 次重复呈现和等待中关闭。
GPU host 有首帧提交且没有第 120 帧记录，排除零提交误判。

`python3 guest-runtime/test-desktop-egl.py` 通过普通 UID 验证：EGL/GLES、YUV 读回、视频 native buffer、
跨线程纹理同步、首帧字体图集、弹幕透明度与线程退出。

## GPU 原生图像保活

v47 试用期间捕获 `Desktop GPU missing handle 177 for opcode 10020`。
`10020` 是 `rcBindTexture`：原生 EGLImage 仍在使用其纹理，宿主颜色缓冲却已被回收。
原实现只增加 native buffer 的本地引用，没有为 EGLImage 增加 GPU 颜色缓冲引用。

v48 在 `eglCreateImageKHR(EGL_NATIVE_BUFFER_ANDROID)` 中保留宿主引用，
在 `eglDestroyImageKHR` 中先释放并 flush，再释放 native buffer 本地引用。
复用现有 `rcOpenColorBuffer2/rcCloseColorBuffer`，协议与图像结构保持一致。

实际 EGL 回归在图像存活时释放分配端引用、保留克隆 handle，等待 1.1 秒，
通过新分配触发回收后重新绑定并读回像素。旧库重现
`Desktop GPU missing handle 16 for opcode 10020`；新版通过延迟绑定并读回 `[64,64,64,255]`。
该检查针对同一个 opcode 和回收窗口，补充原有立即绑定视频像素测试。

## 实机与交付

最终证据：[display-power-v48.json](evidence/display-power-v48.json)。

| 实机场景 | CPU 核数 | 说明 |
| --- | ---: | --- |
| v46 QQ 后台基线 | 1.462 | 客体显示保持打开 |
| v48 QQ 刚打开后切后台 | 0.995 | 包含应用初始化与其他存活客体应用的工作 |
| v48 同一会话 QQ 再次切后台 | 0.427 | 相对基线降低约 71% |
| v48 抖音切后台 | 0.488 | 保留应用数据和存活进程 |

三次 HOME/返回共六次电源转换通过：后台 `isInteractive=false`，前台 `true`，
恢复后 Surface 有新呈现；GPU worker 数为 `29/29/29/29`，system_server 同一 PID `1878` 存活。
首次视频加载时曾新增两个 GPU worker，后续切换数量稳定，检查以首轮后数量判断持续增长。

设置页面六次实际滑动：101.73 FPS，中位帧间隔 8.297ms、P95 16.594ms、最大 24.887ms。
数据包含输入命令间隙，说明活跃高刷新率仍可工作，配置仍是 120Hz。
v47 两次前台 QQ 采样被宿主应用切换打断，未作为优化后的前台对照。

覆盖安装、桌面启动检查通过；普通 UID `10698`、CapEff `0`、`untrusted_app`。
桌面服务就绪 10.775 秒。源码和运行接口均不使用宿主 Root；本机 Root 只用于安装与观察。
APK 的 v2 签名、1060 个 native 文件、2209 个数据文件、114 个系统 APK、13 个 JNI 导出核验通过。
构建与 Lint 通过，Lint 0 errors / 3 warnings。

- 下载：`/storage/emulated/0/Download/A10VM-0.2.38-display-power.apk`
- 留存：`artifacts/apk/a10vm-0.2.38-display-power-debug.apk`
- 大小：696786136 字节。
- SHA-256：`b5ad5ae23b5fc7c84cfaf25a5fe954c13e8a1123a6cb205a9ee3e44599868e71`

`tools/measure-vm-power.py` 记录 CPU ticks、宿主 Surface 提交、电池温度与 system_server 存活状态。
短窗口证明工作量变化；电池温度有滞后，编译与应用负载会改变热状态，六秒采样不代表稳定降温幅度。

## 实现原则与后续

KISS/YAGNI：通过已有显示状态和客体电源服务完成当前需求，使用现有 metrics/JNI 通道。
SRP：电源调用独立在 `GuestDisplayPower` / `GuestDisplayState`，图形提交判断留在 HWC。
DRY：两个 client composition 分支复用 `presentClientTarget`，CPU 测量复用已有工具。

后续按同一设备亮度、相同场景、相同充电条件做持续使用温度对照；继续按实际热点推进视频解码开销。
