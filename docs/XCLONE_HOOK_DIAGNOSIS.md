# 小X分身 hook 兼容性修复

客体包名：`com.bly.dkplat`。交付版本：`0.2.43-mt-startup`，versionCode 53。
应用和客体以普通应用 UID 运行；开发采集和安装工具使用本机 `su`。

## 修复的阻塞

### ART 库路径识别

`0.2.39-linker-terminal` 的主进程、`:hs` 和 `:p0` 输出：

```text
LSPlantHooker: libart base not found in maps
LSPlantHooker: LSPlant nInit=false
LSPlantHooker: LSPlant init failed; skip module hooks
```

原 `libloader.so` 的 `_ZL13locate_libartv` 要求 maps 行包含 `/libart.so`，
且文件偏移为零。实际文件名为安装目录下的 `liba10vm-guest-libart.so`。
同一份未修改的定位函数在补丁前返回 0，补丁后返回 1。

`GuestProcMaps` 在动态 libc 的 openat 边界生成客体 maps 快照，用
`dl_iterate_phdr` 的逻辑库名与设备号、inode 对应真实映射；地址、权限、
偏移和描述符的只读/CLOEXEC 标志继续来自实际映射。普通打开、libc syscall、
dirfd 相对打开和 thread-self 路径均覆盖。

宿主 `GuestMappingPaths` 将客体别名解析回打包文件后再做映射核验。
未知可执行库及必需库缺失仍有拒绝用例。

### 仅执行 ART 代码段

库定位成功后，Dobby 在 `GenRelocateCodeAndBranch+148` 执行
`ldr w22,[x20]` 时崩溃：目标 ART 段为 `--xp`，hook 引擎需要读取指令。
linker 的 ELF 映射将可执行段同时设为可读，不增加写权限。

普通 UID 的最小复现使用原库验证了初始化、实际返回值改变、原方法备份调用、
unhook 恢复；五个信号全部通过。

### APK 的直接系统调用

实机 `strace` 捕获到同一 APK 的两种打开：

```text
openat(..., ROOTFS/data/app/INSTALL/base.apk, O_RDONLY|O_CLOEXEC) = 29
openat(..., /data/app/INSTALL/base.apk, O_RDONLY|O_NOFOLLOW|O_CLOEXEC) = -1 ENOENT
```

第二种来自 `libsmallx_license.so` 的 `RawFile`，直接执行 AArch64
`svc #0`，没有经过 libc 的客体路径映射。文件本身可读，失败发生在地址空间
外的路径解释。

`ApplicationCodePaths` 在客体应用入口委托 `IPackageManager` 的包信息查询，
对返回的 `ApplicationInfo` 和 `PackageInfo.applicationInfo` 复制后转换代码路径。
仅将 `/data/app` 和 `/mnt/expand` 的基础包及 split 包代码路径转换为
`A10VM_ROOTFS` 下的实际路径。应用身份、数据目录和原对象由回归核验。
使用运行环境提供的 rootfs，未加入设备安装目录或小X包名特例。

系统 APK 的代码路径继续使用客体坐标。实机观察证明，将系统 WebView 的路径
也转成物理坐标会导致 linker namespace 与库路径不匹配；独立回归包含这一约束。

### MT 的 APK 库搜索路径回归

`0.2.41` 的 MT 启动日志出现物理 `base.apk` 路径解析失败，随后原生类初始化
报 `UnsatisfiedLinkError`。与小X同时验收，避免只证明基础包可读。

最小 namespace 复现使用真实的页对齐 APK 内 ELF，给 namespace 传入 rootfs 下的
物理 APK 搜索路径。linker 的静态 realpath 逐级检查宿主前缀时，混入客体路径
映射，抛出 ENOENT 并丢弃搜索路径；其权限列表与 fd 返回的客体库路径也不一致。

linker 的 `resolve_paths` 在路径解析入口将 rootfs 下的物理路径转为客体坐标。
基础包元数据保留实际可读路径供直接系统调用使用，namespace 用客体路径与
fd 导出的路径比较。转换复用 `guestPhysicalPath`，仍按原来的 namespace 权限判断。

