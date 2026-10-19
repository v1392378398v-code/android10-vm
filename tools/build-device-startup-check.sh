#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SDK=${ANDROID_HOME:-"$HOME/Android/Sdk"}
OUT="$ROOT/artifacts/device-compat/startup-check"
SRC="$ROOT/tools/fixtures/device-startup"
ANDROID_USER_DIR=${ANDROID_USER_HOME:-"${XDG_CONFIG_HOME:-"$HOME/.config"}/.android"}
KEYSTORE=${A10VM_DEBUG_KEYSTORE:-"$ANDROID_USER_DIR/debug.keystore"}
unset LD_LIBRARY_PATH LD_PRELOAD
mkdir -p "$OUT/classes" "$OUT/dex"
javac --release 8 -cp "$SDK/platforms/android-35/android.jar" -d "$OUT/classes" "$SRC/StartupCheck.java"
bash "$SDK/build-tools/35.0.0/d8" --min-api 30 --output "$OUT/dex" "$OUT/classes/io/a10vm/devicecheck/StartupCheck.class"
aapt2 link -I "$SDK/platforms/android-35/android.jar" --manifest "$SRC/AndroidManifest.xml" -o "$OUT/base.apk"
(cd "$OUT/dex" && zip -q -u "$OUT/base.apk" classes.dex)
zipalign -f 4 "$OUT/base.apk" "$OUT/aligned.apk"
apksigner sign --ks "$KEYSTORE" \
    --ks-pass pass:android --key-pass pass:android --out "$OUT/check.apk" "$OUT/aligned.apk"
