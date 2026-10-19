#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
unset LD_LIBRARY_PATH LD_PRELOAD
for tool in clang++ jq readelf sha256sum; do command -v "$tool" >/dev/null; done
if [ "$#" -eq 2 ]; then sh container-probe/prepare.sh "$1" "$2";
elif [ "$#" -ne 0 ]; then printf 'Usage: sh tools/prepare-native-display.sh [RAW_IMAGE G0_REPORT]\n' >&2; exit 2; fi
BASE="$ROOT/container-probe/build/prepared"
test -f "$BASE/assets/inputs.json"
sh container-probe/graphics/build-native.sh
"$ROOT/artifacts/container/graphics/bin/touch-test"
sh container-probe/graphics/stage-apk.sh
sh guest-runtime/build-native.sh
python3 guest-runtime/prepare.py
sh guest-runtime/build-framework.sh
python3 guest-runtime/prepare-framework.py
sh container-probe/graphics/build-desktop.sh
sh guest-runtime/build-network.sh
sh guest-runtime/build-audio.sh
sh guest-runtime/build-media.sh
sh guest-runtime/build-host-devices.sh
sh guest-runtime/build-camera.sh
python3 guest-runtime/prepare-desktop.py
python3 guest-runtime/stage.py
sh tools/stage-native-display.sh
