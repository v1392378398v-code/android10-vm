#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
HWSRC="$ROOT/container-probe/hwbinder"
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
LIBC="$UP/bionic/libc"
B="$LIBC"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
for tool in clang clang++ ld.lld llvm-readelf llvm-nm jq python3; do command -v "$tool" >/dev/null; done
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$SRC/fetch-sources.sh" "" "$HWSRC/archives.txt" "$HWSRC/sources.sha256"
sh "$SRC/prepare-sources.sh"
sh "$HWSRC/prepare-sources.sh"
mkdir -p "$OUT/obj/hwbinder" "$OUT/hwbinder"
. "$SRC/compile.sh"
python3 "$HWSRC/select-sources.py" "$UP" > "$OUT/hwbinder/recipes.json"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
compile "$LIBC/arch-common/bionic/crtbegin_so.c" "$OUT/obj/hwbinder/crtbegin_so.o"
compile "$LIBC/arch-common/bionic/crtend_so.S" "$OUT/obj/hwbinder/crtend_so.o"
clang --version > "$OUT/hwbinder/compiler.txt"
sha256sum "$builtins" > "$OUT/hwbinder/builtins.sha256"
objects=
for path in $(jq -r '.sources[]' "$OUT/hwbinder/recipes.json"); do
    object="$OUT/obj/hwbinder/$(printf '%s' "$path" | tr / _).o"
    flags="-I$(dirname "$UP/$path")"
    if [ -f "$OUT/derived/$path" ]; then input="$OUT/derived/$path"; else input="$UP/$path"; fi
    platform_compile "$input" "$object" $flags
    objects="$objects $object"
done
ld.lld -shared -soname libhwbinder.so -z max-page-size=4096 -z now -z relro \
    --hash-style=gnu --eh-frame-hdr --build-id=sha1 --no-undefined --exclude-libs ALL \
    "$OUT/obj/hwbinder/crtbegin_so.o" $objects \
    "$OUT/lib/liba10binder.so" "$OUT/lib/libbinderthreadstate.so" \
    "$OUT/lib/libutils.so" "$OUT/lib/libcutils.so" "$OUT/lib/libbase.so" "$OUT/lib/liblog.so" \
    "$OUT/lib/libc++.so" "$OUT/lib/libm.so" "$OUT/lib/libunwind.so" \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$builtins" \
    "$OUT/obj/hwbinder/crtend_so.o" -o "$OUT/lib/libhwbinder.so"
llvm-readelf -hlWd "$OUT/lib/libhwbinder.so" > "$OUT/hwbinder/libhwbinder.so-elf.txt"
llvm-nm -u "$OUT/lib/libhwbinder.so" > "$OUT/hwbinder/libhwbinder.so-undefined.txt"
sha256sum "$OUT/lib/libhwbinder.so" > "$OUT/hwbinder/libraries.sha256"
