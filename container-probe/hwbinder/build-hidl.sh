#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
HWSRC="$ROOT/container-probe/hwbinder"
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$SRC/fetch-sources.sh" "${1:-}" "$HWSRC/archives.txt" "$HWSRC/hidl-sources.sha256"
mkdir -p "$OUT/obj/hidl" "$OUT/hwbinder"
. "$SRC/compile.sh"
compile "$B/arch-common/bionic/crtbegin_so.c" "$OUT/obj/hidl/crtbegin_so.o"
compile "$B/arch-common/bionic/crtend_so.S" "$OUT/obj/hidl/crtend_so.o"
objects=
for name in HidlInternal HidlSupport Status TaskRunner; do
    object="$OUT/obj/hidl/$name.o"
    platform_compile "$UP/system/libhidl/base/$name.cpp" "$object" \
        -I"$UP/system/libhidl/base/include"
    objects="$objects $object"
done
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
ld.lld -shared -soname libhidlbase.so -z max-page-size=4096 -z now -z relro \
    --hash-style=gnu --eh-frame-hdr --build-id=sha1 --no-undefined --exclude-libs ALL \
    "$OUT/obj/hidl/crtbegin_so.o" $objects \
    "$OUT/lib/libutils.so" "$OUT/lib/libcutils.so" "$OUT/lib/libbase.so" "$OUT/lib/liblog.so" \
    "$OUT/lib/libc++.so" "$OUT/lib/libm.so" "$OUT/lib/libunwind.so" \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$builtins" \
    "$OUT/obj/hidl/crtend_so.o" -o "$OUT/lib/libhidlbase.so"
llvm-readelf -hlWd "$OUT/lib/libhidlbase.so" > "$OUT/hwbinder/libhidlbase.so-elf.txt"
python3 "$HWSRC/prepare-hidl-values.py"
platform_compile "$OUT/hwbinder/hidl-values/HidlValues.cpp" "$OUT/obj/hidl/HidlValues.o" \
    -I"$UP/system/libhidl/base/include" -I"$OUT/hwbinder/hidl-values/include"
ld.lld -shared -soname liba10hidl-values.so -z max-page-size=4096 -z now -z relro \
    --hash-style=gnu --eh-frame-hdr --build-id=sha1 --no-undefined --exclude-libs ALL \
    "$OUT/obj/hidl/crtbegin_so.o" "$OUT/obj/hidl/HidlValues.o" \
    "$OUT/lib/libhwbinder.so" "$OUT/lib/libhidlbase.so" "$OUT/lib/libutils.so" \
    "$OUT/lib/liblog.so" "$OUT/lib/libc++.so" "$OUT/lib/libm.so" "$OUT/lib/libunwind.so" \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$builtins" \
    "$OUT/obj/hidl/crtend_so.o" -o "$OUT/lib/liba10hidl-values.so"
llvm-readelf -hlWd "$OUT/lib/liba10hidl-values.so" > "$OUT/hwbinder/liba10hidl-values.so-elf.txt"
if [ "${1:-}" = --record ]; then
    python3 "$ROOT/container-probe/runtime/record-sources.py" "$UP" "$HWSRC/hidl-sources.sha256" \
        $objects "$OUT/obj/hidl/HidlValues.o" "$OUT/obj/hidl/crtbegin_so.o" "$OUT/obj/hidl/crtend_so.o"
    (cd "$UP" && sha256sum system/libhidl/base/Android.bp \
        system/libhidl/transport/HidlBinderSupport.cpp system/libhidl/transport/include/hidl/HidlBinderSupport.h) \
        >> "$HWSRC/hidl-sources.sha256"
fi
