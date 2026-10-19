#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/artifacts/container/audio/include/system"
BASE=https://android.googlesource.com/platform/system/media/+/refs/tags/android-10.0.0_r47/audio/include/system
mkdir -p "$DEST"
for name in audio.h audio-base.h audio-base-utils.h audio_effect.h audio_effect-base.h; do
    if [ -s "$DEST/$name" ]; then continue; fi
    curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
        "$BASE/$name?format=TEXT" -o "$DEST/$name.b64"
    base64 -d "$DEST/$name.b64" > "$DEST/$name.part"
    test -s "$DEST/$name.part"
    mv "$DEST/$name.part" "$DEST/$name"
    rm "$DEST/$name.b64"
done
(cd "$DEST" && sha256sum --check --status "$ROOT/guest-runtime/audio-headers.sha256")
