#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
HWSRC="$ROOT/container-probe/hwbinder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$OUT/upstream/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$SRC/compile.sh"
mkdir -p "$OUT/obj/hwbinder-probe" "$OUT/bin"
compile "$B/arch-common/bionic/crtbegin.c" "$OUT/obj/hwbinder-probe/crtbegin.o"
compile "$B/arch-common/bionic/crtend.S" "$OUT/obj/hwbinder-probe/crtend.o"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
objects=
for path in test/ProbeMain.cpp test/Registry.cpp test/Service.cpp test/Client.cpp test/Buffers.cpp test/HidlValues.cpp; do
    object="$OUT/obj/hwbinder-probe/$(printf '%s' "$path" | tr / _).o"
    platform_compile "$HWSRC/$path" "$object" -I"$HWSRC/test" \
        -I"$UP/system/libhidl/base/include" -I"$OUT/hwbinder/hidl-values/include"
    objects="$objects $object"
done
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 \
    -z max-page-size=4096 -z now -z relro --hash-style=gnu --eh-frame-hdr --build-id=sha1 \
    --no-undefined --exclude-libs ALL \
    "$OUT/obj/hwbinder-probe/crtbegin.o" $objects \
    "$OUT/lib/libhwbinder.so" "$OUT/lib/libhidlbase.so" "$OUT/lib/liba10hidl-values.so" \
    "$OUT/lib/liba10binder.so" "$OUT/lib/libbinderthreadstate.so" \
    "$OUT/lib/libutils.so" "$OUT/lib/libcutils.so" "$OUT/lib/libbase.so" "$OUT/lib/liblog.so" \
    "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" "$OUT/lib/libm.so" "$OUT/lib/libc.so" \
    "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" "$builtins" \
    "$OUT/obj/hwbinder-probe/crtend.o" -o "$OUT/bin/hwbinder-probe"
llvm-readelf -hlWd "$OUT/bin/hwbinder-probe" > "$OUT/hwbinder/hwbinder-probe-elf.txt"
