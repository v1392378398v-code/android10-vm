#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
UP="$OUT/upstream"
B="$UP/bionic/libc"
CACHE="$ROOT/container-probe/runtime/dynamic/compile-source.py"
unset LD_LIBRARY_PATH LD_PRELOAD
. "$SRC/compile.sh"
mkdir -p "$OUT/obj/binder-probe" "$OUT/bin"
compile "$B/arch-common/bionic/crtbegin.c" "$OUT/obj/binder-probe/crtbegin.o"
compile "$B/arch-common/bionic/crtend.S" "$OUT/obj/binder-probe/crtend.o"
builtins=$(clang --target=aarch64-linux-android29 --print-libgcc-file-name)
for program in binder-broker binder-probe broker-dispatch-test broker-cleanup-test broker-reclaim-benchmark; do
    case "$program" in
        binder-broker) inputs='native/Broker.cpp native/BrokerDispatch.cpp native/BrokerObjects.cpp native/BrokerTransactions.cpp native/BrokerCleanup.cpp native/BrokerNodeReclaim.cpp native/BrokerMain.cpp' ;;
        binder-probe) inputs='test/ProbeMain.cpp test/Registry.cpp native/ServiceRegistry.cpp test/Service.cpp test/Client.cpp test/Resources.cpp test/DriverSwitch.cpp' ;;
        broker-dispatch-test) inputs='native/Broker.cpp native/BrokerDispatch.cpp native/BrokerObjects.cpp native/BrokerTransactions.cpp native/BrokerCleanup.cpp native/BrokerNodeReclaim.cpp test/BrokerDispatchTest.cpp' ;;
        broker-cleanup-test) inputs='native/Broker.cpp native/BrokerDispatch.cpp native/BrokerObjects.cpp native/BrokerTransactions.cpp native/BrokerCleanup.cpp native/BrokerNodeReclaim.cpp test/BrokerCleanupTest.cpp' ;;
        broker-reclaim-benchmark) inputs='native/Broker.cpp native/BrokerDispatch.cpp native/BrokerObjects.cpp native/BrokerTransactions.cpp native/BrokerCleanup.cpp native/BrokerNodeReclaim.cpp test/BrokerReclaimBenchmark.cpp' ;;
    esac
    objects=
    for path in $inputs; do
        object="$OUT/obj/binder-probe/$(printf '%s' "$path" | tr / _).o"
        platform_compile "$SRC/$path" "$object" -I"$SRC/test"
        objects="$objects $object"
    done
    ld.lld -pie -e _start -dynamic-linker /system/bin/linker64 \
        -z max-page-size=4096 -z now -z relro --hash-style=gnu --eh-frame-hdr --build-id=sha1 \
        --no-undefined --exclude-libs ALL \
        "$OUT/obj/binder-probe/crtbegin.o" $objects \
        "$OUT/lib/libbinder.so" "$OUT/lib/liba10binder.so" "$OUT/lib/libutils.so" \
        "$OUT/lib/libcutils.so" "$OUT/lib/libbase.so" "$OUT/lib/liblog.so" \
        "$OUT/lib/libbinderthreadstate.so" "$OUT/lib/libc++.so" "$OUT/lib/libunwind.so" \
        "$OUT/lib/libm.so" "$OUT/lib/libc.so" "$OUT/lib/libdl.so" "$OUT/bin/source-linker64" \
        "$builtins" "$OUT/obj/binder-probe/crtend.o" -o "$OUT/bin/$program"
    llvm-readelf -hlWd "$OUT/bin/$program" > "$OUT/binder/$program-elf.txt"
done
