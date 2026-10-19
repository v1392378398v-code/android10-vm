#!/bin/sh
set -eu
unset LD_LIBRARY_PATH LD_PRELOAD
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ "$#" -ne 2 ]; then
    printf 'Usage: sh tools/try-android10-ota.sh ROM_ZIP NEW_OUTPUT_DIRECTORY\n' >&2
    exit 2
fi
SDK=${ANDROID_HOME:-/data/data/com.termux/files/home/Android/Sdk}
python3 tools/import-android-ota.py "$1" "$2"
OUT=$(CDPATH= cd -- "$2" && pwd)
FS="$ROOT/.tools/fs/data/data/com.termux/files/usr/bin/debugfs"
mkdir "$OUT/extracted"
"$FS" -R "rdump / \"$OUT/extracted\"" "$OUT/system.raw" > "$OUT/system-extract.log" 2>&1
"$FS" -R "rdump / \"$OUT/extracted/vendor\"" "$OUT/vendor.raw" > "$OUT/vendor-extract.log" 2>&1
DEXLIB=${A10VM_DEXLIB_JAR:-/data/data/com.termux/files/usr/share/java/jadx-1.5.6-all.jar}
mkdir -p "$OUT/wifi-relay/classes"
javac --release 8 -cp "$DEXLIB" -d "$OUT/wifi-relay/classes" guest-runtime/build-tools/PatchWifiRelay.java
java -cp "$OUT/wifi-relay/classes:$DEXLIB" PatchWifiRelay \
    "$OUT/extracted/system/framework/services.jar" "$OUT/wifi-relay/services.jar"
sh "$ROOT/guest-runtime/build-rom-services.sh"
python3 tools/rom_runtime_profile.py "$OUT/extracted" "$OUT/prepared" --services-override "$OUT/wifi-relay/services.jar"
mkdir -p "$OUT/bootstrap/classes" "$OUT/bootstrap/dex"
javac --release 8 -cp "$SDK/platforms/android-35/android.jar:$ROOT/artifacts/container/framework/classes" -d "$OUT/bootstrap/classes" \
    tools/fixtures/rom/RomBootstrap.java tools/fixtures/rom/RomDesktopCheck.java \
    tools/fixtures/rom/RomHardwareCheck.java guest-runtime/check/GuestSetup.java \
    guest-runtime/check/GuestNetworks.java guest-runtime/check/GuestOemNetd.java guest-runtime/check/LocalGuestService.java \
    guest-runtime/check/AppLaunch.java guest-runtime/check/GuestConnectivity.java \
    guest-runtime/check/GuestWifi.java guest-runtime/check/GuestWifiChannel.java
bash "$SDK/build-tools/35.0.0/d8" --min-api 29 --lib "$SDK/platforms/android-35/android.jar" \
    --output "$OUT/bootstrap/dex" "$OUT/bootstrap/classes/io/a10vm/guest/"*.class
JNI=
if [ -f "$OUT/extracted/system/framework/QPerformance.jar" ] && \
   [ -f "$OUT/extracted/system/lib64/libqti_performance.so" ]; then JNI=qti_performance; fi
python3 tools/try-android-rom.py "$OUT/prepared" "$OUT/desktop-trial" --phase desktop \
    --seconds 60 --boot-jni "$JNI" --bootstrap "$OUT/bootstrap/dex/classes.dex"
