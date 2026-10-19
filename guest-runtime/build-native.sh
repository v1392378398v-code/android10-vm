#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/properties"
OUT="$ROOT/artifacts/container/art"
D="$ROOT/artifacts/container/properties/derived"
NDK=${ANDROID_NDK_HOME:-"$HOME/Android/Sdk/ndk/29.0.13113456"}
SDK=${ANDROID_HOME:-"$HOME/Android/Sdk"}
SYSROOT="$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot"
unset LD_LIBRARY_PATH LD_PRELOAD
for tool in clang++ patchelf llvm-strip; do command -v "$tool" >/dev/null; done
B="$D/bionic/libc"
C="$D/core/property_service/libpropertyinfoparser"
UNWIND=
for path in "$NDK"/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/*/lib/linux/aarch64; do
    if [ -f "$path/libunwind.a" ]; then UNWIND=$path; break; fi
done
test -n "$UNWIND"
mkdir -p "$OUT/bin" "$OUT/lib"
clang++ --target=aarch64-linux-android29 --sysroot="$SYSROOT" \
    -nostdinc++ -isystem "$SYSROOT/usr/include/c++/v1" -nostdlib++ \
    -std=c++17 -O2 -fPIE -pie -fvisibility=hidden -Wall -Wextra -Werror \
    -Wno-unused-parameter -Wno-vla-cxx-extension \
    -I"$SRC/native" -I"$B" -I"$B/async_safe/include" -I"$B/system_properties/include" \
    -I"$C/include" -L"$UNWIND" -Wl,-z,max-page-size=16384 \
    "$ROOT/guest-runtime/native/SeedProperties.cpp" "$SRC/native/PrivateProperties.cpp" \
    "$SRC/native/PropertyInfo.cpp" "$ROOT/artifacts/container/properties/lib/liba10vm-property-core.a" \
    "$SYSROOT/usr/lib/aarch64-linux-android/libc++_static.a" \
    "$SYSROOT/usr/lib/aarch64-linux-android/libc++abi.a" -ldl -lm -o "$OUT/bin/seed-properties"
patchelf --remove-rpath "$OUT/bin/seed-properties"
llvm-strip --strip-unneeded "$OUT/bin/seed-properties"
mkdir -p "$OUT/classes" "$OUT/dex"
javac --release 8 -d "$OUT/classes" "$ROOT/guest-runtime/check/RuntimeCheck.java" \
    "$ROOT/guest-runtime/check/DirectoryCheck.java" \
    "$ROOT/guest-runtime/check/ProcessEvidence.java"
BUILD_TOOLS=${A10VM_BUILD_TOOLS:-"$SDK/build-tools/35.0.0"}
bash "$BUILD_TOOLS/d8" --min-api 29 --output "$OUT/dex" \
    "$OUT/classes/io/a10vm/guest/"*.class
mkdir -p "$OUT/obj"
clang --target=aarch64-linux-android29 --sysroot="$SYSROOT" -fPIC -O2 -Wall -Wextra -Werror \
    -c "$ROOT/guest-runtime/native/GuestLog.c" -o "$OUT/obj/guest-log.o"
RUNTIME="$ROOT/artifacts/container/runtime"
ld.lld -shared -soname liba10vm-guest-log.so -z now -z relro -z max-page-size=4096 \
    --no-undefined "$RUNTIME/obj/binder/crtbegin_so.o" "$OUT/obj/guest-log.o" \
    "$RUNTIME/lib/libc.so" "$RUNTIME/obj/binder/crtend_so.o" -o "$OUT/lib/liba10vm-guest-log.so"
