#!/bin/sh
set -eu
unset LD_LIBRARY_PATH LD_PRELOAD
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
TRIAL=${1:-artifacts/experiments/miui12-20.12.9}
sh guest-runtime/build-checks.sh
SDK=${ANDROID_HOME:-"$HOME/Android/Sdk"}
mkdir -p "$TRIAL/apk-bootstrap/classes" "$TRIAL/apk-bootstrap/dex"
javac --release 8 -cp "$SDK/platforms/android-35/android.jar:artifacts/container/framework/classes" \
    -d "$TRIAL/apk-bootstrap/classes" tools/fixtures/rom/RomBootstrap.java \
    tools/fixtures/rom/RomDesktopCheck.java tools/fixtures/rom/RomHardwareCheck.java
bash "$SDK/build-tools/35.0.0/d8" --min-api 29 --lib "$SDK/platforms/android-35/android.jar" \
    --output "$TRIAL/apk-bootstrap/dex" "$TRIAL/apk-bootstrap/classes/io/a10vm/guest/"*.class
sh guest-runtime/build-network.sh
sh guest-runtime/build-dex-cache.sh
sh guest-runtime/build-host-devices.sh
sh container-probe/runtime/dynamic/build-linker.sh
sh container-probe/runtime/dynamic/build-libc.sh
sh container-probe/binder/build-libraries.sh
sh container-probe/binder/build-probes.sh
sh container-probe/graphics/build-native.sh
sh container-probe/graphics/build-desktop.sh
python3 tools/patch-rom-media.py "$TRIAL/extracted/system/lib64/libmediaplayerservice.so" \
    "$TRIAL/media-reset/libmediaplayerservice.so" > "$TRIAL/media-reset-patch.json"
mkdir -p "$TRIAL/account-capability"
python3 tools/patch-rom-account.py "$TRIAL/extracted/system/app/XiaomiAccount/XiaomiAccount.apk" \
    "$TRIAL/account-capability/XiaomiAccount.apk" > "$TRIAL/account-capability/account-patch.json"
python3 tools/patch-rom-account.py "$TRIAL/extracted/system/priv-app/FindDevice/FindDevice.apk" \
    "$TRIAL/account-capability/FindDevice.apk" --kind finddevice > "$TRIAL/account-capability/finddevice-patch.json"
python3 tools/stage-rom-apk.py "$TRIAL/prepared-v2" "$TRIAL/apk-bootstrap/dex/classes.dex" \
    --boot-jni qti_performance --rom-binder "$TRIAL/extracted/system/lib64/libbinder.so" \
    --host-netd artifacts/container/network/lib/libnetd_client.so \
    --framework-dex artifacts/container/framework/dex/classes.dex \
    --system-apk-override system/app/XiaomiAccount/XiaomiAccount.apk="$TRIAL/account-capability/XiaomiAccount.apk" \
    --system-apk-override system/priv-app/FindDevice/FindDevice.apk="$TRIAL/account-capability/FindDevice.apk" \
    --webview-apk guest-runtime/build/prepared/assets/guest-runtime/rootfs/system/product/app/webview/webview.apk \
    --webview-package com.android.webview \
    --hardware-application com.qti.slaservice=vendor.qti.sla.service@1.0::ISlaService/default \
    --hardware-application vendor.qti.hardware.cacert.server=vendor.qti.hardware.cacert@1.0::IService/default \
    --native-override liba10binder.so=artifacts/container/runtime/lib/liba10binder.so \
    --native-override ld-android.so=artifacts/container/runtime/bin/source-linker64 \
    --native-override libc.so=artifacts/container/runtime/lib/libc.so \
    --native-override libdl.so=artifacts/container/runtime/lib/libdl.so \
    --native-override libdexfile.so=artifacts/container/dex-cache/lib/libdexfile.so \
    --native-override binder-broker=artifacts/container/runtime/bin/binder-broker \
    --native-override host-devices=artifacts/container/host-devices/bin/host-devices \
    --native-override libOpenglSystemCommon.so=artifacts/container/graphics/desktop/lib/libOpenglSystemCommon.so \
    --native-override libEGL_emulation.so=artifacts/container/graphics/desktop/lib/libEGL_emulation.so \
    --native-override libGLESv1_CM_emulation.so=artifacts/container/graphics/desktop/lib/libGLESv1_CM_emulation.so \
    --native-override libGLESv2_emulation.so=artifacts/container/graphics/desktop/lib/libGLESv2_emulation.so \
    --native-override gralloc.ranchu.so=artifacts/container/graphics/desktop/lib/gralloc.ranchu.so \
    --native-override hwcomposer.ranchu.so=artifacts/container/graphics/desktop/lib/hwcomposer.ranchu.so \
    --native-override liba10vm-hal-modules.so=artifacts/container/graphics/desktop/lib/liba10vm-hal-modules.so \
    --native-override libmediaplayerservice.so="$TRIAL/media-reset/libmediaplayerservice.so"
sh tools/stage-native-display.sh
# The complete ROM APK exceeds 2 GiB; start packaging from a fresh ZIP.
mkdir -p artifacts/apk
BACKUP=$(mktemp -d "$ROOT/artifacts/apk/miui-rebuild.XXXXXX")
if [ -f app/build/outputs/apk/debug/app-debug.apk ]; then
    mv app/build/outputs/apk/debug/app-debug.apk "$BACKUP/"
fi
if [ -d app/build/intermediates/incremental/packageDebug ]; then
    mv app/build/intermediates/incremental/packageDebug "$BACKUP/"
fi
exec sh tools/build-termux.sh -PguestRuntimePrepared=guest-runtime/build/rom-prepared/miui12 \
    -PguestRuntimeProfile=miui12 '-Dorg.gradle.jvmargs=-Xmx4096m -Dfile.encoding=UTF-8' \
    --max-workers=1 :app:assembleDebug :app:lintDebug
