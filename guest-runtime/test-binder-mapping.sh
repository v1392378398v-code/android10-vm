#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/artifacts/container/framework"
mkdir -p "$OUT/bin"
unset LD_LIBRARY_PATH LD_PRELOAD
clang++ -std=c++17 -fno-emulated-tls -I"$ROOT/container-probe/binder/native" \
    "$ROOT/guest-runtime/native/BinderDevices.cpp" \
    "$ROOT/guest-runtime/check/BinderMappingTest.cpp" \
    -o "$OUT/bin/binder-mapping-test"
"$OUT/bin/binder-mapping-test"
