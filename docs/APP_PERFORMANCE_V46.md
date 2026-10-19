# v46 大应用启动与应用内性能

本轮目标是减少虚拟 Android 内 QQ、微信、抖音的重复 DEX 加载开销，并让应用
连续退出、重开时显示服务继续工作。交付版本为 `0.2.36-app-dex-cache`，
`versionCode=46`。保留现有应用数据和原生 ARM64/GPU/Surface/触摸路线。

## 实现

- 在 Android 10 `ArtDexFileLoader` 的 ZIP 加载入口接入持久缓存。首次完整验证
  成功后发布；再次启动或加载同一动态插件时，核对真实 ZIP fd 身份、entry、CRC、
  长度和缓存 SHA-256，再映射已经验证的 DEX。异常缓存沿用原加载流程。
- 缓存放在各应用的 `code_cache/a10vm-dex-v1`。发布时创建缺失的父目录，兼容
  旧应用数据；清数据和卸载随应用目录删除缓存，APK 更新采用新的文件身份。
- 修复 GPU socket reset 早于 pidfd 退出通知的竞态：连接级 `ECONNRESET`、
  `EPIPE`、`ENOTCONN` 结束当前 worker；其余协议和后端错误保留原错误处理。
- 保留抖音进程族的 JIT 内联兼容参数。提前 JIT 编译的对照波动较大，生产通用
  JIT、堆大小和核心分配沿用当前设置。

## 最终 APK 启动结果

每个应用连续强停后启动三次，每次确认新进程 PID 和前台窗口完成绘制；随后检查
热启动。总计 18 个启动样本均通过，system_server 始终为同一存活进程。

| 应用 | v45 冷启动 Activity WaitTime | v46 三次冷启动 Activity WaitTime | 中位数变化 |
| --- | --- | --- | --- |
| QQ | 9084 / 9681 ms | 1892 / 1794 / 1716 ms | 9382.5 → 1794 ms，约减少 81% |
| 抖音 | 6525 / 6396 ms | 1598 / 1327 / 1403 ms | 6460.5 → 1403 ms，约减少 78% |

微信 Activity 计时会先于实际窗口绘制结束。本次从执行启动命令到绘制检查完成的
墙钟时间为 2690 / 2264 / 2158 ms，中位数约 2.26 秒，包含命令和检查开销。
旧微信样本口径不完整，因此这里仅报告最终实际绘制结果。

QQ、微信、抖音的新进程分别出现 85 / 19 / 57 处 `.adex` 映射；这是映射数。
QQ 基线报告在后续微信样本处失败，表中只采用其中已完成绘制的两个 QQ 样本。
本次最终报告全部通过。

首次生成缓存仍有解压、验证和写入成本。之前的抖音首次生成样本为 7313 ms；
最终表格采用已经存在缓存的冷进程启动。当前缓存占用约 QQ 809 MiB、微信
173 MiB、抖音 439 MiB，包含本机已产生的文件身份。APK 更新产生的新旧身份
可能共存，直到应用 code_cache 被清理。

证据：

- `artifacts/performance/v45-big-apps-before/report.json`
- `artifacts/performance/v45-douyin-before/report.json`
- `artifacts/performance/v46-app-start-final/report.json`
- `artifacts/performance/v46-big-apps-cache-final/report.json`（首次生成与旧显示错误）

## 应用内操作

三个应用分别完成八次交替滑动，宿主 Surface 提交结果如下：

| 场景 | Surface 提交 FPS | P95 间隔 | 最大间隔 |
| --- | ---: | ---: | ---: |
| QQ 已登录消息列表 | 108.50 | 16.593 ms | 157.642 ms |
| 微信登录首页 | 118.76 | 8.299 ms | 16.596 ms |
| 抖音推荐视频页 | 105.65 | 16.596 ms | 33.191 ms |

该数据包含输入命令间隔，衡量 Surface 提交节奏；内容动画帧率、触摸到显示延迟
和所有业务操作的提速比例还需要各自测量。微信当前停留在登录首页，本轮未测量
已登录聊天场景。截图确认 QQ 消息列表和抖音推荐视频页已正常呈现。

证据为 `artifacts/performance/v46-{qq,wechat,douyin}-in-app.json` 和同名 PNG。
全部操作完成后 system_server 仍存活，保持普通应用 UID、`CapEff=0`。

DEX 缓存也覆盖应用内动态 ZIP 插件加载；这一收益由真实加载器回归验证。
应用内长帧仍有优化空间，后续优先对消息列表、页面切换和视频流的长帧采样。

## 验证与交付

- 新库 14 项真实 DEX 加载回归通过，库存库对缓存发布断言产生预期失败。
  覆盖多 DEX、真实 fd/location 差异、损坏、截断、APK 更新、未完整验证、
  非法 DEX、未压缩 ZIP 和不可用缓存目录；普通 Termux UID 下执行。
- 保持进程存活并关闭含未读回复的 GPU 连接，确定性重现 reset：修复前
  `live_peer_reset_does_not_poison_gpu_server=0`，修复后为 `1`，后续连接处理命令
  `commands_work_after_peer_reset=1`。原有资源回收和重连检查同时通过。
- 补丁对固定上游源码正向应用检查、对已编译派生源码反向检查均通过。
- `assembleDebug`、`lintDebug`、包内输入哈希、1060 个 native 文件、2209 个 runtime
  assets、114 个 APK、13 个 JNI 导出及 v2 签名验证通过；Lint 为 0 Error/Fatal、
  3 Warning。
- 覆盖安装成功。实机桌面启动约 8.38 秒；客体 UID 为普通应用 UID，`CapEff=0`、
  `untrusted_app`。Root 仅用于本机安装和自动化检查，客体运行免 Root。

APK：`/storage/emulated/0/Download/A10VM-0.2.36-app-dex-cache.apk`

SHA-256：`985519e7625e1d0dd386af5d43164673b3c7a0123c1136d8424150bbafdfcf2b`

验证证据还包括 `artifacts/device-desktop/boot-v46-final/apk-desktop-report.json`、
`artifacts/container/graphics/native-display-apk-report.json`、
`artifacts/container/dex-cache/test-report.json` 和
`artifacts/container/graphics/desktop/live-reset-{before,after}.log`。

## 设计原则与下一步

KISS/YAGNI：只处理已观测的重复加载与连接退出问题。SOLID/SRP：缓存模块、
原加载器接入、启动环境、构建和测量分别承担独立职责。DRY：复用 `MemMap`、
原加载流程、普通 UID 运行夹具和现有构建缓存；应用启动意图供两种测量工具共用。

本轮的两个实施问题分别是旧数据缺少 `code_cache` 和 socket/pidfd 退出顺序不同，
已经通过父目录创建和连接级异常处理解决。下一步按应用内实际长帧推进，保留本版
作为大应用启动和连续重开可试用基线。

工具调用：使用本地 Shell、`apply_patch` 和现有构建/设备脚本；本轮没有调用 MCP 服务。
