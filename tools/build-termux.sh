#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
unset LD_LIBRARY_PATH LD_PRELOAD
export ANDROID_HOME=${ANDROID_HOME:-"$HOME/Android/Sdk"}
export ANDROID_SDK_ROOT="$ANDROID_HOME"
AAPT2=$(command -v aapt2)
exec sh ./gradlew -Pandroid.aapt2FromMavenOverride="$AAPT2" --no-daemon "$@"