namespace 修复后，`0.2.42` 的 MT 仍报原生 `<clinit>` 没有实现。
同机仅撤去 `ApplicationInfo.CREATOR` 的全局转换，MT 即完成主界面绘制。
该转换也改写了 `ActivityThread.bindApplication` 的启动元数据，影响应用的
原生初始化。`0.2.43` 将转换收窄到 PackageManager 查询；启动 parcel、原始
CREATOR 和 Binder 对象保持原语义，查询者仍取得直接系统调用可读的 APK 路径。
独立回归覆盖这三个边界，以及基础包、split、嵌套包信息、空值与系统 WebView 路径。

安装只在 `GuestApplication.main` 的 `android.app.ActivityThread` 应用入口执行。
共享运行时初始化、system_server 冷启动、WebView relro 与子 zygote 使用原入口。
最终 `0.2.43` 的 MT 主界面与 10 秒启动观察通过，详细证据见
[MT 修复记录](MT_STARTUP_FIX.md)。

## 验证与证据

可重复命令：

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD sh guest-runtime/test-proc-maps.sh artifacts/xclone-hook/libloader.so --initialize
env -u LD_LIBRARY_PATH -u LD_PRELOAD sh guest-runtime/test-runtime-identity.sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD sh guest-runtime/test-code-paths.sh
```

本轮新增的直接 SVC 复现，补丁前 `raw_apk_open_errno=2`，补丁后
`raw_apk_contents=1`、`code_paths_complete=1`；UID 10373，rootRequired=false。
覆盖基础包、split、PackageInfo 嵌套、重复转换、空值、宿主路径与系统 namespace。
新增 `code_paths_bind_parcel=1` 与 `code_paths_binder_identity=1` 检查启动元数据
及原 Binder 对象；应用包查询取得物理路径，原对象和启动 parcel 继续保持客体路径。
同一测试同时检查 APK 内原生库在隔离 namespace 中的实际加载和符号调用。

开发替换后的实机进程日志：

```text
native capture prepared=true
LSPlant nInit=true
WebViewFactory: Loading com.android.webview version 139.0.7258.143
```

主进程注册 28 个 hook，`:hs` 注册 2 个。对应采集内
`APK_OPEN_REJECTED` 与 WebView namespace 崩溃均未再出现，主进程 UID/EUID
10698、CapEff=0，SELinux 为 untrusted_app。

上述 APK 读取通过记录来自先前全局转换版本。`0.2.43` 的查询委托版本实机
再次启动小X时，`native capture prepared=true`、`LSPlant nInit=true` 与 WebView
加载仍出现，原生直接读取 APK 的 `APK_OPEN_REJECTED` 再次出现。应用上下文
返回的安装包路径尚未覆盖；此项保留为小X后续兼容问题，MT 启动修复已单独验收。

私有工件保存在 `artifacts/xclone-hook/`，不纳入 Git：

- `proc-maps-before.json`、`proc-maps-report.json`：同一定位函数的前后结果。
- `hook-crash-debug.log`、`hook-init-report.json`：指令读取故障和真实 hook 行为。
- `code-paths-before-report.json`、`code-paths-report.json`：直接 SVC 的前后结果。
- `code-paths-namespace-before.log`：新增 APK namespace 用例的失败证据。
- `device/compat/apk-openat.trace`：实际失败路径和 errno。
- `device/compat/application-926-57.log`、`application-926-58.log`：开发替换后的主进程和服务进程。
- `apk-verification.json`、`device/apk-desktop-report.json`：上一轮 0.2.40 的打包、签名与免 root 启动证据。

测试用原库 SHA-256：

```text
libloader.so          721731e812ec7a9e6eccbff640fcd0d2c5d1009299d9c52a49a360f8223724ac
libsmallx_license.so  97be4364aed73d386fa8df410fac3bcffcde6487ddcec273e1f1ade68902b003
```

这些验证证明 hook 引擎和 APK 读取兼容链路；小X各个配置功能仍需按具体功能验收。
修改未覆盖所有原生库的直接系统调用。

## 实现边界与后续

KISS/YAGNI：只处理已复现的 maps 名称、代码段读取和安装包路径问题。
DRY：libc syscall openat 复用常规 openat；基础包和 split 使用同一转换。
SRP：maps 快照、宿主映射核验和应用代码路径分别放在独立模块。

后续按小X的具体配置功能检查目标进程内的 hook 效果，并在其他宿主安卓版本
复核 ELF 权限和路径别名；当前实机证据来自这一台设备。
