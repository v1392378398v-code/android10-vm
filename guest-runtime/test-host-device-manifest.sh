#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST=$(mktemp -d "${TMPDIR:-$HOME}/host-device-manifest.XXXXXX")
trap 'rm -rf "$DEST"' EXIT HUP INT TERM
javac --release 8 -d "$DEST" \
    "$ROOT/guest-runtime/src/main/java/io/a10vm/guestruntime/HostDeviceManifest.java" \
    "$ROOT/guest-runtime/test/HostDeviceManifestTest.java"
java -cp "$DEST" io.a10vm.guestruntime.HostDeviceManifestTest \
    "$ROOT/guest-runtime/native/host-devices.xml" "$DEST/manifest.xml"
