#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/artifacts/container/camera/tools"
DEXLIB=${A10VM_DEXLIB_JAR:-/data/data/com.termux/files/usr/share/java/jadx-1.5.6-all.jar}
mkdir -p "$OUT"
javac --release 8 -cp "$DEXLIB" -d "$OUT" \
    "$ROOT/guest-runtime/build-tools/DexArchive.java" "$ROOT/guest-runtime/build-tools/PatchMiuiCamera.java"
exec java -cp "$OUT:$DEXLIB" PatchMiuiCamera "$1" "$2"
