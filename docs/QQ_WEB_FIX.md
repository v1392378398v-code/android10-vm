# QQ 内置网页的文件属性兼容修复

日期：2026-10-18。所有者查询修复始于 v0.2.77，完整网页验收版本为
`0.2.80-miui12-paired-graphics-hal`（versionCode 90）。

## 原因与证据

在 v0.2.75 的实际 QQ X5 渲染进程中，GDB 捕获到 `SIGSYS`：

```text
thread: CrRendererMain
syscall: 10 / fgetxattr
attribute: user.a10vm.owner
target: app_tbs_64/core_share/libmttwebview.so
call chain: X5 +0x679394c -> fstat -> guestApplyOwnership -> fgetxattr
NoNewPrivs: 1
Seccomp_filters: 2
```

实机 libc 和 linker 的 SHA-256 与 v0.2.75 构建产物一致。
问题发生在库已经加载、X5 已安装过滤器之后的首次应用侧 `fstat`。
原有加载器元数据修复和已缓存文件检查没有覆盖这条路径。

v0.2.76 在安装过滤器前预热已加载库和打开文件，原有库首次 `fstat`
回归通过，真实 QQ 网页仍然崩溃。后续 GDB 捕获到另一条完整调用链：

```text
thread: Profile Saver
syscall: 8 / getxattr
attribute: user.a10vm.owner
target: app_tbs_64/core_share/oat/renderer_dex.jar.cur.prof
call chain: libart -> libprofile -> libartbase -> stat -> guestApplyOwnership
NoNewPrivs: 1
Seccomp_filters: 2
```

X5 通过 `SECCOMP_FILTER_FLAG_TSYNC` 将过滤器同步到既有 ART 线程。
profile 文件在启用过滤器后才首次检查；仅扩大预热清单仍会遗漏延迟访问，
而缓存按 ctime 失效后也会再次进入同一条属性查询。

## 改动

`GuestOwnership.cpp` 的内部查询改用隐藏的汇编入口，入口固定属性名
`user.a10vm.owner`。`GuestSandbox.cpp` 在客体安装过滤器时，复制原指令并在
前面添加仅匹配该入口的规则，同时校验 ARM64 架构、系统调用号、完整指令地址、
属性名地址与 16 字节长度。其余调用进入原指令，累加器恢复为初始值。

同时接入 `syscall(seccomp)`、`syscall(prctl)` 和公开 `prctl` 三条入口，
保留 flags 和 TSYNC 行为；删除 v0.2.76 的文件枚举预热。
原程序为空、缺少指令或接近 BPF 指令上限时，交由内核按原参数处理。
非客体进程和其他 prctl/seccomp 操作也保持原参数。

文件所有者缓存、内部查询入口和过滤器适配各自保留独立职责。缓存继续按设备号、
inode、ctime 校验，既有虚拟 UID/GID 和 `fchown` 失效处理保持有效。
此兼容处理依赖客体 libc 的安装入口；不适用于应用内联 `svc` 安装的过滤器。

## 验证

- 新增 `owner-sandbox` 用例：加载带虚拟 UID/GID 的库，在安装过滤器后才首次
  打开并执行 `fstat`，读取 UID 10234、GID 10235。
- 新增独立 `OwnershipSandboxCheck.cpp`，模拟冷访问 profile、修改库 ctime 后的
  `fstat`、既有 ART 线程访问另一个冷文件。v0.2.76 首次 profile stat 退出
  SIGSYS（-31）；v0.2.77 在 seccomp TSYNC 和公开 prctl 两种模式均通过。
- 验证虚拟 UID/GID、errno 保留、TSYNC 对既有线程的效果，原过滤器的 EPERM
  返回与应用直接 `fgetxattr` 的 SIGSYS 继续生效。
- 原有文件系统 87 项、进程身份和四项判定负例通过。
- 动态运行库四种属性配置、四种装载失败、分配器、TLS 和卸载检查通过。
- QQ 网页脚本限定当前 system_server 的应用日志，避免历史 PID 重用造成歧义；
  默认两轮各观察 30 秒，保留客体截图。
- v0.2.79 完整包保留上述修复。本机首轮 QQ X5 渲染进程在安装两层 seccomp 后
  存活 30 秒，未见原有 xattr/SIGSYS 崩溃标记；后续客体截图命令超时，第二轮未执行，
  该轮完整网页用例未通过，当时宿主 Surface 处于后台。
- v0.2.80 在本机 PJZ110 完成完整 APK 覆盖安装、冷启动和 30 秒桌面稳定观察。
  随后两次分别停止并重新打开 QQ 的真实 X5 腾讯视频网页，每轮观察 30 秒。
  两个 renderer（13384 / 18782）均存活，未出现崩溃标记，客体截图均成功；首轮截图
  已确认中文、导航、图片及正文正常显示。完整脚本结果 `passed=true`，原始证据为
  `artifacts/qq-web/v080-local/`。该结果覆盖此次两轮网页复现，不代表全部网页或长期日用。

原始 GDB、系统调用和测试输出保存在私有 `artifacts/container/camera/`。
最新安装器 55600 与现有客体应用数据属于本轮保留项。
