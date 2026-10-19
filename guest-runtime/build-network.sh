#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
DEST="$ROOT/artifacts/container/network"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$ROOT/container-probe/binder/compile.sh"
mkdir -p "$DEST/lib" "$DEST/obj"
platform_compile "$ROOT/guest-runtime/native/HostNetdClient.cpp" "$DEST/obj/host-netd.o"
platform_compile "$ROOT/guest-runtime/native/HostConnect.cpp" "$DEST/obj/host-connect.o" \
    -I"$ROOT/artifacts/container/media/upstream/system/netd/include"
ld.lld -shared -soname libnetd_client.so -z now -z relro -z max-page-size=4096 --no-undefined \
    "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/host-netd.o" "$DEST/obj/host-connect.o" \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$OUT/lib/libc++.so" \
    "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$OUT/obj/binder/crtend_so.o" -o "$DEST/lib/libnetd_client.so"
