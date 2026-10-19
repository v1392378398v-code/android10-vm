#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
unset LD_LIBRARY_PATH LD_PRELOAD
OUT="$ROOT/app/build/native-display"
LIBS="$OUT/jniLibs/arm64-v8a"
mkdir -p "$LIBS" "$OUT/assets"
files='[]'
for library in linker libc libdl libm; do rm -f "$LIBS/liba10vm-a10-$library.so"; done
name=liba10vm-p1-client.so
cp "$ROOT/artifacts/container/graphics/bin/codec-client" "$LIBS/$name"
files=$(printf '%s' "$files" | jq --arg name "$name" \
    --arg sha256 "$(sha256sum "$LIBS/$name" | cut -d ' ' -f 1)" \
    --argjson bytes "$(stat -c %s "$LIBS/$name")" '. + [{name: $name, sha256: $sha256, bytes: $bytes}]')
renderer="$ROOT/native-display/build/prepared/jniLibs/arm64-v8a/liba10vm-desktop-window.so"
files=$(printf '%s' "$files" | jq --arg name "$(basename "$renderer")" \
    --arg sha256 "$(sha256sum "$renderer" | cut -d ' ' -f 1)" \
    --argjson bytes "$(stat -c %s "$renderer")" '. + [{name: $name, sha256: $sha256, bytes: $bytes}]')
jq -n --argjson files "$files" --arg codec "$(tr -d '\n' < artifacts/container/graphics/codec-id.txt)" \
    '{backend: "native-arm64-gles-surface", rootRequired: false, desktopImplemented: true,
      inputProtocol: "touch-v2", targetHz: 120, width: 1080, height: 2160, density: 480,
      codec: $codec, files: $files}' \
    > "$OUT/assets/native-display-inputs.json"
printf 'Staged rootless native display inputs: %s\n' "$OUT"
