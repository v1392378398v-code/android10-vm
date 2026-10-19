#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
SRC="$ROOT/container-probe/runtime/companion"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
for tool in clang clang++ ld.lld llvm-ar llvm-readelf llvm-nm jq python3; do command -v "$tool" >/dev/null; done
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$SRC/fetch-sources.sh" "${1:-}"
sh "$SRC/prepare-sources.sh"
test -f "$OUT/lib/libc.so"
test -f "$OUT/lib/libdl.so"
mkdir -p "$OUT/obj/companion" "$OUT/companion" "$OUT/generated"
. "$SRC/compile.sh"
python3 "$SRC/select-sources.py" "$UP" > "$OUT/companion/recipes.json"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
test -f "$builtins"
clang --version > "$OUT/companion/compiler.txt"
sha256sum "$builtins" > "$OUT/companion/builtins.sha256"
compile "$B/arch-common/bionic/crtbegin_so.c" "$OUT/obj/companion/crtbegin_so.o"
compile "$B/arch-common/bionic/crtend_so.S" "$OUT/obj/companion/crtend_so.o"
all_objects=
for recipe in math optimized unwind abi cxx; do
    objects=
    flags=$(jq -r --arg name "$recipe" '.[$name].cflags[]' "$OUT/companion/recipes.json")
    cppflags=$(jq -r --arg name "$recipe" '.[$name].cppflags[]' "$OUT/companion/recipes.json")
    includes=$(jq -r --arg name "$recipe" '.[$name].includes[]' "$OUT/companion/recipes.json")
    case "$recipe" in
        math) flags="$flags -D_LIBC=1 -I$UP/bionic/libm -I$B/upstream-freebsd/android/include -Wno-macro-redefined -Wno-deprecated-non-prototype -Wno-implicit-const-int-float-conversion" ;;
        optimized) flags="$flags -I$UP/external/arm-optimized-routines/math/include" ;;
        abi) cppflags="$cppflags -D_LIBCXXABI_BUILDING_LIBRARY" ;;
        unwind) cppflags="$cppflags -D_LIBUNWIND_IS_NATIVE_ONLY -fno-rtti" ;;
    esac
    for directory in $includes; do flags="$flags -I$UP/$directory"; done
    jq -r --arg name "$recipe" '.[$name].sources[]' "$OUT/companion/recipes.json" \
        > "$OUT/companion/$recipe-sources.txt"
    while read -r path; do
        object="$OUT/obj/companion/$(printf '%s' "$path" | tr / _).o"
        case "$path" in
            bionic/libm/*.S) compile "$UP/$path" "$object" -D_LIBC=1 -Werror ;;
            */s_sincosl.c) compile "$OUT/derived/$path" "$object" $flags -Wno-unused-but-set-variable ;;
            *.cpp|*.cc) compile "$UP/$path" "$object" $flags $cppflags ;;
            *) compile "$UP/$path" "$object" $flags ;;
        esac
        objects="$objects $object"
    done < "$OUT/companion/$recipe-sources.txt"
    all_objects="$all_objects $objects"
    rm -f "$OUT/lib/liba10vm-$recipe.a"
    llvm-ar rcD "$OUT/lib/liba10vm-$recipe.a" $objects
done
python3 "$UP/bionic/tools/generate-version-script.py" arm64 "$UP/bionic/libm/libm.map.txt" \
    "$OUT/generated/libm.map"
link_shared() {
    soname=$1
    shift
    ld.lld -shared -soname "$soname" -z max-page-size=4096 -z now -z relro \
        --hash-style=gnu --eh-frame-hdr --build-id=sha1 --no-undefined \
        --exclude-libs "$(basename "$builtins")" \
        "$OUT/obj/companion/crtbegin_so.o" "$@" "$builtins" \
        "$OUT/obj/companion/crtend_so.o" -o "$OUT/lib/$soname"
    llvm-readelf -hlWd "$OUT/lib/$soname" > "$OUT/companion/$soname-elf.txt"
    llvm-nm -u "$OUT/lib/$soname" > "$OUT/companion/$soname-undefined.txt"
}
link_shared libm.so --version-script "$OUT/generated/libm.map" -Bsymbolic-functions \
    --whole-archive "$OUT/lib/liba10vm-math.a" "$OUT/lib/liba10vm-optimized.a" \
    --no-whole-archive "$OUT/lib/libc.so"
link_shared libunwind.so --whole-archive "$OUT/lib/liba10vm-unwind.a" --no-whole-archive \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so"
link_shared libc++.so --whole-archive "$OUT/lib/liba10vm-cxx.a" "$OUT/lib/liba10vm-abi.a" \
    --no-whole-archive "$OUT/lib/libunwind.so" "$OUT/lib/libm.so" "$OUT/lib/libc.so" "$OUT/lib/libdl.so"
sha256sum "$OUT/lib/libm.so" "$OUT/lib/libunwind.so" "$OUT/lib/libc++.so" \
    > "$OUT/companion/libraries.sha256"
if [ "${1:-}" = --record ]; then
    python3 "$ROOT/container-probe/runtime/record-sources.py" "$UP" "$SRC/sources.sha256" $all_objects \
        "$OUT/obj/companion/crtbegin_so.o" "$OUT/obj/companion/crtend_so.o"
    (cd "$UP" && sha256sum bionic/libm/Android.bp bionic/libm/libm.map.txt \
        external/arm-optimized-routines/Android.bp external/libcxx/Android.bp \
        external/libcxxabi/Android.bp external/libunwind_llvm/Android.bp \
        bionic/tools/generate-version-script.py) >> "$SRC/sources.sha256"
fi
