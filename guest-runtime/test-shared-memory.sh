#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
DEST="$ROOT/artifacts/device-compat/shared-memory"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$ROOT/container-probe/binder/compile.sh"
mkdir -p "$DEST"
for name in GuestSharedMemory HostDeviceTransport; do
    platform_compile "$ROOT/guest-runtime/native/$name.cpp" "$DEST/$name.o"
done
platform_compile "$ROOT/guest-runtime/test/SharedMemoryCheck.cpp" "$DEST/check.o"
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 --wrap=fcntl \
    -z now -z relro -z max-page-size=4096 --no-undefined \
    "$OUT/obj/binder-probe/crtbegin.o" "$DEST/check.o" \
    "$DEST/GuestSharedMemory.o" "$DEST/HostDeviceTransport.o" \
    "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" "$OUT/lib/libc.so" "$OUT/lib/libdl.so" \
    "$OUT/bin/source-linker64" "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$OUT/obj/binder-probe/crtend.o" -o "$DEST/check"
printf 'dir.probe = %s\n[probe]\nnamespace.default.isolated = true\nnamespace.default.search.paths = %s/lib\nnamespace.default.permitted.paths = %s:%s\n' \
    "$DEST" "$OUT" "$OUT" "$DEST" > "$DEST/ld.config.txt"
A10VM_LD_CONFIG="$DEST/ld.config.txt" "$OUT/bin/source-linker64" "$DEST/check"
A10VM_LD_CONFIG="$DEST/ld.config.txt" "$OUT/bin/source-linker64" "$DEST/check" legacy
A10VM_LD_CONFIG="$DEST/ld.config.txt" "$OUT/bin/source-linker64" "$DEST/check" fragmented
