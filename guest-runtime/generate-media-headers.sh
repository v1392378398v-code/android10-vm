#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/artifacts/container/media"
GEN="$DEST/generated/include"
HW="$DEST/upstream/hardware/interfaces"
HIDL="$DEST/upstream/system/libhidl/transport"
mkdir -p "$GEN"
for package in android.hidl.base@1.0 android.hidl.manager@1.0 android.hidl.manager@1.1 \
    android.hidl.manager@1.2 android.hidl.memory@1.0 android.hidl.memory.token@1.0 \
    android.hidl.memory.block@1.0 android.hidl.allocator@1.0 android.hidl.token@1.0 \
    android.hidl.safe_union@1.0 android.hardware.graphics.common@1.0 \
    android.hardware.graphics.common@1.1 android.hardware.graphics.common@1.2 \
    android.hardware.graphics.bufferqueue@1.0 android.hardware.graphics.bufferqueue@2.0 \
    android.hardware.graphics.mapper@2.0 android.hardware.graphics.mapper@2.1 \
    android.hardware.graphics.mapper@3.0 android.hardware.media@1.0 \
    android.hardware.media.omx@1.0 android.hardware.media.c2@1.0 \
    android.hardware.media.bufferpool@1.0 android.hardware.media.bufferpool@2.0 \
    android.hardware.cas@1.0 android.hardware.cas.native@1.0 \
    android.hardware.drm@1.0 android.hardware.drm@1.1 android.hardware.drm@1.2; do
    "$DEST/tools/hidl-gen" -Lc++-headers -o "$GEN" \
        -randroid.hardware:"$HW" -randroid.hidl:"$HIDL" "$package"
done
for header in $(rg -l 'template<> constexpr std::array' "$GEN"); do
    sed -i 's/template<> constexpr std::array/template<> inline constexpr std::array/g' "$header"
done
AV="$DEST/upstream/frameworks/av"
NATIVE="$DEST/upstream/frameworks/native"
"$DEST/tools/aidl" --lang=cpp -I"$AV/camera/aidl" -I"$NATIVE/aidl/gui" \
    -o "$DEST/generated/aidl" -h "$GEN" \
    "$AV/camera/aidl/android/hardware/ICameraService.aidl" \
    "$AV/camera/aidl/android/hardware/ICameraServiceListener.aidl" \
    "$AV/camera/aidl/android/hardware/ICameraServiceProxy.aidl" \
    "$AV/camera/aidl/android/hardware/camera2/ICameraDeviceCallbacks.aidl" \
    "$AV/camera/aidl/android/hardware/camera2/ICameraDeviceUser.aidl"
"$DEST/tools/aidl" --lang=cpp -I"$AV/media/libaudioclient/aidl" \
    -o "$DEST/generated/aidl" -h "$GEN" \
    "$AV/media/libaudioclient/aidl/android/media/IAudioRecord.aidl" \
    "$AV/media/libaudioclient/aidl/android/media/IPlayer.aidl"
"$DEST/tools/aidl" --lang=cpp -I"$AV/media/libmedia/aidl" \
    -o "$DEST/generated/aidl" -h "$GEN" \
    "$AV/media/libmedia/aidl/android/IGraphicBufferSource.aidl" \
    "$AV/media/libmedia/aidl/android/IOMXBufferSource.aidl"
cp "$AV/media/libmedia/aidl/android/IOMXNode.h" "$GEN/android/IOMXNode.h"
printf 'Generated Android 10 media HIDL headers: %s\n' "$GEN"
