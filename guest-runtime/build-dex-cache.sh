#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/runtime/dex-cache"
OUT="$ROOT/artifacts/container/dex-cache"
ART="$OUT/upstream/art"
COMMIT=2311566b9f24023b84501b8429c40c69f6f6be23
if [ ! -d "$ART/.git" ]; then
    git clone --depth 1 --single-branch --branch lineage-17.1 \
        https://github.com/LineageOS/android_art.git "$ART"
fi
test "$(git -C "$ART" rev-parse HEAD)" = "$COMMIT"
UP="$ROOT/artifacts/container/runtime/upstream"
B="$ROOT/artifacts/container/runtime/companion/derived/bionic/libc"
if [ ! -d "$B/include" ]; then B="$UP/bionic/libc"; fi
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
LIB="$ROOT/artifacts/container/art/lib"
NDK=${ANDROID_NDK_HOME:-"$HOME/Android/Sdk/ndk/29.0.13113456"}
mkdir -p "$OUT/derived" "$OUT/obj" "$OUT/lib" "$OUT/bin" "$OUT/generated"
cp -R "$ART/libdexfile" "$ART/libartbase" "$ART/libartpalette" "$OUT/derived/"
if [ -f "$SRC/cache.patch" ]; then
    git apply --recount --unsafe-paths --directory="$OUT/derived" "$SRC/cache.patch"
fi
. "$ROOT/container-probe/runtime/companion/compile.sh"
compile "$B/arch-common/bionic/crtbegin.c" "$OUT/obj/crtbegin.o"
compile "$B/arch-common/bionic/crtend.S" "$OUT/obj/crtend.o"
dex_compile() {
    compile "$@" -std=gnu++17 -O3 -fno-exceptions -fno-rtti -DNDEBUG -DART_TARGET -DART_TARGET_ANDROID \
        -DART_BASE_ADDRESS=0x70000000 -DBUILDING_LIBART=1 -fvisibility=protected \
        -DART_STACK_OVERFLOW_GAP_arm=8192 -DART_STACK_OVERFLOW_GAP_arm64=8192 \
        -DART_STACK_OVERFLOW_GAP_mips=16384 -DART_STACK_OVERFLOW_GAP_mips64=16384 \
        -DART_STACK_OVERFLOW_GAP_x86=16384 -DART_STACK_OVERFLOW_GAP_x86_64=20480 \
        -I"$OUT/derived/libdexfile" -I"$OUT/derived/libartbase" -I"$OUT/derived/libartpalette" \
        -I"$OUT/derived/libartpalette/include" -I"$UP/system/core/base/include" \
        -I"$UP/system/core/liblog/include" -I"$UP/system/core/libziparchive/include" \
        -I"$UP/external/zlib" -I"$SRC" \
        -idirafter "$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include"
}
python3 "$ART/tools/generate_operator_out.py" "$OUT/derived/libdexfile" \
    "$OUT/derived/libdexfile/dex/dex_file.h" "$OUT/derived/libdexfile/dex/dex_file_layout.h" \
    "$OUT/derived/libdexfile/dex/dex_instruction.h" "$OUT/derived/libdexfile/dex/dex_instruction_utils.h" \
    "$OUT/derived/libdexfile/dex/invoke_type.h" "$OUT/derived/libdexfile/dex/method_reference.h" \
    > "$OUT/generated/operators.cc"
objects=
for name in art_dex_file_loader compact_dex_file compact_offset_table descriptors_names \
    dex_file dex_file_exception_helpers dex_file_layout dex_file_loader dex_file_tracking_registrar \
    dex_file_verifier dex_instruction modifiers primitive signature standard_dex_file type_lookup_table utf; do
    source="$OUT/derived/libdexfile/dex/$name.cc"
    object="$OUT/obj/$name.o"
    dex_compile "$source" "$object"
    objects="$objects $object"
done
dex_compile "$OUT/generated/operators.cc" "$OUT/obj/operators.o"
objects="$objects $OUT/obj/operators.o"
if [ -f "$SRC/DexArchiveCache.cpp" ]; then
    dex_compile "$SRC/DexArchiveCache.cpp" "$OUT/obj/cache.o"
    objects="$objects $OUT/obj/cache.o"
fi
dex_compile "$SRC/DexClassIndex.cpp" "$OUT/obj/class-index.o"
objects="$objects $OUT/obj/class-index.o"
ld.lld -shared -soname libdexfile.so -z now -z relro -z max-page-size=4096 --no-undefined \
    "$ROOT/artifacts/container/runtime/obj/binder/crtbegin_so.o" $objects \
    "$LIB/libartbase.so" "$LIB/libartpalette.so" "$LIB/libbase.so" "$LIB/liblog.so" \
    "$LIB/libc++.so" "$LIB/libc.so" "$LIB/libm.so" "$LIB/libdl.so" \
    "$ROOT/artifacts/container/framework/lib/libcrypto.so" \
    "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
    "$ROOT/artifacts/container/runtime/obj/binder/crtend_so.o" -o "$OUT/lib/libdexfile.so"
sha256sum "$OUT/lib/libdexfile.so" > "$OUT/library.sha256"
for check in DexLoaderCheck DexClassLookupCheck; do
    case "$check" in
        DexLoaderCheck) binary=dex-cache-check ;;
        DexClassLookupCheck) binary=dex-class-lookup-check ;;
    esac
    dex_compile "$SRC/test/$check.cpp" "$OUT/obj/$check.o"
    ld.lld -pie -z now -z relro -z max-page-size=4096 --no-undefined \
        -dynamic-linker /system/bin/linker64 \
        "$OUT/obj/crtbegin.o" "$OUT/obj/$check.o" \
        "$OUT/lib/libdexfile.so" "$LIB/libartbase.so" "$LIB/libbase.so" \
        "$LIB/libc++.so" "$LIB/libc.so" "$LIB/libm.so" "$LIB/libdl.so" \
        "$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)" \
        "$OUT/obj/crtend.o" -o "$OUT/bin/$binary"
done
