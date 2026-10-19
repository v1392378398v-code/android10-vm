#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
OUT="$ROOT/artifacts/container/runtime"
SRC="$ROOT/container-probe/hwbinder"
for path in system/libhwbinder/ProcessState.cpp system/libhwbinder/IPCThreadState.cpp; do
    mkdir -p "$OUT/derived/$(dirname "$path")"
    cp "$OUT/upstream/$path" "$OUT/derived/$path"
done
git apply --recount --check --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
git apply --recount --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
