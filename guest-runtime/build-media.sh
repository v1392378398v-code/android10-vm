#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
MEDIA="$ROOT/artifacts/container/media"
AV="$MEDIA/upstream/frameworks/av"
NATIVE="$MEDIA/upstream/frameworks/native"
HEADERS="$MEDIA/upstream/system/media"
HIDL="$MEDIA/upstream/system/libhidl"
G="$ROOT/artifacts/container/graphics/upstream"
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$ROOT/guest-runtime/fetch-media-sources.sh"
if [ ! -x "$MEDIA/tools/hidl-gen" ] || [ ! -x "$MEDIA/tools/aidl" ]; then
    sh "$ROOT/guest-runtime/build-media-tools.sh"
fi
sh "$ROOT/guest-runtime/generate-media-headers.sh"
python3 "$ROOT/guest-runtime/prepare-media.py"
mkdir -p "$MEDIA/bin" "$MEDIA/obj"
. "$ROOT/container-probe/binder/compile.sh"
media_compile() {
    compile "$@" -std=gnu++17 -fno-exceptions -fno-rtti -fno-sized-deallocation \
        -DA10VM_PRIVATE_RUNTIME -D_FILE_OFFSET_BITS=64 -DLOG_NDEBUG=1 \
        -DLIBLOG_LOG_TAG=1006 -DSNET_EVENT_LOG_TAG=1397638484 -Wno-deprecated-declarations \
        -I"$UP/system/core/base/include" -I"$UP/system/core/liblog/include" \
        -I"$UP/system/core/libcutils/include" -I"$UP/system/core/libutils/include" \
        -I"$UP/system/core/libsystem/include" -I"$UP/system/core/libprocessgroup/include" \
        -I"$UP/system/core/libbacktrace/include" -I"$UP/system/core/include" \
        -I"$UP/frameworks/native/libs/binderthreadstate/include" -I"$UP/system/libhwbinder/include" \
        -D__ANDROID_APEX__ -Wno-multichar \
        -I"$MEDIA/generated/include" -I"$AV/include" -I"$NATIVE/include" \
        -I"$NATIVE/include/media/openmax" -I"$NATIVE/libs/gui/include" \
        -I"$NATIVE/headers/media_plugin" \
        -I"$NATIVE/libs/ui/include" -I"$NATIVE/libs/nativewindow/include" \
        -I"$NATIVE/libs/nativebase/include" -I"$NATIVE/libs/arect/include" \
        -I"$NATIVE/libs/binder/include" -I"$NATIVE/libs/math/include" \
        -I"$G/hardware/include" -I"$G/libsync/include" -I"$G/opengl/include" \
        -I"$UP/system/core/libsync/include" \
        -I"$HEADERS/audio/include" -I"$HEADERS/audio_utils/include" \
        -I"$HEADERS/camera/include" -I"$HEADERS/private/camera/include" \
        -I"$HIDL/base/include" -I"$HIDL/transport/include" \
        -I"$HIDL/transport/token/1.0/utils/include" -I"$HIDL/libhidlmemory/include" \
        -I"$MEDIA/upstream/system/libfmq/include" -I"$MEDIA/upstream/system/netd/include" \
        -I"$MEDIA/upstream/external/boringssl/src/include" \
        -I"$MEDIA/upstream/external/selinux/libselinux/include" \
        -I"$MEDIA/upstream/external/icu/libandroidicu/include" \
        -I"$MEDIA/upstream/system/core/libmemunreachable/include" \
        -I"$AV/media/libaudiofoundation/include" -I"$AV/media/libaudioclient/include" \
        -I"$AV/media/libmedia/include" -I"$AV/media/libmedia/aidl" \
        -I"$AV/media/libmediaextractor/include" -I"$AV/media/libmediandk/include" \
        -I"$AV/media/ndk/include" \
        -I"$AV/media/libmediametrics/include" -I"$AV/media/libmediautils/include" \
        -I"$AV/media/utils/include" \
        -I"$AV/media/libmediaplayerservice/include" -I"$AV/media/libmediaplayerservice" \
        -I"$AV/media/libmediaplayerservice/nuplayer" -I"$AV/media/libmediadrm/include" \
        -I"$AV/media/libstagefright/include" -I"$AV/media/libstagefright/foundation/include" \
        -I"$AV/media/libstagefright/xmlparser/include" -I"$AV/media/libstagefright/omx/include" \
        -I"$AV/media/libstagefright" -I"$AV/media/libstagefright/httplive" \
        -I"$AV/media/libstagefright/mpeg2ts" -I"$AV/media/libstagefright/rtsp" \
        -I"$AV/media/libstagefright/timedtext" -I"$AV/media/libstagefright/webm" \
        -I"$AV/media/codec2/core/include" -I"$AV/media/codec2/vndk/include" \
        -I"$AV/media/codec2/hidl/client/include" \
        -I"$AV/media/bufferpool/2.0/include" \
        -I"$AV/media/codec2/hidl/1.0/utils/include" \
        -I"$AV/camera/include" -I"$AV/camera/include/camera" \
        -I"$AV/drm/common/include" -I"$AV/drm/drmserver" \
        -I"$AV/drm/libdrmframework/plugins/common/include" \
        -I"$AV/services/mediaresourcemanager" -I"$AV/services/minijail"
}
build() {
    name=$1
    kind=$2
    shift 2
    objects=
    for source in "$@"; do
        object="$MEDIA/obj/$(printf '%s' "${source#"$AV"/}" | tr / _).o"
        media_compile "$source" "$object"
        objects="$objects $object"
    done
    libraries=
    for path in "$MEDIA/lib/"*.so; do
        if [ "$(basename "$path")" != "$name" ]; then libraries="$libraries $path"; fi
    done
    if [ "$kind" = library ]; then
        flags="-shared -soname $name"
        begin="$OUT/obj/binder/crtbegin_so.o"
        end="$OUT/obj/binder/crtend_so.o"
        target="$MEDIA/lib/$name"
    else
        flags='-pie -e _start -dynamic-linker /system/bin/linker64'
        begin="$OUT/obj/binder-probe/crtbegin.o"
        end="$OUT/obj/binder-probe/crtend.o"
        target="$MEDIA/bin/$name"
    fi
    ld.lld $flags -z now -z relro -z max-page-size=4096 --no-undefined --as-needed \
        "$begin" $objects $libraries "$OUT/bin/source-linker64" \
        "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" "$end" -o "$target"
    printf 'Built ARM64 media component: %s\n' "$name"
}
build libresourcemanagerservice.so library "$AV/services/mediaresourcemanager/ResourceManagerService.cpp" \
    "$AV/services/mediaresourcemanager/ServiceLog.cpp"
build libstagefright_httplive.so library "$AV/media/libstagefright/httplive/"*.cpp \
    "$AV/media/libstagefright/mpeg2ts/"*.cpp "$AV/media/libstagefright/id3/ID3.cpp" \
    "$AV/media/libstagefright/MetaDataUtils.cpp"
rtsp_sources=
for source in AAMRAssembler AAVCAssembler AH263Assembler AMPEG2TSAssembler \
    AMPEG4AudioAssembler AMPEG4ElementaryAssembler APacketSource ARawAudioAssembler \
    ARTPAssembler ARTPConnection ARTPSource ARTPWriter ARTSPConnection ASessionDescription; do
    rtsp_sources="$rtsp_sources $AV/media/libstagefright/rtsp/$source.cpp"
done
build libmediaplayerservice.so library "$AV/media/libmediaplayerservice/"*.cpp \
    "$AV/media/libmediaplayerservice/nuplayer/"*.cpp \
    $rtsp_sources "$AV/media/libstagefright/rtsp/SDPLoader.cpp" \
    "$AV/media/libstagefright/rtsp/NetworkUtils.cpp" \
    "$AV/media/libstagefright/timedtext/TextDescriptions.cpp"
build media program "$AV/media/mediaserver/main_mediaserver.cpp" "$AV/media/mediaserver/register.cpp"
build media-drm program "$AV/services/mediadrm/"*.cpp
build drm program "$AV/drm/drmserver/"*.cpp "$AV/drm/common/"*.cpp
build media-omx program "$AV/services/mediacodec/main_codecservice.cpp"
