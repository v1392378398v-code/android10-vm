#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST=$(mktemp -d "${TMPDIR:-$HOME}/sensor-values.XXXXXX")
trap 'rm -rf "$DEST"' EXIT HUP INT TERM
javac --release 8 -d "$DEST" \
    "$ROOT/guest-runtime/src/main/java/io/a10vm/guestruntime/SensorEventValues.java" \
    "$ROOT/guest-runtime/test/SensorEventValuesTest.java"
java -cp "$DEST" io.a10vm.guestruntime.SensorEventValuesTest
