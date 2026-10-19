#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/hwbinder"
OUT="$ROOT/artifacts/container/runtime"
PREPARED="$ROOT/container-probe/build/prepared"

sh "$ROOT/container-probe/binder/prepare-apk.sh" "$@"
sh "$SRC/build-libraries.sh"
sh "$SRC/build-hidl.sh"
sh "$SRC/build-probes.sh"

files='[]'
record() {
    input=$1
    name=$2
    cp "$OUT/$input" "$PREPARED/jniLibs/arm64-v8a/$name"
    needed=$(llvm-readelf -d "$OUT/$input" | sed -n 's/.*Shared library: \[\(.*\)\].*/\1/p' | jq -R . | jq -s .)
    files=$(printf '%s' "$files" | jq --arg name "$name" \
        --arg sha256 "$(sha256sum "$OUT/$input" | cut -d ' ' -f 1)" \
        --argjson bytes "$(stat -c %s "$OUT/$input")" --argjson needed "$needed" \
        '. + [{name: $name, sha256: $sha256, bytes: $bytes, needed: $needed}]')
}
record bin/hwbinder-probe liba10vm-p2-hwbinder-probe.so
record lib/libhwbinder.so liba10vm-source-libhwbinder.so
record lib/libhidlbase.so liba10vm-source-libhidlbase.so
record lib/liba10hidl-values.so liba10vm-hidl-values.so
checks=$(jq -R . "$SRC/checks.txt" | jq -s .)
component=$( (cd "$SRC" && sha256sum archives.txt sources.sha256 hidl-sources.sha256 checks.txt platform.patch \
    *.sh *.py test/*) | sha256sum | cut -d ' ' -f 1)
jq -n --arg component "$component" --argjson files "$files" --argjson checks "$checks" \
    '{component: $component, tag: "android-10.0.0_r47", gate: "P2-private-hwbinder",
      sourceBuilt: true, completeG2: false, files: $files, requiredChecks: $checks}' \
    > "$PREPARED/assets/hwbinder-inputs.json"
printf 'Prepared source-built HwBinder probe inputs: %s\n' "$PREPARED"
