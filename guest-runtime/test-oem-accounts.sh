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
platform_compile "$ROOT/guest-runtime/test/OemAccountsCheck.cpp" "$OUT/obj/oem-accounts-check.o"
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder-probe/crtbegin.o" "$OUT/obj/oem-accounts-check.o" \
    "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" \
    "$OUT/obj/binder-probe/crtend.o" -o "$OUT/bin/oem-accounts-check"
exec python3 "$ROOT/guest-runtime/test-oem-accounts.py" "$@"
