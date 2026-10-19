#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime/binder"
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT"
clang++ -std=c++17 -O2 -Wall -Wextra -Werror -Wno-missing-field-initializers -pthread -I"$SRC/native" \
    "$SRC/test/BinderMultiOpenTest.cpp" "$SRC/test/DriverSwitch.cpp" \
    "$SRC/native/Broker.cpp" "$SRC/native/BrokerDispatch.cpp" "$SRC/native/BrokerObjects.cpp" \
    "$SRC/native/BrokerTransactions.cpp" "$SRC/native/BrokerCleanup.cpp" "$SRC/native/BrokerNodeReclaim.cpp" \
    "$SRC/native/Wire.cpp" "$SRC/native/TransactionLayout.cpp" "$SRC/native/TransactionWire.cpp" \
    "$SRC/native/ClientBuffers.cpp" "$SRC/native/Driver.cpp" -o "$OUT/multi-open-test"
TASK_TEMP=$(mktemp -d "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/a10b-multi.XXXXXX")
trap 'rm -f "$TASK_TEMP/binder.sock"; rmdir "$TASK_TEMP"' EXIT
timeout 10 "$OUT/multi-open-test" "$TASK_TEMP/binder.sock"
