#!/usr/bin/env python3
"""Stage verified guest ART, source Bionic and private runtime data for the APK."""
import hashlib
import json
from pathlib import Path
import shutil
from property_bundle import merge as merge_properties
from system_image import canonical_parent

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "guest-runtime/build/prepared"
ART = ROOT / "artifacts/container/art"
FRAMEWORK = ROOT / "artifacts/container/framework"
DESKTOP = ROOT / "artifacts/container/desktop"
SYSTEM = ROOT / "artifacts/container/system-image"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    inputs = json.loads((ART / "inputs.json").read_text())
    framework = json.loads((FRAMEWORK / "inputs.json").read_text())
    desktop = json.loads((DESKTOP / "inputs.json").read_text())
    system = json.loads((SYSTEM / "inputs.json").read_text())
    assert framework["sourceImageSha256"] == inputs["sourceImageSha256"]
    assert desktop["sourceImageSha256"] == inputs["sourceImageSha256"]
    assert system["sourceImageSha256"] == inputs["sourceImageSha256"]
    assert OUT.parent.name == "build" and not OUT.is_symlink()
    if OUT.exists():
        shutil.rmtree(OUT)
    files, data = [], []

    def stage(source, name, kind, logical=None, guest_path=None, library_name=None, mode=None, install_path=None):
        folder = "jniLibs/arm64-v8a" if kind == "files" else "assets"
        destination = OUT / folder / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if kind == "files":
            with destination.open("rb") as stream:
                header = stream.read(20)
            assert header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\xb7\x00", \
                "Expected ARM64 runtime input: " + name
            destination.chmod(0o755)
        entry = {"name": name, "bytes": destination.stat().st_size, "sha256": digest(destination)}
        if logical:
            entry["logical"] = logical
        if guest_path:
            entry["guestPath"] = guest_path
        if library_name is not None:
            entry["libraryName"] = library_name
        if mode is not None:
            entry["mode"] = mode & 0o777
        if install_path:
            entry["installPath"] = install_path
        (files if kind == "files" else data).append(entry)

    programs = {"dalvikvm64": "liba10vm-dalvikvm.so", "ld-android.so": "liba10vm-source-linker.so",
                "app_process64": "liba10vm-app-process.so", "binder-broker": "liba10vm-binder-broker.so",
                "binder-registry": "liba10vm-binder-registry.so", "servicemanager": "liba10vm-servicemanager.so",
                "property-service": "liba10vm-property-service.so"}
    programs["hwservicemanager"] = "liba10vm-hwservicemanager.so"
    programs["system-suspend"] = "liba10vm-system-suspend.so"
    programs["surfaceflinger"] = "liba10vm-surfaceflinger.so"
    programs["graphics-composer"] = "liba10vm-graphics-composer.so"
    programs["graphics-allocator"] = "liba10vm-graphics-allocator.so"
    programs["graphics-configstore"] = "liba10vm-graphics-configstore.so"
    programs["installd"] = "liba10vm-installd.so"
    programs["desktop-gpu-host"] = "liba10vm-desktop-gpu-host.so"
    programs["health"] = "liba10vm-health.so"
    programs["idmap2d"] = "liba10vm-idmap2d.so"
    programs["idmap2"] = "liba10vm-idmap2.so"
    programs["audioserver"] = "liba10vm-audioserver.so"
    programs["audio-hal"] = "liba10vm-audio-hal.so"
    programs["host-devices"] = "liba10vm-host-devices.so"
    for role in ("media", "media-extractor", "media-metrics", "media-drm", "drm", "media-omx", "media-codec"):
        programs[role] = "liba10vm-" + role + ".so"
    native, assets = {}, {}
    aliases = {item["path"].removeprefix("rootfs"): item["target"] for item in system["symlinks"]}
    for entry in inputs["files"] + framework["files"] + desktop["files"]:
        logical = entry.get("logical", entry.get("name", ""))
        if logical in programs or logical.endswith(".so"):
            native[logical] = entry
        else:
            guest = canonical_parent("/" + entry["path"].split("/rootfs/", 1)[1], aliases)
            assets[guest.lstrip("/")] = entry
    for entry in system["files"]:
        if entry.get("imageNative"):
            native[entry["name"]] = entry
        else:
            guest = canonical_parent("/" + entry["path"].split("/rootfs/", 1)[1], aliases)
            assets.setdefault(guest.lstrip("/"), entry)
    for logical, entry in native.items():
        source = ROOT / entry["path"]
        assert source.stat().st_size == entry["bytes"] and digest(source) == entry["sha256"], entry
        name = ("liba10vm-image-" + hashlib.sha256(logical.encode()).hexdigest()[:20] + ".so"
                if entry.get("imageNative") else programs.get(logical,
                "liba10vm-guest-" + logical.replace("/", "-").replace("@", "_")))
        library = entry.get("libraryName", "") if entry.get("imageNative") else (
            logical if logical.endswith(".so") else "")
        stage(source, name, "files", logical, entry.get("guestPath"), library)
    for guest, entry in assets.items():
        source = ROOT / entry["path"]
        assert source.stat().st_size == entry["bytes"] and digest(source) == entry["sha256"], entry
        # .bc forces a 32-bit install; aapt expands .gz assets and strips their suffix.
        encoded = guest.endswith((".bc", ".gz"))
        asset = "guest-runtime/rootfs/" + guest + (".asset" if encoded else "")
        stage(source, asset, "data", mode=entry.get("mode"),
              install_path="rootfs/" + guest if encoded else None)
    stage(ART / "bin/seed-properties", "liba10vm-seed-properties.so", "files", "seed-properties")
    stage(ART / "dex/classes.dex", "guest-runtime/runtime-check.dex", "data")
    stage(FRAMEWORK / "dex/classes.dex", "guest-runtime/framework-check.dex", "data")
    catalog = OUT / "system-image-paths.json"
    catalog.write_text(json.dumps([{"path": item["path"]} for item in system["inventory"]]) + "\n", encoding="utf-8")
    stage(catalog, "guest-runtime/system-image-paths.json", "data")
    properties = merge_properties(DESKTOP / "rootfs", desktop["propertyFiles"],
                                 ROOT / "guest-runtime/native/guest.prop")
    seed = OUT / "guest.prop"
    seed.write_text("".join(name + "=" + value + "\n" for name, value in sorted(properties.items())), encoding="utf-8")
    stage(seed, "guest-runtime/guest.prop", "data")
    assert len({entry["name"] for entry in files}) == len(files)
    assert len({entry["name"] for entry in data}) == len(data)
    symlinks = {item["path"]: item for item in system["symlinks"]}
    for item in desktop.get("nativePackageLinks", []) + desktop.get("propertyLinks", []):
        symlinks["rootfs" + item["path"]] = {"path": "rootfs" + item["path"], "target": item["target"]}
    manifest = {"guestSdk": 29, "loaderFromSource": True, "rootRequired": False,
                "artIntegrated": True, "desktopImplemented": desktop["desktopImplemented"],
                "frameworkIntegrated": True, "bootClassPath": framework["bootClassPath"],
                "registryLibraries": framework["registryLibraries"],
                "systemServerClassPath": desktop["systemServerClassPath"],
                "desktopPackages": desktop["packages"],
                "allSystemPackages": desktop.get("allSystemPackages", False),
                "systemApkCount": desktop.get("systemApkCount", len(desktop["packages"])),
                "propertyFiles": desktop["propertyFiles"], "propertyCount": len(properties),
                "symlinks": list(symlinks.values()), "links": system["links"],
                "nativeLinks": system["nativeLinks"],
                "systemImagePaths": len(system["inventory"]),
                "mutableDataPreserved": system["mutableDataPreserved"],
                "initialDirectories": ["apex", "system/bin", "dev/input", "data/local/tmp", "data/dalvik-cache/arm64",
                    "data/anr", "data/tombstones", "data/dalvik-cache",
                    "data/misc/user", "data/misc/profiles/cur", "data/misc/profiles/ref",
                    "data/misc/shared_relro", "data/misc/media", "data/misc/mediadrm", "data/mediadrm",
                    "data/vendor/mediadrm", "data/mediaserver", "data/drm", "data/misc/audioserver",
                    "data/system", "data/system/users", "data/user", "data/user_de",
                    "data/app", "data/app-lib", "data/app-private", "data/app-ephemeral",
                    "data/app-staging", "mnt/asec", "mnt/expand", "data/user/0", "data/user_de/0",
                    "data/system/users/0", "data/misc/profiles/cur/0"],
                "sourceImageSha256": inputs["sourceImageSha256"], "files": files, "data": data}
    manifest["initialDirectories"] = sorted(set(manifest["initialDirectories"] + system["directories"]))
    (OUT / "assets/guest-runtime-inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    from package_queries_bundle import stage_package_queries
    stage_package_queries(OUT)
    if (ROOT / "artifacts/container/camera/bin/camera-provider").is_file():
        from camera_bundle import stage_camera
        stage_camera(OUT)
    from keyboard_bundle import stage_keyboard
    stage_keyboard(OUT)
    print(json.dumps({"nativeFiles": len(files), "dataFiles": len(data), "path": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
