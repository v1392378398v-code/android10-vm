#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SDK=${ANDROID_HOME:-"$HOME/Android/Sdk"}
ANDROID_JAR="$SDK/platforms/android-35/android.jar"
DEST="$ROOT/artifacts/container/runtime-identity-check"
mkdir -p "$DEST"
javac --release 8 -cp "$ANDROID_JAR" -d "$DEST" \
    "$ROOT/guest-runtime/src/main/java/io/a10vm/guestruntime/StartupLog.java" \
    "$ROOT/guest-runtime/src/main/java/io/a10vm/guestruntime/RuntimeFiles.java" \
    "$ROOT/guest-runtime/src/main/java/io/a10vm/guestruntime/GuestMappingPaths.java" \
    "$ROOT/guest-runtime/src/main/java/io/a10vm/guestruntime/RuntimeIdentity.java" \
    "$ROOT/guest-runtime/test/RuntimeIdentityMappingCheck.java"
java -cp "$DEST:$ANDROID_JAR" io.a10vm.guestruntime.RuntimeIdentityMappingCheck
