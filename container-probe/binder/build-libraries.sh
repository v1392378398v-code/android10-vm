#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
for tool in clang clang++ ld.lld llvm-ar llvm-readelf llvm-nm jq python3; do command -v "$tool" >/dev/null; done
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$SRC/fetch-sources.sh" "${1:-}"
sh "$SRC/prepare-sources.sh"
for library in libc.so libdl.so libm.so libc++.so libunwind.so; do test -f "$OUT/lib/$library"; done
mkdir -p "$OUT/obj/binder" "$OUT/binder" "$OUT/generated"
. "$SRC/compile.sh"
python3 "$SRC/select-sources.py" "$UP" > "$OUT/binder/recipes.json"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
test -f "$builtins"
compile "$B/arch-common/bionic/crtbegin_so.c" "$OUT/obj/binder/crtbegin_so.o"
compile "$B/arch-common/bionic/crtend_so.S" "$OUT/obj/binder/crtend_so.o"
clang --version > "$OUT/binder/compiler.txt"
sha256sum "$builtins" > "$OUT/binder/builtins.sha256"
all_objects=
for recipe in log base cutils utils binderthreadstate a10binder binder; do
    objects=
    if [ "$recipe" = a10binder ]; then
        paths='Wire.cpp TransactionLayout.cpp TransactionWire.cpp Driver.cpp ClientBuffers.cpp'
    else
        paths=$(jq -r --arg name "$recipe" '.[$name].sources[]' "$OUT/binder/recipes.json")
    fi
    for path in $paths; do
        object="$OUT/obj/binder/$(printf '%s' "$path" | tr / _).o"
        flags="-I$(dirname "$UP/$path")"
        if [ "$recipe" = a10binder ]; then input="$SRC/native/$path";
        elif [ -f "$OUT/derived/$path" ]; then input="$OUT/derived/$path";
        else input="$UP/$path"; fi
        case "$path" in
            */Threads.cpp) flags="$flags -Dset_sched_policy=a10vm_set_sched_policy" ;;
        esac
        platform_compile "$input" "$object" $flags
        objects="$objects $object"
    done
    if [ "$recipe" = cutils ]; then
        for path in Ashmem.cpp Scheduling.cpp; do
            object="$OUT/obj/binder/$path.o"
            platform_compile "$SRC/native/$path" "$object"
            objects="$objects $object"
        done
    fi
    all_objects="$all_objects $objects"
    soname="lib$recipe.so"
    dependencies=
    case "$recipe" in
        base) dependencies="$OUT/lib/liblog.so" ;;
        cutils) dependencies="$OUT/lib/liblog.so $OUT/lib/libbase.so" ;;
        utils) dependencies="$OUT/lib/libcutils.so $OUT/lib/liblog.so" ;;
        binderthreadstate) dependencies="$OUT/lib/liblog.so" ;;
        binder) dependencies="$OUT/lib/liba10binder.so $OUT/lib/libutils.so $OUT/lib/libcutils.so $OUT/lib/libbase.so $OUT/lib/liblog.so $OUT/lib/libbinderthreadstate.so" ;;
    esac
    ld.lld -shared -soname "$soname" -z max-page-size=4096 -z now -z relro \
        --hash-style=gnu --eh-frame-hdr --build-id=sha1 --no-undefined --exclude-libs ALL \
        "$OUT/obj/binder/crtbegin_so.o" $objects $dependencies \
        "$OUT/lib/libc++.so" "$OUT/lib/libm.so" "$OUT/lib/libunwind.so" \
        "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$builtins" \
        "$OUT/obj/binder/crtend_so.o" -o "$OUT/lib/$soname"
    llvm-readelf -hlWd "$OUT/lib/$soname" > "$OUT/binder/$soname-elf.txt"
    llvm-nm -u "$OUT/lib/$soname" > "$OUT/binder/$soname-undefined.txt"
done
sha256sum "$OUT/lib/liblog.so" "$OUT/lib/libbase.so" "$OUT/lib/libcutils.so" \
    "$OUT/lib/libutils.so" "$OUT/lib/libbinderthreadstate.so" "$OUT/lib/liba10binder.so" \
    "$OUT/lib/libbinder.so" > "$OUT/binder/libraries.sha256"
if [ "${1:-}" = --record ]; then
    python3 "$ROOT/container-probe/runtime/record-sources.py" "$UP" "$SRC/sources.sha256" $all_objects \
        "$OUT/obj/binder/crtbegin_so.o" "$OUT/obj/binder/crtend_so.o"
    (cd "$UP" && sha256sum system/core/liblog/Android.bp system/core/base/Android.bp \
        system/core/libcutils/Android.bp system/core/libutils/Android.bp \
        frameworks/native/libs/binder/Android.bp frameworks/native/libs/binderthreadstate/Android.bp) \
        >> "$SRC/sources.sha256"
fi
