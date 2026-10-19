#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
DEST="$ROOT/artifacts/container/audio"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$ROOT/container-probe/binder/compile.sh"
mkdir -p "$DEST/lib" "$DEST/obj"
sh "$ROOT/guest-runtime/fetch-audio-headers.sh"
platform_compile "$ROOT/guest-runtime/native/HostAudioHal.cpp" "$DEST/obj/host-audio.o" \
    -I"$ROOT/artifacts/container/graphics/upstream/hardware/include" \
    -I"$ROOT/artifacts/container/graphics/upstream/nativebase/include" -I"$DEST/include"
platform_compile "$ROOT/guest-runtime/native/HostAudioPcm.cpp" "$DEST/obj/host-audio-pcm.o" \
    -I"$ROOT/artifacts/container/runtime/upstream/system/core/libsystem/include" -I"$DEST/include"
ld.lld -shared -soname audio.primary.a10vm.so -z now -z relro -z max-page-size=4096 --no-undefined \
    "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/host-audio.o" "$DEST/obj/host-audio-pcm.o" \
    "$OUT/lib/libc.so" "$OUT/lib/libc++.so" "$OUT/lib/libdl.so" \
    "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$OUT/obj/binder/crtend_so.o" -o "$DEST/lib/audio.primary.a10vm.so"
