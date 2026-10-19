#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
PREPARED="$ROOT/container-probe/build/prepared"

sh "$ROOT/container-probe/runtime/companion/prepare-apk.sh" "$@"
sh "$SRC/build-libraries.sh"
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
record bin/binder-probe liba10vm-p2-binder-probe.so
record bin/binder-broker liba10vm-p2-binder-broker.so
record lib/liblog.so liba10vm-source-liblog.so
record lib/libbase.so liba10vm-source-libbase.so
record lib/libcutils.so liba10vm-source-libcutils.so
record lib/libutils.so liba10vm-source-libutils.so
record lib/libbinderthreadstate.so liba10vm-source-libbinderthreadstate.so
record lib/liba10binder.so liba10vm-private-binder-transport.so
record lib/libbinder.so liba10vm-source-libbinder.so

for name in liba10vm-source-linker.so liba10vm-source-libc.so liba10vm-source-libdl.so \
        liba10vm-source-libm.so liba10vm-source-libcxx.so liba10vm-source-libunwind.so \
        liba10vm-p2-properties.so; do
    path="$PREPARED/jniLibs/arm64-v8a/$name"
    needed=$(llvm-readelf -d "$path" | sed -n 's/.*Shared library: \[\(.*\)\].*/\1/p' | jq -R . | jq -s .)
    files=$(printf '%s' "$files" | jq --arg name "$name" \
        --arg sha256 "$(sha256sum "$path" | cut -d ' ' -f 1)" \
        --argjson bytes "$(stat -c %s "$path")" --argjson needed "$needed" \
        '. + [{name: $name, sha256: $sha256, bytes: $bytes, needed: $needed}]')
done

checks=$(jq -R . "$SRC/checks.txt" | jq -s .)
component=$( (cd "$SRC" && sha256sum archives.txt sources.sha256 checks.txt platform.patch \
    *.sh *.py native/* test/*) | sha256sum | cut -d ' ' -f 1)
jq -n --arg component "$component" --argjson files "$files" --argjson checks "$checks" \
    '{component: $component, tag: "android-10.0.0_r47", gate: "P2-private-binder",
      sourceBuilt: true, completeG2: false, files: $files, requiredChecks: $checks}' \
    > "$PREPARED/assets/binder-inputs.json"
printf 'Prepared source-built Binder probe inputs: %s\n' "$PREPARED"
