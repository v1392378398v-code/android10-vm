#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/artifacts/container/media"
UP="$ROOT/artifacts/container/runtime/upstream"
HIDL="$DEST/upstream/system/tools/hidl"
AIDL="$DEST/upstream/system/tools/aidl"
BASE="$UP/system/core/base"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
unset LD_LIBRARY_PATH LD_PRELOAD
sh "$ROOT/guest-runtime/fetch-media-sources.sh"
mkdir -p "$DEST/tools" "$DEST/obj/tools" "$DEST/generated/tools"
host_compile() {
    input=$1
    object=$2
    shift 2
    python3 "$CACHE" "$object" clang++ --target=aarch64-linux-android29 -std=gnu++17 -O2 -fPIC -DNDEBUG \
        -MD -MF "$object.d" -Wno-deprecated-declarations \
        -I"$BASE/include" -I"$UP/system/core/liblog/include" -I"$UP/system/core/libutils/include" \
        "$@" -c "$input" -o "$object"
}
base_objects=
for name in file logging stringprintf strings errors_unix threads; do
    object="$DEST/obj/tools/base-$name.o"
    host_compile "$BASE/$name.cpp" "$object"
    base_objects="$base_objects $object"
done
sed '/^%pure-parser$/d' "$HIDL/hidl-gen_y.yy" > "$DEST/generated/tools/hidl-gen_y.yy"
bison --defines="$DEST/generated/tools/hidl-gen_y.h" \
    -o "$DEST/generated/tools/hidl-gen_y.cpp" "$DEST/generated/tools/hidl-gen_y.yy"
sed '/#include "hidl-gen_y.h"/a\
#define YYSTYPE yy::parser::semantic_type\
#define YYLTYPE yy::parser::location_type' "$HIDL/hidl-gen_l.ll" > "$DEST/generated/tools/hidl-gen_l.ll"
flex -o "$DEST/generated/tools/hidl-gen_l.cpp" "$DEST/generated/tools/hidl-gen_l.ll"
hidl_objects=
for input in "$HIDL/"*.cpp "$HIDL/host_utils/"*.cpp "$HIDL/utils/"*.cpp \
    "$HIDL/hashing/Hash.cpp" "$DEST/generated/tools/hidl-gen_y.cpp" \
    "$DEST/generated/tools/hidl-gen_l.cpp"; do
    object="$DEST/obj/tools/hidl-$(basename "$input" .cpp).o"
    host_compile "$input" "$object" -I"$HIDL" -I"$HIDL/host_utils/include" \
        -I"$HIDL/host_utils/include/hidl-util" -I"$HIDL/utils/include" \
        -I"$HIDL/utils/include/hidl-util" -I"$HIDL/hashing/include" \
        -I"$DEST/upstream/external/boringssl/src/include" -I"$DEST/generated/tools"
    hidl_objects="$hidl_objects $object"
done
clang++ $hidl_objects $base_objects -L/system/lib64 -llog -lcrypto -o "$DEST/tools/hidl-gen"
sed '/^%pure-parser$/d' "$AIDL/aidl_language_y.yy" > "$DEST/generated/tools/aidl_language_y.yy"
bison --defines="$DEST/generated/tools/aidl_language_y.h" \
    -o "$DEST/generated/tools/aidl_language_y.cpp" "$DEST/generated/tools/aidl_language_y.yy"
sed '/#include "aidl_language_y.h"/a\
#define YYSTYPE yy::parser::semantic_type\
#define YYLTYPE yy::parser::location_type' "$AIDL/aidl_language_l.ll" > "$DEST/generated/tools/aidl_language_l.ll"
flex -o "$DEST/generated/tools/aidl_language_l.cpp" "$DEST/generated/tools/aidl_language_l.ll"
aidl_objects=
for input in "$AIDL/"*.cpp "$DEST/generated/tools/aidl_language_y.cpp" \
    "$DEST/generated/tools/aidl_language_l.cpp"; do
    case "$input" in *_unittest.cpp|*/main_cpp.cpp) continue ;; esac
    object="$DEST/obj/tools/aidl-$(basename "$input" .cpp).o"
    host_compile "$input" "$object" -Wno-c++11-narrowing -I"$AIDL" -I"$DEST/generated/tools"
    aidl_objects="$aidl_objects $object"
done
clang++ $aidl_objects $base_objects -L/system/lib64 -llog -o "$DEST/tools/aidl"
printf 'Built Android 10 interface generators: %s\n' "$DEST/tools"
