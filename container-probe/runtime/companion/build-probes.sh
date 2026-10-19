#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
SRC="$ROOT/container-probe/runtime/companion"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
for tool in clang clang++ ld.lld llvm-readelf; do command -v "$tool" >/dev/null; done
unset LD_LIBRARY_PATH LD_PRELOAD
. "$SRC/compile.sh"
mkdir -p "$OUT/obj/companion-probe" "$OUT/bin"
compile "$B/arch-common/bionic/crtbegin.c" "$OUT/obj/companion-probe/crtbegin.o"
compile "$B/arch-common/bionic/crtend.S" "$OUT/obj/companion-probe/crtend.o"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
for module in ExceptionModule LateModule; do
    object="$OUT/obj/companion-probe/$module.o"
    compile "$SRC/test/$module.cpp" "$object" -DA10VM_DYNAMIC_PROBE -fno-builtin
    case "$module" in
        ExceptionModule) soname=liba10vm-exceptions.so ;;
        LateModule) soname=liba10vm-late-test.so ;;
    esac
    ld.lld -shared -soname "$soname" -z max-page-size=4096 -z now -z relro \
        --hash-style=gnu --eh-frame-hdr --build-id=sha1 --no-undefined --exclude-libs ALL \
        "$OUT/obj/companion/crtbegin_so.o" "$object" \
        "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" "$OUT/lib/libc.so" "$builtins" \
        "$OUT/obj/companion/crtend_so.o" -o "$OUT/lib/$soname"
done
objects=
for path in CompanionProbe.cpp MathProbe.cpp ComplexProbe.c CxxProbe.cpp ExceptionProbe.cpp \
    LoadingProbe.cpp UnwindProbe.cpp; do
    object="$OUT/obj/companion-probe/$path.o"
    compile "$SRC/test/$path" "$object" -DA10VM_DYNAMIC_PROBE -fno-builtin \
        -frounding-math -fno-optimize-sibling-calls
    objects="$objects $object"
done
compile "$ROOT/container-probe/runtime/test/ProcessIdentity.cpp" \
    "$OUT/obj/companion-probe/ProcessIdentity.o" -DA10VM_DYNAMIC_PROBE
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 \
    -z max-page-size=4096 -z now -z relro --hash-style=gnu --eh-frame-hdr --build-id=sha1 \
    --no-undefined --exclude-libs ALL -T "$ROOT/container-probe/runtime/arm64-tls.ld" \
    "$OUT/obj/companion-probe/crtbegin.o" $objects "$OUT/obj/companion-probe/ProcessIdentity.o" \
    "$OUT/lib/liba10vm-exceptions.so" "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" \
    "$OUT/lib/libm.so" "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" "$builtins" \
    "$OUT/obj/companion-probe/crtend.o" -o "$OUT/bin/companion-probe"
llvm-readelf -hlWd "$OUT/bin/companion-probe" > "$OUT/companion/probe-elf.txt"
