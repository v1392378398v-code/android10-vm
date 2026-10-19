#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/artifacts/container/framework"
SDK=${ANDROID_HOME:-"$HOME/Android/Sdk"}
# Deleted compatibility classes must not survive javac's incremental output.
rm -rf "$DEST/classes"
mkdir -p "$DEST/classes" "$DEST/dex"
javac --release 8 -cp "$SDK/platforms/android-35/android.jar" -d "$DEST/classes" \
    "$ROOT/guest-runtime/check/ProcessEvidence.java" \
    "$ROOT/guest-runtime/check/FrameworkServer.java" "$ROOT/guest-runtime/check/FrameworkClient.java" \
    "$ROOT/guest-runtime/check/DesktopCheck.java" "$ROOT/guest-runtime/check/DesktopHome.java" "$ROOT/guest-runtime/check/PropertyCheck.java" \
    "$ROOT/guest-runtime/check/DesktopBoot.java" "$ROOT/guest-runtime/check/DesktopInput.java" \
    "$ROOT/guest-runtime/check/DesktopTaskCheck.java" \
    "$ROOT/guest-runtime/check/DisplayModeCheck.java" "$ROOT/guest-runtime/check/CameraQueryCheck.java" \
    "$ROOT/guest-runtime/check/GuestCameraCheck.java" \
    "$ROOT/guest-runtime/check/GuestDisplayState.java" \
    "$ROOT/guest-runtime/check/FlattenedApex.java" "$ROOT/guest-runtime/check/DesktopProcesses.java" \
    "$ROOT/guest-runtime/check/AppLaunch.java" "$ROOT/guest-runtime/check/GuestApplication.java" \
    "$ROOT/guest-runtime/check/BootNativeLibraries.java" \
    "$ROOT/guest-runtime/check/OemBootJniCheck.java" \
    "$ROOT/guest-runtime/check/MediaResetCheck.java" \
    "$ROOT/guest-runtime/check/GuestWebViewProviders.java" \
    "$ROOT/guest-runtime/check/GuestHardwareApplications.java" \
    "$ROOT/guest-runtime/check/GuestCredentialCapabilities.java" \
    "$ROOT/guest-runtime/check/GuestCredentialCheck.java" \
    "$ROOT/guest-runtime/check/GuestMtdStorageCheck.java" \
    "$ROOT/guest-runtime/check/GuestFindDeviceCheck.java" \
    "$ROOT/guest-runtime/check/GuestAccountCapabilityCheck.java" \
    "$ROOT/guest-runtime/check/GuestTap.java" \
    "$ROOT/guest-runtime/check/ApplicationCodePathsCheck.java" \
    "$ROOT/guest-runtime/check/GuestPackageQueryCheck.java" \
    "$ROOT/guest-runtime/check/PackageQueryClient.java" \
    "$ROOT/guest-runtime/check/PackageQueryClientCheck.java" \
    "$ROOT/guest-runtime/framework-adapters/PackageCodePaths.java" \
    "$ROOT/guest-runtime/framework-adapters/PackageQueryReplies.java" \
    "$ROOT/guest-runtime/check/AppRuntimeOptions.java" "$ROOT/guest-runtime/check/AppDexCache.java" \
    "$ROOT/guest-runtime/check/AppDexCacheCheck.java" \
    "$ROOT/guest-runtime/check/ProcessLaunchCheck.java" \
    "$ROOT/guest-runtime/check/SystemToolsCheck.java" \
    "$ROOT/guest-runtime/check/BootImageCheck.java" \
    "$ROOT/guest-runtime/check/GuestChildZygote.java" "$ROOT/guest-runtime/check/GuestWebView.java" \
    "$ROOT/guest-runtime/check/FontCheck.java" \
    "$ROOT/guest-runtime/check/JitCheck.java" \
    "$ROOT/guest-runtime/check/JitStartupCheck.java" \
    "$ROOT/guest-runtime/check/GuestCommand.java" \
    "$ROOT/guest-runtime/check/GuestInstall.java" \
    "$ROOT/guest-runtime/check/GuestDownloadCheck.java" \
    "$ROOT/guest-runtime/check/GuestServiceApiCheck.java" \
    "$ROOT/guest-runtime/check/GuestKeyStoreCheck.java" \
    "$ROOT/guest-runtime/check/GuestMediaScan.java" \
    "$ROOT/guest-runtime/check/MediaCheck.java" \
    "$ROOT/guest-runtime/check/LocalGuestService.java" "$ROOT/guest-runtime/check/PrivateVolumes.java" \
    "$ROOT/guest-runtime/check/PrivateKeyStore.java" \
    "$ROOT/guest-runtime/check/GuestMemory.java" \
    "$ROOT/guest-runtime/check/GuestScheduling.java" "$ROOT/guest-runtime/check/SchedulingCheck.java" \
    "$ROOT/guest-runtime/check/GuestNetworks.java" "$ROOT/guest-runtime/check/GuestCapabilities.java" \
    "$ROOT/guest-runtime/check/GuestOemNetd.java" \
    "$ROOT/guest-runtime/check/GuestConnectivity.java" \
    "$ROOT/guest-runtime/check/GuestDnsResolver.java" \
    "$ROOT/guest-runtime/check/GuestWifi.java" \
    "$ROOT/guest-runtime/check/GuestWifiChannel.java" \
    "$ROOT/guest-runtime/check/NetworkCheck.java" \
    "$ROOT/guest-runtime/check/WifiDeveloperCheck.java" \
    "$ROOT/guest-runtime/check/CoroutineContextCheck.java" \
    "$ROOT/guest-runtime/check/DeviceCheck.java" \
    "$ROOT/guest-runtime/check/GuestSetup.java" \
    "$ROOT/guest-runtime/check/GuestInputMethods.java" \
    "$ROOT/guest-runtime/check/GuestStorageCheck.java" \
    "$ROOT/guest-runtime/check/EglConfigCheck.java" \
    "$ROOT/guest-runtime/check/GuestDiscovery.java"
bash "$SDK/build-tools/35.0.0/d8" --min-api 29 --lib "$SDK/platforms/android-35/android.jar" \
    --output "$DEST/dex" "$DEST/classes/io/a10vm/guest/"*.class \
    "$DEST/classes/io/a10vm/framework/"*.class
