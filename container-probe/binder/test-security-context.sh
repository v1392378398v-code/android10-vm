#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime/binder"
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT"
clang++ -std=c++17 -O2 -pthread -I"$SRC/native" \
    "$SRC/test/BinderSecurityContextTest.cpp" "$SRC/native/Broker.cpp" "$SRC/native/BrokerDispatch.cpp" \
    "$SRC/native/BrokerObjects.cpp" "$SRC/native/BrokerTransactions.cpp" "$SRC/native/BrokerCleanup.cpp" \
    "$SRC/native/BrokerNodeReclaim.cpp" \
    "$SRC/native/Wire.cpp" "$SRC/native/TransactionLayout.cpp" "$SRC/native/TransactionWire.cpp" \
    "$SRC/native/ClientBuffers.cpp" -o "$OUT/security-context-test"
timeout 10 "$OUT/security-context-test"
