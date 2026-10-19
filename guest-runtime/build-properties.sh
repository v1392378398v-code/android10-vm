#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
DEST="$ROOT/artifacts/container/framework"
PROP="$ROOT/container-probe/properties"
D="$ROOT/artifacts/container/properties/derived"
PB="$D/bionic/libc"
PC="$D/core/property_service/libpropertyinfoparser"
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$PROP/prepare-sources.sh"
. "$SRC/compile.sh"
mkdir -p "$DEST/obj/properties" "$DEST/bin" "$DEST/lib"
objects=
for input in "$PB/system_properties/context_node.cpp" "$PB/system_properties/contexts_serialized.cpp" \
    "$PB/system_properties/prop_area.cpp" "$PB/system_properties/prop_info.cpp" \
    "$PB/system_properties/system_properties.cpp" "$PC/property_info_parser.cpp" \
    "$PB/async_safe/async_safe_log.cpp" "$PROP/native/PrivateProperties.cpp" \
    "$PROP/native/PropertyInfo.cpp" "$ROOT/guest-runtime/native/PropertyService.cpp"; do
    object="$DEST/obj/properties/$(basename "$input").o"
    platform_compile "$input" "$object" -I"$PROP/native" -I"$PB" \
        -I"$PB/async_safe/include" -I"$PB/system_properties/include" -I"$PC/include"
    objects="$objects $object"
done
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 -z now -z relro -z max-page-size=4096 \
    --no-undefined --exclude-libs ALL "$OUT/obj/binder-probe/crtbegin.o" $objects \
    "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" "$OUT/lib/libc.so" "$OUT/lib/libm.so" \
    "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" "$builtins" "$OUT/obj/binder-probe/crtend.o" \
    -o "$DEST/bin/property-service"
platform_compile "$ROOT/guest-runtime/native/PropertyClient.c" "$DEST/obj/property-client.o"
ld.lld -shared -soname liba10vm-property-client.so -z now -z relro -z max-page-size=4096 \
    --no-undefined "$OUT/obj/binder/crtbegin_so.o" "$DEST/obj/property-client.o" "$OUT/lib/libc.so" \
    "$OUT/obj/binder/crtend_so.o" -o "$DEST/lib/liba10vm-property-client.so"
