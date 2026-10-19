# MT 终端私有 linker 配置修复

版本：`0.2.39-linker-terminal`，versionCode `49`。

## 触发与原因

当前设备上，客体 MT 管理器执行
`/data/user/0/bin.mt.plus/files/term/bin/bash` 时，原版本输出：

```text
A10VM private linker configuration was rejected
libc: A10VM private linker configuration was rejected
```

把客体 `/system/bin/sh` 复制到客体数据目录后执行，也会触发同一错误。
文件系统适配层把 `/proc/self/fd` 的链接结果转换成客体路径，而 linker
配置的 `dir.guest` 使用宿主私有目录。两者直接比较时匹配失败，尚未进入
动态依赖加载就终止了进程。

## 修改

- 配置解析复用 `GuestPaths` 将程序路径映射到实际文件路径，仅用于选择配置节。
- 遇到可执行但不可读的安装目录或路径别名时，通过目录设备号与 inode
  核对归属，不依赖厂商路径或安卓版本。
- 报错包含配置文件、程序路径和解析原因。

配置仍使用原有私有库搜索路径与 namespace 隔离规则。
KISS / DRY：复用已有路径映射。SRP：配置匹配留在 linker 配置解析器内。
YAGNI：本次只修复已复现的路径匹配问题。

## 验证入口

以下检查由普通 Termux UID 执行：

```sh
python3 container-probe/runtime/dynamic/test-linker-config.py
python3 container-probe/runtime/dynamic/test-native.py
python3 container-probe/runtime/filesystem/test-native.py
```

覆盖客体数据目录程序、客体逻辑路径、目录别名、可执行但不可读目录、registry
配置，以及缺失配置节、空配置和不匹配配置。原有动态加载与文件系统检查一并通过。

打包时核对生成清单：运行组件仅 `liba10vm-source-linker.so` 的哈希发生变化，
所有客体数据资产与其他原生组件保持原哈希。

当前 Android 16 设备覆盖安装后，桌面启动检查耗时 10.382 秒；客体服务的
实际 UID/EUID 为 10698，有效 capabilities 为 0，运行域为 `untrusted_app`。
同一条复制 shell 的命令和 MT 自带 `bash --noprofile --norc` 均退出 0，
Bash 版本为 `5.2.37(1)-release`。MT 终端界面交互尚未单独验收。
设备验收结果记录在 `artifacts/linker-terminal/`。
