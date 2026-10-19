#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$SRC/compile.sh"
platform_compile "$ROOT/guest-runtime/test/RawApkCheck.cpp" "$OUT/obj/raw-apk-check.o"
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder-probe/crtbegin.o" "$OUT/obj/raw-apk-check.o" \
    "$OUT/lib/libc.so" "$OUT/bin/source-linker64" "$OUT/obj/binder-probe/crtend.o" \
    -o "$OUT/bin/raw-apk-check"
platform_compile "$ROOT/guest-runtime/test/ApkNamespaceCheck.cpp" "$OUT/obj/apk-namespace-check.o"
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder-probe/crtbegin.o" "$OUT/obj/apk-namespace-check.o" \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" \
    "$OUT/obj/binder-probe/crtend.o" -o "$OUT/bin/apk-namespace-check"
sh "$ROOT/guest-runtime/build-checks.sh"
exec python3 "$ROOT/guest-runtime/test-code-paths.py" "$@"
