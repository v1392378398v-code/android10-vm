#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/runtime"
OUT="$ROOT/artifacts/container/runtime"
PREPARED="$ROOT/container-probe/build/prepared"
sh "$ROOT/container-probe/properties/prepare-apk.sh" "$@"
sh "$SRC/build-native.sh"
NAME=liba10vm-p2-bootstrap.so
cp "$OUT/bin/bootstrap-probe" "$PREPARED/jniLibs/arm64-v8a/$NAME"
component=$( (cd "$SRC"; sha256sum archives.txt sources.sha256 static-sources.txt \
    platform.patch arm64-tls.ld build-native.sh fetch-sources.sh record-sources.py test/*) | \
    sha256sum | cut -d ' ' -f 1)
jq -n --arg component "$component" --arg name "$NAME" \
    --arg sha256 "$(sha256sum "$OUT/bin/bootstrap-probe" | cut -d ' ' -f 1)" \
    --argjson bytes "$(stat -c %s "$OUT/bin/bootstrap-probe")" \
    '{component: $component, tag: "android-10.0.0_r47", staticBionicBootstrap: true,
      dynamicRuntimeIntegrated: false, files: [{name: $name, sha256: $sha256,
      bytes: $bytes, needed: []}]}' > "$PREPARED/assets/runtime-inputs.json"
printf 'Prepared static Bionic bootstrap inputs: %s\n' "$PREPARED"
