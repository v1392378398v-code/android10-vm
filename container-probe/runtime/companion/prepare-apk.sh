#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
SRC="$ROOT/container-probe/runtime/companion"
OUT="$ROOT/artifacts/container/runtime"
PREPARED="$ROOT/container-probe/build/prepared"
sh "$ROOT/container-probe/runtime/dynamic/prepare-apk.sh" "$@"
sh "$SRC/build-libraries.sh"
sh "$SRC/build-probes.sh"
component=$( (cd "$SRC" && sha256sum archives.txt sources.sha256 checks.txt platform.patch *.sh *.py test/*) | \
    sha256sum | cut -d ' ' -f 1)
files='[]'
while read -r path name; do
    input="$OUT/$path"
    cp "$input" "$PREPARED/jniLibs/arm64-v8a/$name"
    needed=$(llvm-readelf -d "$input" | sed -n 's/.*Shared library: \[\(.*\)\].*/\1/p' | jq -R . | jq -s .)
    files=$(printf '%s' "$files" | jq --arg name "$name" \
        --arg sha256 "$(sha256sum "$input" | cut -d ' ' -f 1)" \
        --argjson bytes "$(stat -c %s "$input")" --argjson needed "$needed" \
        '. + [{name: $name, sha256: $sha256, bytes: $bytes, needed: $needed}]')
done <<'INPUTS'
bin/companion-probe liba10vm-p2-companion.so
lib/libm.so liba10vm-source-libm.so
lib/libc++.so liba10vm-source-libcxx.so
lib/libunwind.so liba10vm-source-libunwind.so
lib/liba10vm-exceptions.so liba10vm-exceptions.so
lib/liba10vm-late-test.so liba10vm-late-test.so
INPUTS
checks=$(jq -R . "$SRC/checks.txt" | jq -s .)
jq -n --arg component "$component" --argjson files "$files" --argjson checks "$checks" \
    '{component: $component, tag: "android-10.0.0_r47", librariesFromSource: true,
      aarch64LlvmUnwindAdaptation: true, binary128SincoslCorrection: true,
      completeG1: false, libcppVersion: 8000,
      requiredChecks: $checks, files: $files}' > "$PREPARED/assets/companion-inputs.json"
printf 'Prepared source-built companion runtime inputs: %s\n' "$PREPARED"
