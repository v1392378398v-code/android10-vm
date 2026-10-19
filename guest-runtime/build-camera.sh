#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
MEDIA="$ROOT/artifacts/container/media"
DEST="$ROOT/artifacts/container/camera"
HW="$MEDIA/upstream/hardware/interfaces/camera"
HELPER="$HW/common/1.0/default"
ALLOCATOR="$MEDIA/upstream/system/libhidl/transport/allocator/1.0/default"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$ROOT/container-probe/binder/compile.sh"
mkdir -p "$DEST/bin" "$DEST/lib" "$DEST/obj" "$DEST/generated"
python3 "$ROOT/guest-runtime/prepare-camera.py"
for package in android.hardware.camera.common@1.0 android.hardware.camera.device@1.0 \
    android.hardware.camera.device@3.2 android.hardware.camera.device@3.3 android.hardware.camera.device@3.4 \
    android.hardware.camera.device@3.5 android.hardware.camera.provider@2.4 android.hardware.camera.provider@2.5 \
    android.hardware.camera.metadata@3.2 android.hardware.camera.metadata@3.3 android.hardware.camera.metadata@3.4; do
    "$MEDIA/tools/hidl-gen" -Lc++-headers -o "$DEST/generated" \
        -randroid.hardware:"$MEDIA/upstream/hardware/interfaces" \
        -randroid.hidl:"$MEDIA/upstream/system/libhidl/transport" "$package"
done
"$MEDIA/tools/aidl" --lang=cpp -I"$MEDIA/upstream/frameworks/native/libs/sensorprivacy/aidl" \
    -o "$DEST/generated/aidl" -h "$DEST/generated" \
    "$MEDIA/upstream/frameworks/native/libs/sensorprivacy/aidl/android/hardware/ISensorPrivacyListener.aidl"
for header in $(rg -l 'template<> constexpr std::array' "$DEST/generated"); do
    sed -i 's/template<> constexpr std::array/template<> inline constexpr std::array/g' "$header"
done
camera_compile() {
    compile "$@" -std=gnu++17 -fno-exceptions -fno-rtti -fno-sized-deallocation \
        -DA10VM_PRIVATE_RUNTIME -D_FILE_OFFSET_BITS=64 -DLOG_NDEBUG=1 \
        -DLIBLOG_LOG_TAG=1006 -DSNET_EVENT_LOG_TAG=1397638484 -Wno-deprecated-declarations \
        -I"$UP/system/core/base/include" -I"$UP/system/core/liblog/include" \
        -I"$UP/system/core/libcutils/include" -I"$UP/system/core/libutils/include" \
        -I"$UP/system/core/libsystem/include" -I"$UP/system/core/include" \
        -I"$UP/frameworks/native/libs/binder/include" -I"$UP/system/libhwbinder/include" \
        -I"$UP/frameworks/native/libs/binderthreadstate/include" \
        -I"$DEST/generated" -I"$MEDIA/generated/include" -I"$HELPER/include" \
        -I"$ROOT/artifacts/container/graphics/upstream/hardware/include" \
        -I"$ROOT/artifacts/container/graphics/upstream/opengl/include" \
        -I"$MEDIA/upstream/system/libhidl/base/include" -I"$MEDIA/upstream/system/libhidl/transport/include" \
        -I"$MEDIA/upstream/system/libhidl/libhidlmemory/include" \
        -I"$MEDIA/upstream/system/libhidl/transport/token/1.0/utils/include" \
        -I"$MEDIA/upstream/system/libhidl/transport/memory/1.0/default" \
        -I"$MEDIA/upstream/system/libfmq/include" \
        -I"$MEDIA/upstream/system/media/camera/include" \
        -I"$MEDIA/upstream/system/media/private/camera/include" \
        -I"$MEDIA/upstream/frameworks/native/headers/media_plugin" \
        -I"$MEDIA/upstream/frameworks/native/include/media/openmax" \
        -I"$MEDIA/upstream/frameworks/native/libs/nativebase/include" \
        -I"$MEDIA/upstream/frameworks/native/libs/gui/include" \
        -I"$MEDIA/upstream/frameworks/native/libs/ui/include" \
        -I"$MEDIA/upstream/frameworks/native/libs/nativewindow/include" \
        -I"$MEDIA/upstream/frameworks/native/libs/arect/include" \
        -I"$MEDIA/upstream/frameworks/native/libs/math/include" \
        -I"$MEDIA/upstream/frameworks/native/libs/sensorprivacy/include" \
        -I"$MEDIA/upstream/frameworks/av/camera/include" \
        -I"$MEDIA/upstream/frameworks/av/camera/include/camera" \
        -I"$MEDIA/upstream/frameworks/av/media/libmedia/include" \
        -I"$MEDIA/upstream/frameworks/av/services/camera/libcameraservice" \
        -I"$HW/device/1.0/default" -I"$ALLOCATOR"
}
objects=
for name in HostCameraHal HostCameraFrames HostDeviceTransport; do
    object="$DEST/obj/$name.o"
    camera_compile "$ROOT/guest-runtime/native/$name.cpp" "$object"
    objects="$objects $object"
done
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
ld.lld -shared -soname camera.a10vm.so -z now -z relro -z max-page-size=4096 --no-undefined --as-needed \
    "$OUT/obj/binder/crtbegin_so.o" $objects "$MEDIA/lib/libhardware.so" \
    "$OUT/lib/libc++.so" "$OUT/lib/libc.so" "$builtins" "$OUT/obj/binder/crtend_so.o" \
    -o "$DEST/lib/camera.a10vm.so"
camera_compile "$ROOT/container-probe/graphics/desktop/GuestHardware.cpp" "$DEST/obj/GuestHardware.o"
ld.lld -shared -soname liba10vm-hal-modules.so -z now -z relro -z max-page-size=4096 --no-undefined \
    "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/GuestHardware.o" "$OUT/lib/libdl.so" "$OUT/lib/libc.so" \
    "$OUT/obj/binder/crtend_so.o" -o "$DEST/lib/liba10vm-hal-modules.so"
objects=
for source in "$ROOT/guest-runtime/native/HostCameraProvider.cpp" "$HW/device/1.0/default/CameraDevice.cpp" \
    "$HELPER/CameraModule.cpp" "$HELPER/CameraMetadata.cpp" "$HELPER/HandleImporter.cpp" \
    "$ALLOCATOR/AshmemAllocator.cpp"; do
    object="$DEST/obj/$(basename "$source" .cpp).o"
    camera_compile "$source" "$object"
    objects="$objects $object"
done
libraries=
for path in "$MEDIA/lib/"*.so "$DEST/lib/"*.so; do libraries="$libraries $path"; done
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined --as-needed "$OUT/obj/binder-probe/crtbegin.o" $objects $libraries \
    "$OUT/bin/source-linker64" "$builtins" "$OUT/obj/binder-probe/crtend.o" -o "$DEST/bin/camera-provider"
camera_compile "$MEDIA/upstream/frameworks/av/camera/cameraserver/main_cameraserver.cpp" "$DEST/obj/cameraserver.o"
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined --as-needed "$OUT/obj/binder-probe/crtbegin.o" "$DEST/obj/cameraserver.o" $libraries \
    "$OUT/bin/source-linker64" "$builtins" "$OUT/obj/binder-probe/crtend.o" -o "$DEST/bin/cameraserver"
printf 'Built ARM64 host camera HAL and provider\n'
