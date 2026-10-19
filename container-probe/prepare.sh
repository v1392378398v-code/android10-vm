#!/bin/sh
set -eu
if [ "$#" -ne 2 ]; then
    printf 'Usage: sh container-probe/prepare.sh RAW_IMAGE G0_REPORT\n' >&2
    exit 2
fi
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")
REPORT=$2
OUT="$ROOT/container-probe/build/prepared"
LIBS="$OUT/jniLibs/arm64-v8a"
FS="$ROOT/.tools/fs/data/data/com.termux/files/usr"
NDK=${ANDROID_NDK_HOME:-"$HOME/Android/Sdk/ndk/29.0.13113456"}
SYSROOT="$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot"
unset LD_LIBRARY_PATH LD_PRELOAD
for tool in clang readelf sha256sum jq; do command -v "$tool" >/dev/null; done
test -x "$FS/bin/debugfs"
test -d "$SYSROOT"
jq -e '.inputsVerified and .sourceUnchanged and .declaredGuestSdk == 29' "$REPORT" >/dev/null
SOURCE_SHA=$(sha256sum "$BASE" | cut -d ' ' -f 1)
test "$SOURCE_SHA" = "$(jq -r .sourceSha256 "$REPORT")"

# Only this script's small, generated inputs are replaced on each run.
if [ -e "$OUT" ]; then
    test -d "$OUT"
    test ! -L "$OUT"
    rm -r -- "$OUT"
fi
mkdir -p "$LIBS" "$OUT/assets"
record() {
    name=$1
    source=$2
    readelf -h "$LIBS/$name" | grep -q 'AArch64'
    SHA=$(sha256sum "$LIBS/$name" | cut -d ' ' -f 1)
    NEEDED=$(readelf -d "$LIBS/$name" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | \
        jq -Rs 'split("\n") | map(select(length > 0))')
    jq -n --arg name "$name" --arg source "$source" --arg sha256 "$SHA" \
        --argjson needed "$NEEDED" --argjson bytes "$(stat -c %s "$LIBS/$name")" \
        '{name: $name, source: $source, sha256: $sha256, bytes: $bytes, needed: $needed}' \
        >> "$OUT/files.jsonl"
}
extract() {
    LD_LIBRARY_PATH="$FS/lib:/data/data/com.termux/files/usr/lib" \
        "$FS/bin/debugfs" -R "dump $1 \"$LIBS/$2\"" "$BASE" >> "$OUT/extraction.log" 2>&1
    test -s "$LIBS/$2"
    chmod 755 "$LIBS/$2"
    record "$2" "$1"
}
APEX=/system/apex/com.android.runtime.debug
extract "$APEX/bin/linker64" liba10vm-a10-linker.so
readelf -d "$LIBS/liba10vm-a10-linker.so" | grep -q 'Library soname: \[ld-android.so\]'
test "$(sha256sum "$LIBS/liba10vm-a10-linker.so" | cut -d ' ' -f 1)" = \
    "$(jq -r '.files[] | select(.file == "apex-linker64") | .sha256' "$REPORT")"
for name in libc libm libdl; do
    extract "$APEX/lib64/bionic/$name.so" "liba10vm-a10-$name.so"
done
UNWIND=
for path in "$NDK"/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/*/lib/linux/aarch64; do
    if test -f "$path/libunwind.a"; then UNWIND=$path; break; fi
done
test -n "$UNWIND"
clang --target=aarch64-linux-android29 --sysroot="$SYSROOT" -L"$UNWIND" \
    -fPIE -pie -O2 -Wall -Wextra -Werror -Wl,-z,max-page-size=4096 -Wl,--build-id=sha1 \
    "$ROOT/container-probe/native/payload.c" -ldl -lm -o "$LIBS/liba10vm-g1-payload.so"
record liba10vm-g1-payload.so container-probe/native/payload.c
if ! jq -s -e '[.[].needed[] | select(. != "libc.so" and . != "libm.so" and . != "libdl.so"
        and . != "ld-android.so")] | length == 0' "$OUT/files.jsonl" >/dev/null; then
    printf 'Unexpected ELF dependency; inspect %s/files.jsonl\n' "$OUT" >&2
    exit 1
fi
test "$(sha256sum "$BASE" | cut -d ' ' -f 1)" = "$SOURCE_SHA"
jq -n --arg sha256 "$SOURCE_SHA" --slurpfile files "$OUT/files.jsonl" \
    '{sourceImageSha256: $sha256, declaredGuestSdk: 29, sourceUnchanged: true,
      loaderFromSource: false, files: $files}' > "$OUT/assets/inputs.json"
printf 'Prepared small G1 stage-0 inputs: %s\n' "$OUT"
du -sh "$OUT"
