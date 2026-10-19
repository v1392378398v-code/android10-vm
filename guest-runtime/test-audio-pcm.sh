#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/artifacts/container/audio"
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT/bin"
set -- "$ROOT/guest-runtime/native/HostAudioHal.cpp" "$ROOT/guest-runtime/native/HostAudioPcm.cpp"
clang++ -std=c++17 -O2 -pthread \
    -I"$ROOT/artifacts/container/graphics/upstream/hardware/include" \
    -I"$ROOT/artifacts/container/runtime/upstream/system/core/libcutils/include" \
    -I"$ROOT/artifacts/container/runtime/upstream/system/core/libsystem/include" \
    -I"$OUT/include" "$@" "$ROOT/guest-runtime/test/HostAudioPcmCheck.cpp" \
    -o "$OUT/bin/host-audio-pcm-check"
"$OUT/bin/host-audio-pcm-check"
