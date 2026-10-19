#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SDK=${ANDROID_HOME:-"$HOME/Android/Sdk"}
DEST="$ROOT/artifacts/device-compat/memory-priority-check"
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$DEST/classes" "$DEST/dex"
javac --release 8 -cp "$SDK/platforms/android-35/android.jar" -d "$DEST/classes" \
    "$ROOT/guest-runtime/check/ProcessEvidence.java" \
    "$ROOT/guest-runtime/check/GuestScheduling.java" \
    "$ROOT/guest-runtime/check/GuestMemory.java" \
    "$ROOT/guest-runtime/test/GuestMemoryPriorityCheck.java"
bash "$SDK/build-tools/35.0.0/d8" --min-api 29 --lib "$SDK/platforms/android-35/android.jar" \
    --output "$DEST/dex" "$DEST/classes/io/a10vm/guest/"*.class
