#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/artifacts/container/media"
TAG=android-10.0.0_r47
fetch() {
    repository=$1
    directory=$2
    marker=$3
    archive_path=${4:-}
    archive="$DEST/$(printf '%s' "$directory" | tr / -).tar.gz"
    if [ -s "$DEST/upstream/$directory/$marker" ]; then return; fi
    mkdir -p "$DEST/upstream/$directory"
    curl --fail --silent --show-error --retry 1 --connect-timeout 10 --max-time 60 \
        "https://android.googlesource.com/platform/$repository/+archive/refs/tags/$TAG${archive_path:+/$archive_path}.tar.gz" \
        -o "$archive.part"
    tar --warning=no-timestamp -xzf "$archive.part" -C "$DEST/upstream/$directory"
    test -s "$DEST/upstream/$directory/$marker"
    mv "$archive.part" "$archive"
}
fetch frameworks/av frameworks/av media/mediaserver/main_mediaserver.cpp
fetch system/tools/hidl system/tools/hidl main.cpp
fetch system/tools/aidl system/tools/aidl main.cpp
fetch system/libhidl system/libhidl transport/manager/1.0/IServiceManager.hal
fetch hardware/interfaces hardware/interfaces media/omx/1.0/IOmx.hal
fetch frameworks/native frameworks/native libs/gui/include/gui/Surface.h
fetch system/media system/media camera/include/system/camera_metadata.h
fetch system/libfmq system/libfmq include/fmq/MessageQueue.h
fetch external/icu external/icu/libandroidicu include/aicu/AIcu.h libandroidicu
fetch external/boringssl external/boringssl/src/include openssl/ssl.h src/include
fetch system/netd system/netd include/NetdClient.h
fetch system/core system/core/libmemunreachable include/memunreachable/memunreachable.h libmemunreachable
fetch external/selinux external/selinux/libselinux/include selinux/android.h libselinux/include
