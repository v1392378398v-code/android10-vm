#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
unset LD_LIBRARY_PATH LD_PRELOAD
work=$(mktemp -d "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/a10vm-driver-wakeups.XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
clang++ -std=c++17 -O2 -Wall -Wextra -Werror -Wno-missing-field-initializers -pthread -I"$SRC/native" \
    "$SRC/test/DriverWakeupsTest.cpp" "$SRC/native/Driver.cpp" "$SRC/native/Wire.cpp" \
    "$SRC/native/TransactionWire.cpp" "$SRC/native/TransactionLayout.cpp" \
    "$SRC/native/ClientBuffers.cpp" -o "$work/check"
timeout 15 "$work/check" "$work/binder.sock"
timeout 15 "$work/check" "$work/binder.sock" legacy
if [ "$#" -eq 1 ]; then
    git -C "$ROOT" show "$1:container-probe/binder/native/Driver.cpp" > "$work/Driver.before.cpp"
    clang++ -std=c++17 -O2 -Wall -Wextra -Werror -Wno-missing-field-initializers -pthread -I"$SRC/native" \
        "$SRC/test/DriverWakeupsTest.cpp" "$work/Driver.before.cpp" "$SRC/native/Wire.cpp" \
        "$SRC/native/TransactionWire.cpp" "$SRC/native/TransactionLayout.cpp" \
        "$SRC/native/ClientBuffers.cpp" -o "$work/before"
    if timeout 15 "$work/before" "$work/binder.sock"; then
        printf '%s\n' 'Expected the previous driver to fail the request-count checks' >&2
        exit 1
    else
        test "$?" -eq 7
    fi
fi
