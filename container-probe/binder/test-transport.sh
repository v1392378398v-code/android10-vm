#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime/binder"
for tool in clang++ timeout; do command -v "$tool" >/dev/null; done
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT"
clang++ -std=c++17 -O2 -Wall -Wextra -Werror -pthread -I"$SRC/native" \
    "$SRC/test/TransactionWireTest.cpp" "$SRC/native/Wire.cpp" \
    "$SRC/native/TransactionLayout.cpp" "$SRC/native/TransactionWire.cpp" \
    "$SRC/native/ClientBuffers.cpp" -o "$OUT/transport-test"
timeout 10 "$OUT/transport-test"
clang++ -std=c++17 -O2 -Wall -Wextra -Werror -pthread -I"$SRC/native" \
    "$SRC/test/WirePacketTest.cpp" "$SRC/native/Wire.cpp" -o "$OUT/wire-packet-test"
timeout 10 "$OUT/wire-packet-test"
