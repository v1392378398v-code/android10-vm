#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
for path in frameworks/native/libs/binder/ProcessState.cpp \
    frameworks/native/libs/binder/IPCThreadState.cpp \
    frameworks/native/libs/binderthreadstate/IPCThreadStateBase.cpp system/core/libutils/misc.cpp \
    system/core/liblog/config_read.cpp system/core/liblog/config_write.cpp \
    system/core/liblog/logger_write.cpp; do
    mkdir -p "$OUT/derived/$(dirname "$path")"
    cp "$OUT/upstream/$path" "$OUT/derived/$path"
done
git apply --recount --check --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
git apply --recount --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
