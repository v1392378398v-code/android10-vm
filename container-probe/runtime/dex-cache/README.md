# Android 10 应用 DEX 缓存

大应用冷启动的采样显示，重复 ZIP 解压和 DEX 结构校验占据主要 CPU 时间。
本模块在原有 `ArtDexFileLoader` 的 ZIP 加载边界复用已经完整验证的普通 DEX。
原始 APK、DEX location、ZIP CRC、ClassLoader 和签名验证流程保持原语义。

`DexArchiveCache` 只负责缓存身份、内容校验和原子发布；`cache.patch` 只负责把它
接入加载器。上游源码保存在构建目录，补丁应用到派生副本。

- 首次加载沿用完整解压、结构验证和 checksum 验证，成功且只读后才发布。
- 缓存身份来自实际 ZIP fd 的 dev/inode/size/mtime/ctime、DEX entry、CRC 和长度，
  不以诊断用的 location 代替真实输入。
- 命中后核对格式、长度、身份和 SHA-256，再以私有文件映射复用相同字节。
- 损坏、截断、更新和 I/O 失败均走原加载路径；临时文件通过 rename 原子发布。
- `AppLaunch` 从 `--app-data-dir` 传入应用自己的 `code_cache/a10vm-dex-v1`。
  Android 10 请求缺省该参数时，`AppDexCache` 按 UID 查询包管理器取得实际数据目录；
  支持副进程和共享 UID，不按进程名拼出应用路径。MIUI 构建同时刷新缓存库。
  发布前创建缺失的 `code_cache`，兼容已有的旧应用数据目录。
  清数据和卸载同时移除缓存，APK 更新产生新身份。应用内动态 ZIP DEX 同样受益。

缓存增加一份已解压 DEX 的磁盘占用；首次生成有写入成本。冷启动对照需要单独记录
首次生成和已有缓存的样本，热启动复用存活进程不代表冷启动性能。

构建固定使用 LineageOS `android_art` 的 Android 10 源码提交
`2311566b9f24023b84501b8429c40c69f6f6be23`。替换库保留现有 ART 公开接口，使用
现有 Android 10 Bionic、libc++、libartbase 和 BoringSSL 依赖。

```sh
sh guest-runtime/build-dex-cache.sh
python3 guest-runtime/test-dex-cache.py --stock
python3 guest-runtime/test-dex-cache.py
```

`--stock` 对原库产生预期失败：已验证 DEX 没有发布缓存。新库的 14 项真实加载回归
覆盖 miss/hit、多 DEX、fd/location 差异、损坏、截断、APK 更新、未完整校验、非法
DEX、未压缩 ZIP 和缓存目录不可用，均在普通 UID 下执行。

生产打包必须同步输入清单，按以下顺序执行：

```sh
sh guest-runtime/build-checks.sh
python3 guest-runtime/prepare-desktop.py
python3 guest-runtime/stage.py
sh tools/stage-native-display.sh
sh tools/build-termux.sh :app:assembleDebug :app:lintDebug
python3 tools/verify-native-display-apk.py
```

验收使用 `tools/measure-app-startup.py --label LABEL --case qq --case wechat --case douyin
--runs 3`，记录 Android Activity 时间、绘制等待和新进程 PID；应用数据保留。
`guest-runtime/measure-jit-startup.py` 是 JIT 参数对照，生产参数只接受实际应用证据。

KISS/YAGNI：仅处理已采样的 ZIP DEX 加载开销。SRP/SOLID：缓存、原加载器、应用
启动环境、打包和测量各自独立。DRY：复用现有构建缓存、`MemMap` 和普通 UID 运行夹具。
