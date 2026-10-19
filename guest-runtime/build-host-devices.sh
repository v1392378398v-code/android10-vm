#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
MEDIA="$ROOT/artifacts/container/media"
DEST="$ROOT/artifacts/container/host-devices"
GEN="$DEST/generated"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$ROOT/container-probe/binder/compile.sh"
mkdir -p "$GEN" "$DEST/bin" "$DEST/obj"
python3 "$ROOT/guest-runtime/prepare-host-devices.py"
for package in android.hardware.sensors@1.0 android.hardware.vibrator@1.0 android.hardware.health@1.0 android.hardware.health@2.0; do
    "$MEDIA/tools/hidl-gen" -Lc++-headers -o "$GEN" \
        -randroid.hardware:"$MEDIA/upstream/hardware/interfaces" \
        -randroid.hidl:"$MEDIA/upstream/system/libhidl/transport" "$package"
done
for version in 1.0 1.1; do
    for language in c++-headers c++-sources; do
        "$MEDIA/tools/hidl-gen" -L"$language" -o "$GEN" \
            -rvendor.xiaomi.hardware.mtdservice:"$ROOT/guest-runtime/native/mtdservice" \
            -randroid.hidl:"$MEDIA/upstream/system/libhidl/transport" \
            "vendor.xiaomi.hardware.mtdservice@$version"
    done
done
for header in $(rg -l 'template<> constexpr std::array' "$GEN"); do
    sed -i 's/template<> constexpr std::array/template<> inline constexpr std::array/g' "$header"
done
objects=
mtd_objects=
for name in HostDeviceTransport HostSensorsHal HostVibratorHal HostHealthHal GuestMtdStorage HostDevicesMain; do
    object="$DEST/obj/$name.o"
    platform_compile "$ROOT/guest-runtime/native/$name.cpp" "$object" \
        -I"$GEN" -I"$MEDIA/generated/include" \
        -I"$UP/system/libhidl/base/include" -I"$UP/system/libhidl/transport/include"
    objects="$objects $object"
    if [ "$name" = GuestMtdStorage ]; then mtd_objects="$object"; fi
done
for input in $(rg --files "$GEN/vendor/xiaomi/hardware/mtdservice" -g '*.cpp'); do
    object="$DEST/obj/mtd-$(basename "$(dirname "$input")")-$(basename "$input" .cpp).o"
    platform_compile "$input" "$object" -I"$GEN" -I"$MEDIA/generated/include" \
        -I"$UP/system/libhidl/base/include" -I"$UP/system/libhidl/transport/include"
    objects="$objects $object"
    mtd_objects="$mtd_objects $object"
done
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 \
    -z now -z relro -z max-page-size=4096 --no-undefined --as-needed \
    "$OUT/obj/binder-probe/crtbegin.o" $objects \
    "$DEST/lib/android.hardware.sensors@1.0.so" \
    "$DEST/lib/android.hardware.vibrator@1.0.so" \
    "$DEST/lib/android.hardware.health@1.0.so" \
    "$DEST/lib/android.hardware.health@2.0.so" \
    "$ROOT/artifacts/container/framework/lib/libhidlbase.so" \
    "$ROOT/artifacts/container/framework/lib/libhidltransport.so" \
    "$ROOT/artifacts/container/framework/lib/libhwbinder.so" "$OUT/lib/libutils.so" "$OUT/lib/libc++.so" \
    "$OUT/lib/libbase.so" "$OUT/lib/libcutils.so" "$OUT/lib/liblog.so" \
    "$OUT/lib/libc.so" "$OUT/bin/source-linker64" \
    "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$OUT/obj/binder-probe/crtend.o" -o "$DEST/bin/host-devices"
platform_compile "$ROOT/guest-runtime/test/MtdStorageServer.cpp" "$DEST/obj/mtd-server.o" \
    -I"$GEN" -I"$MEDIA/generated/include" \
    -I"$UP/system/libhidl/base/include" -I"$UP/system/libhidl/transport/include"
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 \
    -z now -z relro -z max-page-size=4096 --no-undefined --as-needed \
    "$OUT/obj/binder-probe/crtbegin.o" "$DEST/obj/mtd-server.o" $mtd_objects \
    "$ROOT/artifacts/container/framework/lib/libhidlbase.so" \
    "$ROOT/artifacts/container/framework/lib/libhwbinder.so" \
    "$OUT/lib/libutils.so" "$OUT/lib/libc++.so" "$OUT/lib/libbase.so" \
    "$OUT/lib/libcutils.so" "$OUT/lib/liblog.so" "$OUT/lib/libc.so" "$OUT/bin/source-linker64" \
    "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$OUT/obj/binder-probe/crtend.o" -o "$DEST/bin/mtd-storage-test"
