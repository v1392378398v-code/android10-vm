#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/runtime"
OUT="$ROOT/artifacts/container/runtime"
PROPS="$ROOT/artifacts/container/properties/derived"
for tool in clang clang++ llvm-ar llvm-readelf llvm-nm sha256sum git python3; do
    command -v "$tool" >/dev/null
done
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT/upstream/system"
# The earlier exploratory cache used the short repository name.
if [ -d "$OUT/upstream/core" ] && [ ! -d "$OUT/upstream/system/core" ]; then
    mv "$OUT/upstream/core" "$OUT/upstream/system/core"
fi
sh "$SRC/fetch-sources.sh" "${1:-}"
sh "$ROOT/container-probe/properties/prepare-sources.sh"
mkdir -p "$OUT/obj/static" "$OUT/bin" "$OUT/lib"
B="$OUT/upstream/bionic/libc"
P="$PROPS/bionic/libc"
C="$PROPS/core/property_service/libpropertyinfoparser"
mkdir -p "$OUT/derived/bionic/libc/bionic"
cp "$B/bionic/bionic_systrace.cpp" "$OUT/derived/bionic/libc/bionic/"
git apply --recount --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
compile() {
    input=$1
    object=$2
    shift 2
    case "$input" in
        */linker_memory.cpp|*/cxa_thread_atexit.cpp) cxx_include="$OUT/upstream/external/libcxx/include" ;;
        *) cxx_include="$OUT/upstream/bionic/libstdc++/include" ;;
    esac
    set -- --target=aarch64-linux-android29 -nostdinc \
        -isystem "$cxx_include" \
        -isystem "$(clang -print-resource-dir)/include" \
        -isystem "$B/include" -isystem "$B/kernel/uapi/asm-arm64" \
        -isystem "$B/kernel/uapi" -isystem "$B/kernel/android/uapi" \
        -I"$B" -I"$B/async_safe/include" -I"$B/private" \
        -I"$B/stdio" \
        -I"$OUT/upstream/system/core/liblog/include" \
        -I"$OUT/upstream/system/core/libcutils/include" \
        -I"$OUT/upstream/external/libcxxabi/include" \
        -I"$P/system_properties/include" -I"$C/include" \
        -I"$B/upstream-openbsd/android/include" \
        -I"$B/upstream-openbsd/lib/libc/include" \
        -fPIC -fno-stack-protector -fno-exceptions -fno-rtti -fno-sized-deallocation \
        -fno-emulated-tls \
        -ffunction-sections -fdata-sections -mno-outline-atomics \
        -O2 -D_LIBC=1 -DLIBC_STATIC -Wno-main \
        -MD -MF "$object.d" "$@"
    case "$input" in
        */cxa_thread_atexit.cpp) set -- "$@" -DHAVE___CXA_THREAD_ATEXIT_IMPL ;;
    esac
    case "$input" in
        *.cpp) clang++ "$@" -nostdinc++ -std=gnu++17 -c "$input" -o "$object" ;;
        *.c) clang "$@" -std=gnu99 -c "$input" -o "$object" ;;
        *.S) clang "$@" -c "$input" -o "$object" ;;
    esac
}
objects=
. "$SRC/filesystem/sources.sh"
while read -r path; do
    if guest_fs_replaces "$path"; then continue; fi
    object="$OUT/obj/static/$(printf '%s' "$path" | tr / _).o"
    case "$path" in
        */upstream-openbsd/*) compile "$OUT/upstream/$path" "$object" -include openbsd-compat.h ;;
        *) compile "$OUT/upstream/$path" "$object" ;;
    esac
    objects="$objects $object"
done < "$SRC/static-sources.txt"
for path in GuestPaths GuestFileCalls GuestExec GuestOwnership GuestIdentity GuestXattrs GuestTimers GuestSockets; do
    object="$OUT/obj/static/$path.o"
    compile "$SRC/filesystem/$path.cpp" "$object"
    objects="$objects $object"
done
object="$OUT/obj/static/bionic_systrace.o"
compile "$OUT/derived/bionic/libc/bionic/bionic_systrace.cpp" "$object"
objects="$objects $object"
for path in system_properties/context_node.cpp system_properties/contexts_serialized.cpp \
    system_properties/prop_area.cpp system_properties/prop_info.cpp \
    system_properties/system_properties.cpp bionic/system_property_api.cpp async_safe/async_safe_log.cpp; do
    object="$OUT/obj/static/property_$(basename "$path" .cpp).o"
    compile "$P/$path" "$object"
    objects="$objects $object"
done
object="$OUT/obj/static/property_info_parser.o"
compile "$C/property_info_parser.cpp" "$object"
objects="$objects $object"
rm -f "$OUT/lib/liba10vm-bootstrap.a"
llvm-ar rcD "$OUT/lib/liba10vm-bootstrap.a" $objects
compile "$B/arch-common/bionic/crtbegin.c" "$OUT/obj/static/crtbegin.o"
compile "$B/arch-common/bionic/crtend.S" "$OUT/obj/static/crtend.o"
probe_objects=
for path in BootstrapProbe ThreadProbe ProcessIdentity; do
    object="$OUT/obj/static/probe_$path.o"
    compile "$SRC/test/$path.cpp" "$object"
    probe_objects="$probe_objects $object"
done
clang++ --target=aarch64-linux-android29 -nostdlib -static \
    -Wl,--gc-sections,-z,max-page-size=4096,--build-id=sha1 \
    -Wl,-T,"$SRC/arm64-tls.ld" \
    -Wl,-Map,"$OUT/bootstrap.map",--error-limit=0 \
    "$OUT/obj/static/crtbegin.o" $probe_objects \
    "$OUT/lib/liba10vm-bootstrap.a" "$OUT/obj/static/crtend.o" \
    -o "$OUT/bin/bootstrap-probe"
llvm-readelf -hlWd "$OUT/bin/bootstrap-probe" > "$OUT/bootstrap-elf.txt"
llvm-nm -u "$OUT/bin/bootstrap-probe" > "$OUT/bootstrap-undefined.txt"
sha256sum "$OUT/bin/bootstrap-probe" > "$OUT/native.sha256"
if [ "${1:-}" = --record ]; then
    python3 "$SRC/record-sources.py" "$OUT/upstream" "$SRC/sources.sha256" \
        $objects $probe_objects "$OUT/obj/static/crtbegin.o" "$OUT/obj/static/crtend.o"
fi
