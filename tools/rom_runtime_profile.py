"""Stage a ROM's framework and ARM64 libraries with the existing host bridges."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "guest-runtime"))
from property_bundle import SOURCES, merge, parse

BASE = ROOT / "guest-runtime/build/prepared"
BRIDGES = {"ld-android.so", "libc.so", "libdl.so", "libm.so", "libunwind.so", "libselinux.so",
           "libnetd_client.so", "liba10binder.so", "libhwbinder.so", "libhidlbase.so", "libhidltransport.so",
           "libbinderthreadstate.so"}


def rom_property_sources(extracted):
    sources = []
    for source in SOURCES:
        path, pending, links = extracted, list(Path(source).parts[1:]), 0
        while pending:
            name = pending.pop(0)
            if name == "..":
                path = path.parent if path != extracted else extracted
                continue
            candidate = path / name
            if candidate.is_symlink():
                links += 1
                if links > 40:
                    raise ValueError("ROM property symlink loop: " + source)
                target = candidate.readlink()
                if target.is_absolute():
                    path = extracted
                pending = list(target.parts[1:] if target.is_absolute() else target.parts) + pending
            else:
                path = candidate
        if path.is_file():
            sources.append("/" + str(path.relative_to(extracted)))
    return sources


def rom_properties(extracted):
    extracted = extracted.resolve(strict=True)
    properties = {}
    sources = rom_property_sources(extracted)
    for source in sources:
        properties.update(parse((extracted / source.lstrip("/")).read_text(encoding="utf-8")))
    if properties.get("ro.build.version.sdk") != "29" or "arm64-v8a" not in properties.get("ro.product.cpu.abilist", ""):
        raise ValueError("This runtime requires an ARM64 Android 10 ROM")
    first_api_level = properties.get("ro.product.first_api_level", "29")
    properties = merge(extracted, sources, ROOT / "guest-runtime/native/guest.prop")
    properties["ro.product.first_api_level"] = first_api_level
    properties["ro.frp.pst"] = ""
    properties.pop("dalvik.vm.boot-image", None)
    properties.pop("ro.dalvik.vm.boot-image", None)
    return properties


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def arm64(path):
    with path.open("rb") as stream:
        header = stream.read(20)
    return header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\xb7\x00"


def init_data_directories(extracted):
    result = set()
    files = list(extracted.glob("init*.rc"))
    for directory in ("system/etc/init", "vendor/etc/init"):
        files.extend((extracted / directory).rglob("*.rc"))
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.lstrip().startswith("mkdir "):
                continue
            words = shlex.split(line, comments=True)
            if len(words) >= 2 and words[0] == "mkdir" and words[1].startswith("/data/"):
                guest = words[1]
                if "$" not in guest and ".." not in Path(guest).parts:
                    if guest == "/data/data" or guest.startswith("/data/data/"):
                        guest = "/data/user/0" + guest[len("/data/data"):]
                    result.add(guest.lstrip("/"))
    return result


def transport_policy(original, transport, extra_syscalls=("readlinkat", "newfstatat", "getcwd", "fgetxattr")):
    defined = {line.split(":", 1)[0].strip() for line in original.splitlines()
               if ":" in line and not line.lstrip().startswith("#")}
    extra = []
    additions = transport + "\n" + "\n".join(name + ": 1" for name in extra_syscalls)
    for line in additions.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name = line.split(":", 1)[0].strip()
        if name not in defined:
            extra.append(line)
            defined.add(name)
    return original + "\n" + "\n".join(extra) + "\n"


def paired_audio_links(links, bridge_files):
    paths = {"rootfs" + item["guestPath"]: item["logical"] for item in bridge_files
             if item.get("guestPath", "").startswith("/vendor/lib64/hw/")
             and ("audio" in item["guestPath"])}
    paired, disabled = [], []
    for item in links:
        if item["path"] in paths:
            paired.append(dict(item, logical=paths[item["path"]]))
        elif re.fullmatch(r"rootfs/vendor/lib64/hw/android\.hardware\.audio(?:\.effect)?@[^/]+-impl\.so", item["path"]):
            disabled.append(item["path"])
        else:
            paired.append(item)
    for path, logical in paths.items():
        if not any(item["path"] == path for item in paired):
            paired.append({"path": path, "logical": logical})
    return paired, disabled


def install_service_identity(prepared):
    name = "liba10vm-rom-service-identity.so"
    source = ROOT / "artifacts/container/rom-services" / name
    target = prepared / "jniLibs/arm64-v8a" / name
    shutil.copyfile(source, target)
    path = prepared / "assets/guest-runtime-inputs.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"] = [item for item in manifest["files"] if item["logical"] != name]
    manifest["files"].append({"logical": name, "name": name, "bytes": target.stat().st_size,
                              "sha256": digest(target)})
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def stage_profile(extracted, output):
    extracted = extracted.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((BASE / "assets/guest-runtime-inputs.json").read_text())
    imported = json.loads((extracted.parent / "import.json").read_text())
    manifest["bridgeImageSha256"] = manifest["sourceImageSha256"]
    manifest["sourceImageSha256"] = imported["partitions"]["system"]["sha256"]
    manifest["romImport"] = imported
    native = {item["logical"]: dict(item) for item in manifest["files"]
              if not item["logical"].startswith("image/")}
    lib = output / "jniLibs/arm64-v8a"
    assets = output / "assets"
    lib.mkdir(parents=True)
    assets.mkdir()
    for item in native.values():
        shutil.copyfile(BASE / "jniLibs/arm64-v8a" / item["name"], lib / item["name"])
    provenance = {}

    def supply(logical, source, guest=None, library=None):
        previous = native.get(logical)
        name = previous["name"] if previous else "liba10vm-rom-" + hashlib.sha256(logical.encode()).hexdigest()[:20] + ".so"
        target = lib / name
        shutil.copyfile(source, target)
        target.chmod(0o755)
        item = {"logical": logical, "name": name, "sha256": digest(target), "bytes": target.stat().st_size}
        if guest:
            item["guestPath"] = guest
        if library is not None:
            item["libraryName"] = library
        native[logical] = item
        provenance[logical] = str(source.relative_to(extracted))

    apexes = [path for path in (extracted / "system/apex").iterdir()
              if path.name.startswith("com.android.runtime.") and path.is_dir()]
    if len(apexes) != 1:
        raise ValueError("Expected one extracted Android 10 runtime APEX")
    runtime = apexes[0]
    search = [runtime / "lib64", extracted / "system/lib64", extracted / "system/lib64/vndk-29",
              extracted / "system/lib64/vndk-sp-29"]
    search.extend(path / "lib64" for path in (extracted / "system/apex").iterdir() if path.is_dir())
    search.extend([extracted / "system/product/lib64", extracted / "vendor/lib64"])
    # Default SONAME selection; full guest paths below retain other vendor/APEX copies.
    chosen = {}
    for directory in search:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.name.endswith(".so") and path.is_file() and not path.is_symlink() and arm64(path):
                chosen.setdefault(path.name, path)
    for name, source in chosen.items():
        if name not in BRIDGES and not name.startswith("liba10vm-"):
            supply(name, source, "/" + str(source.relative_to(extracted)))
    for logical, source in {"dalvikvm64": runtime / "bin/dalvikvm64",
                            "app_process64": extracted / "system/bin/app_process64"}.items():
        supply(logical, source, "/" + str(source.relative_to(extracted)))

    data, directories, symlinks, links = [], set(manifest["initialDirectories"]), [], []
    directories.update(init_data_directories(extracted))
    overrides = {"/" + str(path.relative_to(extracted)): name for name, path in chosen.items()}
    for name in BRIDGES:
        for directory in search + [runtime / "lib64/bionic"]:
            path = directory / name
            if path.is_file() and not path.is_symlink():
                overrides["/" + str(path.relative_to(extracted))] = name
    for name in ("linker64", "linker_asan64"):
        overrides["/system/bin/" + name] = "ld-android.so"
        overrides["/" + str(runtime.relative_to(extracted)) + "/bin/" + name] = "ld-android.so"
    overrides.update({item["guestPath"]: logical for logical, item in native.items()
                      if "guestPath" in item and logical in ("app_process64", "dalvikvm64")})
    for path in sorted(extracted.rglob("*")):
        guest = "/" + str(path.relative_to(extracted))
        if path.is_symlink():
            symlinks.append({"path": "rootfs" + guest, "target": str(path.readlink())})
        elif path.is_dir():
            directories.add(guest.lstrip("/"))
        elif path.is_file():
            if arm64(path):
                logical = overrides.get(guest)
                if not logical:
                    logical = "rom" + guest
                    supply(logical, path, library="")
                links.append({"path": "rootfs" + guest, "logical": logical})
            else:
                name = "guest-runtime/rootfs" + guest + (".asset" if guest.endswith((".bc", ".gz")) else "")
                target = assets / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                data.append({"name": name, "installPath": "rootfs" + guest,
                             "bytes": target.stat().st_size, "sha256": digest(target),
                             "mode": path.stat().st_mode & 0o777})
    for item in manifest["data"]:
        if item["name"].startswith("guest-runtime/rootfs/") or item["name"] == "guest-runtime/guest.prop":
            continue
        target = assets / item["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BASE / "assets" / item["name"], target)
        data.append(dict(item))

    properties = rom_properties(extracted)
    target = assets / "guest-runtime/guest.prop"
    target.write_text("".join(key + "=" + value + "\n" for key, value in sorted(properties.items())), encoding="utf-8")
    data.append({"name": "guest-runtime/guest.prop", "bytes": target.stat().st_size, "sha256": digest(target)})
    environ = (extracted / "init.environ.rc").read_text()
    for name, key in (("BOOTCLASSPATH", "bootClassPath"), ("SYSTEMSERVERCLASSPATH", "systemServerClassPath")):
        value = re.search(r"^\s+export " + name + r" (.+)$", environ, re.M)
        if not value:
            raise ValueError("Missing ROM classpath: " + name)
        manifest[key] = value.group(1).strip().split(":")
    manifest.update(files=list(native.values()), data=data, symlinks=symlinks, links=[], nativeLinks=links,
                    propertyCount=len(properties),
                    initialDirectories=sorted(directories),
                    rootfsAliases={"apex/com.android.runtime": "/" + str(runtime.relative_to(extracted))},
                    romNativeSources=provenance, romFramework=True, desktopVerified=False)
    manifest["desktopPackages"] = {item["installPath"].removeprefix("rootfs/"): "/" + item["installPath"].removeprefix("rootfs/")
                                   for item in data if item.get("installPath", "").endswith(".apk")}
    manifest["systemApkCount"] = len(manifest["desktopPackages"])
    (assets / "guest-runtime-inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "profile-summary.json").write_text(json.dumps({
        "nativeFiles": len(native), "dataFiles": len(data), "romNativeFiles": len(provenance),
        "runtimeApex": runtime.name, "bridgeLibraries": sorted(BRIDGES),
        "bootClassPath": manifest["bootClassPath"], "systemServerClassPath": manifest["systemServerClassPath"]}, indent=2) + "\n")
    return manifest


def adapt_host_bridges(prepared, services_override=None):
    path = prepared / "assets/guest-runtime-inputs.json"
    manifest = json.loads(path.read_text())
    extracted = prepared.parent / "extracted"
    directories = init_data_directories(extracted)
    existing = {"data/user/0" + name[len("data/data"):] if name == "data/data" or name.startswith("data/data/") else name
                for name in manifest["initialDirectories"]}
    manifest["initialDirectories"] = sorted(existing | directories)
    manifest["romInitDataDirectories"] = sorted(directories)
    base = json.loads((BASE / "assets/guest-runtime-inputs.json").read_text())
    overrides = manifest.setdefault("hostBridgeOverrides", {})
    for library in ("libselinux.so", "libhwbinder.so", "libhidlbase.so", "libhidltransport.so",
                    "libbinderthreadstate.so"):
        item = next(item for item in base["files"] if item["logical"] == library)
        target = next(item for item in manifest["files"] if item["logical"] == library)
        source = BASE / "jniLibs/arm64-v8a" / item["name"]
        shutil.copyfile(source, prepared / "jniLibs/arm64-v8a" / target["name"])
        target.update(bytes=item["bytes"], sha256=item["sha256"])
        manifest["romNativeSources"].pop(library, None)
        overrides[library] = item["sha256"]
    manifest["nativeLinks"], disabled = paired_audio_links(manifest["nativeLinks"], base["files"])
    manifest["disabledRomAudioHalPaths"] = sorted(set(manifest.get("disabledRomAudioHalPaths", [])) | set(disabled))
    selected = {"/system/etc/vintf/manifest.xml", "/vendor/etc/vintf/manifest.xml",
                "/vendor/etc/vintf/manifest/a10vm-host-devices.xml",
                "/vendor/etc/vintf/manifest/a10vm-media-codec.xml"}
    selected.update("/vendor/etc/" + name for name in ("audio_policy_configuration.xml", "audio_policy_volumes.xml",
                    "default_volume_tables.xml", "primary_audio_policy_configuration.xml",
                    "r_submix_audio_policy_configuration.xml", "surround_sound_configuration_5_0.xml", "audio_effects.xml"))
    selected.update("/" + item["name"].removeprefix("guest-runtime/rootfs/") for item in base["data"]
                    if "seccomp_policy/" in item["name"] and
                    Path(item["name"]).name in ("mediacodec.policy", "mediaextractor.policy", "mediaswcodec.policy"))
    data = {item.get("installPath", item["name"].removeprefix("guest-runtime/")): item for item in manifest["data"]}
    for item in base["data"]:
        guest = "/" + item.get("installPath", item["name"].removeprefix("guest-runtime/"))
        if not guest.startswith("/rootfs/") or guest.removeprefix("/rootfs") not in selected:
            continue
        target = prepared / "assets" / item["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BASE / "assets" / item["name"], target)
        entry = dict(item, installPath=guest.lstrip("/"))
        data[entry["installPath"]] = entry
        overrides[guest] = entry["sha256"]
    policy_guest = "rootfs/vendor/etc/seccomp_policy/configstore@1.1.policy"
    item = data[policy_guest]
    target = prepared / "assets" / item["name"]
    transport = (ROOT / "guest-runtime/native/media-transport.policy").read_text()
    original = (BASE / "assets" / next(item["name"] for item in base["data"]
                if item["name"].endswith("/configstore@1.1.policy"))).read_text()
    target.write_text(transport_policy(original, transport), encoding="utf-8")
    item.update(bytes=target.stat().st_size, sha256=digest(target))
    overrides[policy_guest] = item["sha256"]
    for guest, item in data.items():
        if guest.startswith("rootfs/vendor/etc/seccomp_policy/") and Path(guest).name in (
                "mediacodec.policy", "mediaextractor.policy", "mediaswcodec.policy"):
            target = prepared / "assets" / item["name"]
            original = target.read_text()
            target.write_text(transport_policy(original, "fgetxattr: 1\ngetxattr: 1", extra_syscalls=()), encoding="utf-8")
            item.update(bytes=target.stat().st_size, sha256=digest(target))
            overrides[guest] = item["sha256"]
    item = data["guest.prop"]
    target = prepared / "assets" / item["name"]
    properties = [line for line in target.read_text().splitlines() if not line.startswith("ro.frp.pst=")]
    target.write_text("\n".join(properties) + "\nro.frp.pst=\n", encoding="utf-8")
    item.update(bytes=target.stat().st_size, sha256=digest(target))
    overrides["guest.prop"] = item["sha256"]
    if services_override:
        item = data["rootfs/system/framework/services.jar"]
        target = prepared / "assets" / item["name"]
        shutil.copyfile(services_override, target)
        item.update(bytes=target.stat().st_size, sha256=digest(target))
        overrides["rootfs/system/framework/services.jar"] = item["sha256"]
    manifest["data"] = list(data.values())
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return overrides


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bridges-only", action="store_true")
    parser.add_argument("--services-override", type=Path)
    args = parser.parse_args()
    if args.bridges_only:
        print(json.dumps(adapt_host_bridges(args.output, args.services_override), indent=2))
    else:
        profile = stage_profile(args.extracted, args.output)
        adapt_host_bridges(args.output, args.services_override)
        print(json.dumps({"nativeFiles": len(profile["files"]), "dataFiles": len(profile["data"])}))
    install_service_identity(args.output)
