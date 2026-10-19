#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/artifacts/container/network/test"
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT/plain" "$OUT/pid"
clang++ -std=c++17 -O2 -fPIC -shared \
    -I"$ROOT/artifacts/container/media/upstream/system/netd/include" \
    "$ROOT/guest-runtime/native/HostNetdClient.cpp" "$ROOT/guest-runtime/native/HostConnect.cpp" \
    -o "$OUT/libnetd-client-check.so"
clang++ -std=c++17 -O2 "$ROOT/guest-runtime/test/HostNetdClientCheck.cpp" -o "$OUT/netd-client-check"
clang++ -std=c++17 -O2 -fPIC -shared "$ROOT/guest-runtime/test/HostNetdClientFixture.cpp" \
    -o "$OUT/plain/liba10vm-host-netd-client.so"
clang++ -std=c++17 -O2 -fPIC -shared -DHOST_HAS_TAG_WITH_PID \
    "$ROOT/guest-runtime/test/HostNetdClientFixture.cpp" -o "$OUT/pid/liba10vm-host-netd-client.so"
LD_LIBRARY_PATH="$OUT/plain" "$OUT/netd-client-check" "$OUT/libnetd-client-check.so" plain
LD_LIBRARY_PATH="$OUT/pid" "$OUT/netd-client-check" "$OUT/libnetd-client-check.so" pid
