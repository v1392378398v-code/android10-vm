#!/usr/bin/env python3
"""Stage the original Android 10 system server and desktop packages."""
import json
import os
from pathlib import Path
import re
import subprocess
import shutil

from prepare import APEX, DEBUGFS, IMAGE, REPORT, ROOT, digest, extract, needed
from system_packages import SystemPackages
from media_bundle import PROGRAMS as MEDIA_PROGRAMS, resources as media_resources
from media_seccomp import policies as media_policies
from property_bundle import restore as restore_properties
from system_image import prepare as prepare_system_image

OUT = ROOT / "artifacts/container/desktop"
FRAMEWORK = ROOT / "artifacts/container/framework"
GRAPHICS = ROOT / "artifacts/container/graphics/desktop"
MEDIA = ROOT / "artifacts/container/media"


def main():
    report = json.loads(REPORT.read_text())
    framework = json.loads((FRAMEWORK / "inputs.json").read_text())
    assert report["inputsVerified"] and report["sourceUnchanged"]
    assert digest(IMAGE) == report["sourceSha256"] == framework["sourceImageSha256"]
    entries = []
    inventory = SystemPackages(DEBUGFS, IMAGE)
    system_packages, app_libraries, package_links = inventory.inventory()
    property_files = restore_properties(inventory, OUT / "rootfs")
    media_paths, media_libraries = media_resources(inventory)
    policy_sources = media_policies()
    media_paths.extend(policy_sources)
    device_manifest = "/vendor/etc/vintf/manifest/a10vm-host-devices.xml"
    local_sources = {device_manifest: ROOT / "guest-runtime/native/host-devices.xml",
                     "/vendor/etc/vintf/manifest/a10vm-media-codec.xml": ROOT / "guest-runtime/native/media-codec.xml",
                     "/vendor/etc/vintf/manifest/android.hardware.sensors@2.0.xml": ROOT / "guest-runtime/native/image-sensors.xml",
                     "/vendor/etc/vintf/manifest/android.hardware.gnss@2.0-service.xml": ROOT / "guest-runtime/native/image-gnss.xml"}

    def record(source, path, logical=None, guest_path=None):
        entry = {"source": source, "path": str(path.relative_to(ROOT)),
                 "bytes": path.stat().st_size, "sha256": digest(path)}
        if logical:
            entry["name"] = logical
        if guest_path:
            entry["guestPath"] = guest_path
        entries.append(entry)

    available = {item["name"] for item in framework["files"] if "name" in item}
    devices = ROOT / "artifacts/container/host-devices/bin/host-devices"
    assert devices.is_file(), devices
    record("android10-host-devices-bridge", devices, "host-devices")
    network = ROOT / "artifacts/container/network/lib"
    shutil.copyfile(FRAMEWORK / "lib/libnetd_client.so", network / "liba10vm-host-netd-client.so")
    for name in ("libnetd_client.so", "liba10vm-host-netd-client.so"):
        record("android10-host-network-bridge", network / name, name)
        available.add(name)
    audio = ROOT / "artifacts/container/audio/lib/audio.primary.a10vm.so"
    record("a10vm-host-pcm-hal", audio, audio.name, "/vendor/lib64/hw/" + audio.name)
    available.add(audio.name)
    dex_cache = ROOT / "artifacts/container/dex-cache/lib/libdexfile.so"
    assert dex_cache.is_file(), "Run sh guest-runtime/build-dex-cache.sh first"
    record("android10-verified-dex-archive-cache", dex_cache, "libdexfile.so")
    available.add("libdexfile.so")
    pending = ["libandroid_servers.so", "libaudiopolicyenginedefault.so", "libsoundpool.so",
               "libwebviewchromium_loader.so", *app_libraries, *media_libraries]
    pending.extend(needed(devices))
    pending.extend(needed(dex_cache))
    for name in ("libresourcemanagerservice.so", "libstagefright_httplive.so", "libmediaplayerservice.so"):
        path = MEDIA / "lib" / name
        assert path.is_file(), path
        record("android10-arm64-media-source", path, name)
        available.add(name)
        pending.extend(needed(path))
    programs = {"system-suspend": "/system/bin/hw/android.system.suspend@1.0-service",
                "surfaceflinger": "/system/bin/surfaceflinger",
                "graphics-composer": "/vendor/bin/hw/android.hardware.graphics.composer@2.1-service",
                "graphics-allocator": "/vendor/bin/hw/android.hardware.graphics.allocator@2.0-service",
                "installd": "/system/bin/installd"}
    programs["graphics-configstore"] = "/vendor/bin/hw/android.hardware.configstore@1.1-service"
    programs["health"] = "/vendor/bin/hw/android.hardware.health@2.0-service.goldfish"
    programs["idmap2d"] = "/system/bin/idmap2d"
    programs["idmap2"] = "/system/bin/idmap2"
    programs["audioserver"] = "/system/bin/audioserver"
    programs["audio-hal"] = "/vendor/bin/hw/android.hardware.audio@2.0-service"
    programs.update(MEDIA_PROGRAMS)
    for name, source in programs.items():
        path = OUT / "bin" / name
        rebuilt = MEDIA / "bin" / name
        if name in ("media", "media-drm", "drm", "media-omx"):
            assert rebuilt.is_file(), rebuilt
            shutil.copyfile(rebuilt, path)
            source = "android10-arm64-media-source"
        else:
            assert extract(source, path), source
        path.chmod(0o755)
        record(source, path, name)
        pending.extend(needed(path))
    for name in ("android.hardware.graphics.composer@2.1-impl.so",
                 "android.hardware.graphics.allocator@2.0-impl.so",
                 "android.hardware.graphics.mapper@2.0-impl-2.1.so",
                 "android.hardware.audio@4.0-impl.so", "android.hardware.audio.effect@4.0-impl.so",
                 "audio.primary.default.so", "audio.r_submix.default.so"):
        source = "/vendor/lib64/hw/" + name
        path = OUT / "lib" / name
        assert extract(source, path), source
        record(source, path, name, source)
        available.add(name)
        pending.extend(needed(path))
    for path in sorted((GRAPHICS / "lib").glob("*.so")):
        guest = "/vendor/lib64/egl/" + path.name if path.name.endswith("_emulation.so") else \
                "/vendor/lib64/hw/" + path.name if path.name in ("gralloc.ranchu.so", "hwcomposer.ranchu.so") else None
        record("paired-android10-graphics-source", path, path.name, guest)
        available.add(path.name)
    host = GRAPHICS / "bin/desktop-gpu-host"
    assert host.is_file()
    record("paired-android10-graphics-source", host, "desktop-gpu-host")
    while pending:
        name = pending.pop(0)
        if name in available:
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.+@-]+", name), name
        path = OUT / "lib" / name
        candidates = [app_libraries[name]] if name in app_libraries else [media_libraries[name]] if name in media_libraries else [directory + "/" + name for directory in (
            APEX + "/lib64", "/system/lib64", "/system/lib64/vndk-29", "/system/lib64/vndk-sp-29",
            "/system/product/lib64", "/vendor/lib64", "/system/apex/com.android.media/lib64",
            "/system/apex/com.android.media.swcodec/lib64")]
        for source in candidates:
            if extract(source, path):
                break
        else:
            raise RuntimeError("Missing system server dependency: " + name)
        record(source, path, name, source if name in media_libraries else None)
        available.add(name)
        pending.extend(needed(path))

    environ = (FRAMEWORK / "rootfs/init.environ.rc").read_text()
    classpath = re.search(r"^\s+export SYSTEMSERVERCLASSPATH (.+)$", environ, re.M).group(1).split(":")
    packages = {
        "framework": "/system/framework/framework-res.apk",
        "launcher": "/system/product/priv-app/Launcher3QuickStep/Launcher3QuickStep.apk",
        "systemui": "/system/product/priv-app/SystemUI/SystemUI.apk",
        "settingsProvider": "/system/priv-app/SettingsProvider/SettingsProvider.apk",
        "settings": "/system/product/priv-app/Settings/Settings.apk",
        "permissionController": "/system/priv-app/PermissionController/PermissionController.apk",
        "packageInstaller": "/system/priv-app/PackageInstaller/PackageInstaller.apk",
        "shell": "/system/priv-app/Shell/Shell.apk",
        "extServices": "/system/priv-app/ExtServices/ExtServices.apk",
        "extShared": "/system/app/ExtShared/ExtShared.apk",
        # LocationManagerService refuses to start without a platform-signed fused provider.
        "fusedLocation": "/system/priv-app/FusedLocation/FusedLocation.apk",
        "gallery": "/system/product/app/Gallery2/Gallery2.apk",
        "mediaProvider": "/system/priv-app/MediaProvider/MediaProvider.apk",
        "documents": "/system/priv-app/DocumentsUI/DocumentsUI.apk",
        "externalStorageProvider": "/system/priv-app/ExternalStorageProvider/ExternalStorageProvider.apk",
        "downloadProvider": "/system/priv-app/DownloadProvider/DownloadProvider.apk",
        "downloadUi": "/system/priv-app/DownloadProviderUi/DownloadProviderUi.apk",
        "keyboard": "/system/product/app/LatinIME/LatinIME.apk",
    }
    packages.update(system_packages)
    configurations = ["/system/etc/selinux/plat_mac_permissions.xml", "/vendor/etc/selinux/vendor_mac_permissions.xml",
        "/system/usr/keychars/Virtual.kcm", "/system/usr/keychars/Generic.kcm", "/system/usr/keylayout/Generic.kl",
        "/system/apex/com.android.tzdata/etc/tz/tzdata", "/system/apex/com.android.tzdata/etc/tz/tz_version",
        "/system/apex/com.android.tzdata/etc/tz/tzlookup.xml"]
    configurations.append("/system/etc/fonts.xml")
    configurations.extend(("/system/etc/task_profiles.json", "/system/etc/cgroups.json"))
    configurations.append("/system/framework/org.apache.http.legacy.jar")
    configurations.extend(media_paths)
    configurations.extend(local_sources)
    for directory in ("/system/framework", "/system/product/framework", "/vendor/framework"):
        for source, mode in inventory.walk(directory):
            if source.endswith(".jar"):
                configurations.append(source)
    configurations.extend("/vendor/etc/" + name for name in ("audio_policy_configuration.xml",
        "audio_policy_volumes.xml", "default_volume_tables.xml", "primary_audio_policy_configuration.xml",
        "r_submix_audio_policy_configuration.xml", "surround_sound_configuration_5_0.xml", "audio_effects.xml"))
    font_sources = {}
    listing = subprocess.check_output([str(DEBUGFS), "-R", "ls -p /system/fonts", str(IMAGE)],
                                      text=True, stderr=subprocess.DEVNULL)
    for row in listing.splitlines():
        fields = row.split("/")
        if len(fields) > 5 and fields[5].endswith((".ttf", ".ttc", ".otf")):
            source = "/system/fonts/" + fields[5]
            if fields[2].startswith("120"):
                stat = subprocess.check_output([str(DEBUGFS), "-R", "stat " + source, str(IMAGE)],
                                               text=True, stderr=subprocess.DEVNULL)
                target = re.search(r'Fast link dest: "([^"/]+)"', stat)
                assert target, source
                font_sources[source] = "/system/fonts/" + target.group(1)
            else:
                assert fields[2].startswith("100"), source
            configurations.append(source)
    for directory in ("/system/etc/permissions", "/system/etc/sysconfig", "/system/product/etc/permissions",
                      "/system/product/etc/sysconfig", "/vendor/etc/permissions"):
        listing = subprocess.check_output([str(DEBUGFS), "-R", "ls -p " + directory, str(IMAGE)],
                                          text=True, stderr=subprocess.DEVNULL)
        for row in listing.splitlines():
            fields = row.split("/")
            if len(fields) > 5 and fields[5].endswith(".xml"):
                configurations.append(directory + "/" + fields[5])
    for source in dict.fromkeys(classpath + list(packages.values()) + configurations + ["/vendor/etc/vintf/manifest.xml", "/system/etc/vintf/manifest.xml",
            "/system/etc/vintf/manifest/android.system.suspend@1.0-service.xml"] + [
                "/system/apex/" + module + "/apex_manifest.json" for module in (
                    "com.android.runtime.debug", "com.android.conscrypt", "com.android.media", "com.android.tzdata")]):
        path = OUT / "rootfs" / source.removeprefix("/")
        original = font_sources.get(source, source)
        if source in local_sources:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_sources[source], path)
            original = "android10-host-device-vintf:" + source
        elif source in policy_sources:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(policy_sources[source], path)
            original = "android10-arm64-private-media-policy:" + source
        else:
            assert extract(original, path), source
        if source == "/system/framework/services.jar":
            build = ROOT / "artifacts/container/framework/wifi-relay"
            build.mkdir(parents=True, exist_ok=True)
            dexlib = Path(os.environ.get("A10VM_DEXLIB_JAR",
                    "/data/data/com.termux/files/usr/share/java/jadx-1.5.6-all.jar"))
            subprocess.run(["javac", "--release", "8", "-cp", str(dexlib), "-d", str(build),
                    str(ROOT / "guest-runtime/build-tools/PatchWifiRelay.java")], check=True)
            patched = build / "services.jar"
            subprocess.run(["java", "-cp", str(build) + ":" + str(dexlib), "PatchWifiRelay",
                    str(path), str(patched)], check=True)
            shutil.copyfile(patched, path)
            original = "android10-stock-services:host-wifi-relay"
        record(original, path)
    for source in property_files:
        record(source, OUT / "rootfs" / source.lstrip("/"))
    manifest = {"guestSdk": 29, "rootRequired": False, "desktopImplemented": True,
                "systemServerClassPath": classpath, "packages": packages,
                "sourceImageSha256": report["sourceSha256"], "files": entries,
                "allSystemPackages": True, "systemApkCount": len(system_packages),
                "nativePackageLinks": package_links,
                "propertyFiles": property_files,
                "propertyLinks": [{"path": "/default.prop", "target": "system/etc/prop.default"}]}
    (OUT / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    art = json.loads((ROOT / "artifacts/container/art/inputs.json").read_text())
    prepare_system_image(art["files"] + framework["files"] + entries, report["sourceSha256"])
    print(json.dumps({"files": len(entries), "systemApks": len(system_packages),
                      "bytes": sum(item["bytes"] for item in entries),
                      "manifest": str(OUT / "inputs.json")}, indent=2))


if __name__ == "__main__":
    main()
