#!/bin/sh
# Static intake only: no guest executable is run and no filesystem is mounted.
set -eu
if [ "$#" -ne 2 ]; then
    printf 'Usage: sh guest-runtime/audit-inputs.sh RAW_IMAGE NEW_OUTPUT_DIR\n' >&2
    exit 2
fi
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")
OUT=$2
FS="$ROOT/.tools/fs/data/data/com.termux/files/usr"
unset LD_LIBRARY_PATH LD_PRELOAD
for tool in file readelf sha256sum jq; do command -v "$tool" >/dev/null; done
test -f "$BASE"
test -x "$FS/bin/debugfs"
if [ -e "$OUT" ]; then
    printf 'Choose a new output directory; existing evidence is preserved.\n' >&2
    exit 2
fi
mkdir -p "$OUT"
OUT=$(CDPATH= cd -- "$OUT" && pwd)
SOURCE_SHA=$(sha256sum "$BASE" | cut -d ' ' -f 1)

dump() {
    LD_LIBRARY_PATH="$FS/lib:/data/data/com.termux/files/usr/lib" \
        "$FS/bin/debugfs" -R "dump $1 \"$OUT/$2\"" "$BASE" >> "$OUT/extraction.log" 2>&1
    test -s "$OUT/$2"
    chmod 444 "$OUT/$2"
}

elf() {
    label=$1
    path=$2
    dump "$path" "$label"
    readelf -h -l -d -n -Ws "$OUT/$label" > "$OUT/$label.elf.txt"
    SHA=$(sha256sum "$OUT/$label" | cut -d ' ' -f 1)
    TYPE=$(file -b "$OUT/$label")
    INTERP=$(sed -n 's/.*Requesting program interpreter: \(.*\)]/\1/p' "$OUT/$label.elf.txt")
    sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' "$OUT/$label.elf.txt" | \
        jq -Rs 'split("\n") | map(select(length > 0))' > "$OUT/$label.needed.json"
    jq -n --arg file "$label" --arg source "$path" --arg sha256 "$SHA" \
        --arg format "$TYPE" --arg interpreter "$INTERP" \
        --argjson bytes "$(stat -c %s "$OUT/$label")" --slurpfile needed "$OUT/$label.needed.json" \
        '{file: $file, guestPath: $source, bytes: $bytes, sha256: $sha256,
          format: $format, interpreter: $interpreter, needed: $needed[0]}' >> "$OUT/elfs.jsonl"
}

dump /system/build.prop build.prop
SDK=$(sed -n 's/^ro.build.version.sdk=//p' "$OUT/build.prop")
RELEASE=$(sed -n 's/^ro.build.version.release=//p' "$OUT/build.prop")
test "$SDK" = 29
test "$RELEASE" = 10
elf init /system/bin/init
elf servicemanager /system/bin/servicemanager
elf app_process64 /system/bin/app_process64
elf surfaceflinger /system/bin/surfaceflinger
elf bootstrap-linker64 /system/bin/bootstrap/linker64
elf apex-linker64 /system/apex/com.android.runtime.debug/bin/linker64
test "$(sha256sum "$BASE" | cut -d ' ' -f 1)" = "$SOURCE_SHA"
jq -n --arg image "$BASE" --arg sha256 "$SOURCE_SHA" --arg release "$RELEASE" \
    --argjson sdk "$SDK" --slurpfile files "$OUT/elfs.jsonl" \
    '{gate: "G0-static-input-inventory", inputsVerified: true, runtimeTested: false,
      sourceImage: $image, sourceSha256: $sha256, sourceUnchanged: true,
      declaredGuestSdk: $sdk, declaredGuestRelease: $release, files: $files}' > "$OUT/report.json"
printf 'Static Android 10 input report: %s/report.json\n' "$OUT"
printf 'Runtime container startup, isolated services, graphics and input remain separate gates.\n'
