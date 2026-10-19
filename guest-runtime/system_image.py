"""Restore immutable image paths without replacing the private runtime overrides."""
import json
from pathlib import Path
import posixpath
import re
import stat
import subprocess

from prepare import DEBUGFS, IMAGE, ROOT, digest
from system_packages import SystemPackages
from media_bundle import PROGRAMS as MEDIA_PROGRAMS

OUT = ROOT / "artifacts/container/system-image"
PARTITIONS = {"system", "vendor", "odm", "oem", "sbin"}
PROGRAM_PATHS = {
    "dalvikvm64": "/system/apex/com.android.runtime.debug/bin/dalvikvm64",
    "ld-android.so": "/system/apex/com.android.runtime.debug/bin/linker64",
    "system-suspend": "/system/bin/hw/android.system.suspend@1.0-service",
    "graphics-composer": "/vendor/bin/hw/android.hardware.graphics.composer@2.1-service",
    "graphics-allocator": "/vendor/bin/hw/android.hardware.graphics.allocator@2.0-service",
    "graphics-configstore": "/vendor/bin/hw/android.hardware.configstore@1.1-service",
    "health": "/vendor/bin/hw/android.hardware.health@2.0-service.goldfish",
    "audio-hal": "/vendor/bin/hw/android.hardware.audio@2.0-service",
    **MEDIA_PROGRAMS,
}


def inventory():
    image = SystemPackages(DEBUGFS, IMAGE)
    entries = []

    def walk(directory, recurse=True):
        for row in image.query("ls -p " + directory).splitlines():
            fields = row.split("/")
            if len(fields) < 7 or fields[5] in (".", "..") or fields[1] == "0":
                continue
            path = posixpath.join(directory, fields[5])
            mode = int(fields[2], 8)
            entry = {"path": path, "inode": int(fields[1]), "mode": mode,
                     "bytes": int(fields[6] or 0)}
            if stat.S_ISLNK(mode):
                match = re.search(r'Fast link dest: "([^"]*)"', image.query("stat " + path))
                if match:
                    entry["target"] = match.group(1)
                else:
                    result = subprocess.run([str(DEBUGFS), "-R", "cat " + path, str(IMAGE)],
                                            capture_output=True, check=True)
                    entry["target"] = result.stdout.decode("utf-8")
                assert entry["target"] and "\x00" not in entry["target"], path
            entries.append(entry)
            if stat.S_ISDIR(mode) and (recurse or fields[5] in PARTITIONS):
                walk(path)

    walk("/", False)
    return entries


def overrides(files):
    native, data, paths = {}, {}, {}
    for entry in files:
        logical = entry.get("logical", entry.get("name", ""))
        if "/rootfs/" in entry["path"]:
            data["/" + entry["path"].split("/rootfs/", 1)[1]] = entry
        elif logical:
            native[logical] = entry
    for logical, entry in native.items():
        path = entry.get("guestPath", PROGRAM_PATHS.get(logical, entry.get("source", "")))
        if path.startswith("/"):
            paths[path] = logical
    return native, data, paths


def coverage(entries, files):
    native, data, paths = overrides(files)
    missing = []
    for item in entries:
        path = item["path"]
        if not stat.S_ISREG(item["mode"]):
            continue
        library = posixpath.basename(path)
        supplied = path in data or path in paths or (
            "/lib64/" in path and library in native)
        if not supplied:
            missing.append(item)
    return missing


def canonical_parent(path, symlinks):
    for _ in range(40):
        parts = path.strip("/").split("/")
        for count in range(1, len(parts)):
            prefix = "/" + "/".join(parts[:count])
            if prefix not in symlinks:
                continue
            target = symlinks[prefix]
            if not target.startswith("/"):
                target = posixpath.join(posixpath.dirname(prefix), target)
            path = posixpath.normpath(posixpath.join(target, *parts[count:]))
            break
        else:
            return path
    raise ValueError("System directory symlink loop: " + path)


def prepare(files, image_hash):
    assert digest(IMAGE) == image_hash, "System image hash mismatch"
    entries = inventory()
    native, data, paths = overrides(files)
    baseline = coverage(entries, files)
    restored, native_links, symlinks, links, directories = [], [], [], [], []
    inodes = {}
    search_names = {name for name in native if "/" not in name and name.endswith(".so")}
    regular = [item for item in entries if stat.S_ISREG(item["mode"])]
    # Default namespace selection is stable; exact guest paths keep separate vendor/VNDK copies.
    regular.sort(key=lambda item: (not item["path"].startswith("/system/lib64/"),
                                   item["path"].count("/"), item["path"]))
    for item in entries:
        path = item["path"]
        if stat.S_ISDIR(item["mode"]):
            directories.append(path.lstrip("/"))
        elif stat.S_ISLNK(item["mode"]) and path not in data:
            symlinks.append({"path": "rootfs" + path, "target": item["target"]})
    for item in regular:
        guest = item["path"]
        name = posixpath.basename(guest)
        logical = paths.get(guest)
        if "/lib64/" in guest and name in native:
            logical = name
        if guest.endswith("/linker64") or guest.endswith("/linker_asan64"):
            logical = "ld-android.so"
        if logical:
            native_links.append({"path": "rootfs" + guest, "logical": logical})
            continue
        if guest in data:
            continue
        if item["inode"] in inodes:
            links.append({"path": "rootfs" + guest, "target": inodes[item["inode"]]})
            continue
        path = OUT / "rootfs" / guest.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([str(DEBUGFS), "-R", f'dump {guest} "{path}"', str(IMAGE)],
                                capture_output=True)
        assert result.returncode == 0 and path.is_file() and path.stat().st_size == item["bytes"], guest
        entry = {"source": guest, "path": str(path.relative_to(ROOT)), "bytes": item["bytes"],
                 "sha256": digest(path), "mode": stat.S_IMODE(item["mode"])}
        with path.open("rb") as stream:
            header = stream.read(20)
        if header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\xb7\x00":
            logical = "image/" + guest.lstrip("/")
            entry.update(name=logical, imageNative=True)
            native_links.append({"path": "rootfs" + guest, "logical": logical})
            if name.endswith(".so") and name not in search_names:
                entry["libraryName"] = name
                search_names.add(name)
        else:
            inodes[item["inode"]] = "rootfs" + guest
        restored.append(entry)
    manifest = {"sourceImageSha256": image_hash, "files": restored, "nativeLinks": native_links,
                "symlinks": symlinks, "links": links, "directories": directories,
                "inventory": entries, "preservedRuntimeOverrides": sorted(native),
                "mutableDataPreserved": True,
                "baselineMissingFiles": len(baseline),
                "baselineMissingBytes": sum(item["bytes"] for item in baseline)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"systemImagePaths": len(entries), "restoredFiles": len(restored),
                      "baselineMissingFiles": len(baseline), "nativeLinks": len(native_links),
                      "restoredBytes": sum(item["bytes"] for item in restored)}, indent=2), flush=True)
    return manifest


if __name__ == "__main__":
    files = []
    for component in ("art", "framework", "desktop"):
        files.extend(json.loads((ROOT / "artifacts/container" / component / "inputs.json").read_text())["files"])
    entries = inventory()
    missing = coverage(entries, files)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "baseline.json").write_text(json.dumps({"inventory": entries, "missing": missing}, indent=2) + "\n")
    print(json.dumps({"paths": len(entries), "missingFiles": len(missing),
                      "missingBytes": sum(item["bytes"] for item in missing),
                      "missingSystemBin": sum(item["path"].startswith("/system/bin/") for item in missing)}, indent=2))
    raise SystemExit(1 if missing else 0)
