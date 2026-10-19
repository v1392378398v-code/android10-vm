# 原生窗口与输入共享模块

主应用和图形探针共用此模块。`NativeWindow` 由服务持有；Surface attachment
只借用窗口，Activity 重建不重启客体。`NativeSurfaceView` 按 360×640 等比显示，
转发完整多指手势与历史 MOVE。`WindowBridge` 适配 JNI，`GuestLibraryFiles`
负责显示库摘要校验；主应用的私有 linker 与 ART 由 `guest-runtime` 管理。

桌面 C++ 源码位于 `container-probe/graphics/desktop/`，输入队列及 JNI 适配复用
`container-probe/graphics/window/`。准备脚本将配套桌面 renderer 放到本模块的生成目录。

```sh
sh tools/prepare-native-display.sh
sh tools/build-termux.sh :app:assembleDebug :app:lintDebug
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-native-display.py --stall-input
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 tools/test-native-display.py --stop-pending
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-desktop-egl.py
env -u LD_LIBRARY_PATH -u LD_PRELOAD python3 guest-runtime/test-system-server.py
```

当前主应用通过配套 EGL/GLES/renderControl、gralloc/HWC 与 SurfaceFlinger 显示真实桌面。
独立触摸通道将事件交给客体 InputManager。桌面、抽屉、设置与 HOME 离屏验收已通过；
APK 实机验收单独记录，见 [版本清单](../docs/evidence/native-system-apps.json)。
