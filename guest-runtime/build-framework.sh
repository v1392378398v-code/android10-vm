#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
DEST="$ROOT/artifacts/container/framework"
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$SRC/build-libraries.sh"
sh "$SRC/build-probes.sh"
sh "$ROOT/guest-runtime/build-properties.sh"
sh "$ROOT/guest-runtime/build-devices.sh"
. "$SRC/compile.sh"
mkdir -p "$DEST/lib" "$DEST/obj" "$DEST/classes" "$DEST/dex"
platform_compile "$ROOT/guest-runtime/native/BinderDevices.cpp" "$DEST/obj/binder-devices.o"
ld.lld -shared -soname liba10vm-binder-devices.so -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/binder-devices.o" \
    "$OUT/lib/liba10binder.so" "$OUT/lib/libc.so" "$OUT/obj/binder/crtend_so.o" \
    -o "$DEST/lib/liba10vm-binder-devices.so"
platform_compile "$ROOT/guest-runtime/native/ManagerPolicy.c" "$DEST/obj/manager-policy.o"
ld.lld -shared -soname liba10vm-manager-policy.so -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/manager-policy.o" \
    "$OUT/lib/libc.so" "$OUT/obj/binder/crtend_so.o" \
    -o "$DEST/lib/liba10vm-manager-policy.so"
platform_compile "$SRC/native/ServiceRegistry.cpp" "$DEST/obj/service-registry.o"
platform_compile "$ROOT/guest-runtime/native/RegistryMain.cpp" "$DEST/obj/registry-main.o"
mkdir -p "$DEST/bin"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 \
    -z max-page-size=4096 -z now -z relro --hash-style=gnu --eh-frame-hdr \
    --no-undefined --exclude-libs ALL "$OUT/obj/binder-probe/crtbegin.o" \
    "$DEST/obj/service-registry.o" "$DEST/obj/registry-main.o" \
    "$OUT/lib/libbinder.so" "$OUT/lib/liba10binder.so" "$OUT/lib/libutils.so" \
    "$OUT/lib/libcutils.so" "$OUT/lib/libbase.so" "$OUT/lib/liblog.so" \
    "$OUT/lib/libbinderthreadstate.so" "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" \
    "$OUT/lib/libm.so" "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" \
    "$builtins" "$OUT/obj/binder-probe/crtend.o" -o "$DEST/bin/binder-registry"
sh "$ROOT/guest-runtime/build-checks.sh"
