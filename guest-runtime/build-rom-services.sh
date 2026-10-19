#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/artifacts/container/rom-services"
RUNTIME="$ROOT/artifacts/container/runtime"
NDK=${ANDROID_NDK_HOME:-"$HOME/Android/Sdk/ndk/29.0.13113456"}
SYSROOT="$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot"
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT"
clang --target=aarch64-linux-android29 --sysroot="$SYSROOT" -fPIC -O2 -Wall -Wextra -Werror \
    -c "$ROOT/guest-runtime/native/RomServiceIdentity.c" -o "$OUT/identity.o"
ld.lld -shared -soname liba10vm-rom-service-identity.so -z now -z relro -z max-page-size=4096 \
    --no-undefined "$RUNTIME/obj/binder/crtbegin_so.o" "$OUT/identity.o" "$RUNTIME/lib/libc.so" \
    "$RUNTIME/obj/binder/crtend_so.o" -o "$OUT/liba10vm-rom-service-identity.so"
clang --target=aarch64-linux-android29 --sysroot="$SYSROOT" -fPIE -O2 -Wall -Wextra -Werror \
    -c "$ROOT/guest-runtime/test/RomServiceIdentityCheck.c" -o "$OUT/identity-check.o"
ld.lld -pie -e _start --dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined "$RUNTIME/obj/binder-probe/crtbegin.o" "$OUT/identity-check.o" "$RUNTIME/lib/libc.so" \
    "$RUNTIME/obj/binder-probe/crtend.o" -o "$OUT/identity-check"
