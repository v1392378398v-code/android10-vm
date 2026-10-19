#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
DEST="$ROOT/artifacts/container/framework"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$ROOT/container-probe/binder/compile.sh"
mkdir -p "$DEST/lib" "$DEST/obj"
platform_compile "$ROOT/guest-runtime/native/GuestDevices.cpp" "$DEST/obj/guest-devices.o"
platform_compile "$ROOT/guest-runtime/native/HostLinearMemory.cpp" "$DEST/obj/host-linear-memory.o"
platform_compile "$ROOT/guest-runtime/native/HostDeviceTransport.cpp" "$DEST/obj/host-device-transport.o"
platform_compile "$ROOT/guest-runtime/native/GuestSharedMemory.cpp" "$DEST/obj/guest-shared-memory.o"
ld.lld -shared -soname liba10vm-guest-devices.so -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/guest-devices.o" "$DEST/obj/host-linear-memory.o" \
    "$DEST/obj/host-device-transport.o" "$DEST/obj/guest-shared-memory.o" \
    "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" "$OUT/lib/libc.so" "$OUT/lib/libdl.so" \
    "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$OUT/obj/binder/crtend_so.o" -o "$DEST/lib/liba10vm-guest-devices.so"
