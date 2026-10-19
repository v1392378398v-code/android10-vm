#!/usr/bin/env python3
"""Check source-image path coverage and preservation of the patched native inputs."""
import json
import stat
import xml.etree.ElementTree as ET

from prepare import ROOT, digest
from system_image import OUT, overrides


def main():
    image = json.loads((OUT / "inputs.json").read_text())
    prepared = ROOT / "guest-runtime/build/prepared"
    manifest = json.loads((prepared / "assets/guest-runtime-inputs.json").read_text())
    native = {item["logical"]: item for item in manifest["files"]}
    data = {"/" + item.get("installPath", item["name"].removeprefix("guest-runtime/")).removeprefix("rootfs/"): item
            for item in manifest["data"] if item["name"].startswith("guest-runtime/rootfs/")}
    directories = {"/" + path for path in manifest["initialDirectories"]}
    native_links = {item["path"].removeprefix("rootfs"): item["logical"] for item in manifest["nativeLinks"]}
    symlinks = {item["path"].removeprefix("rootfs"): item["target"] for item in manifest["symlinks"]}
    links = {item["path"].removeprefix("rootfs"): item["target"].removeprefix("rootfs")
             for item in manifest["links"]}
    missing = []
    for item in image["inventory"]:
        path, mode = item["path"], item["mode"]
        covered = path in directories if stat.S_ISDIR(mode) else path in data or path in native_links or (
            path in symlinks if stat.S_ISLNK(mode) else path in links)
        if not covered:
            missing.append(path)
        if path in links:
            assert links[path] in data, (path, links[path])
    assert not missing, "Missing source image paths: " + ", ".join(missing[:20])
    for path, logical in native_links.items():
        assert logical in native, (path, logical)
    for alias in symlinks:
        assert not any(path.startswith(alias + "/") for path in data), "Data below system symlink: " + alias
        assert not any(path.startswith(alias + "/") for path in native_links), "Native data below system symlink: " + alias
    for item in manifest["files"] + manifest["data"]:
        path = prepared / ("jniLibs/arm64-v8a" if "logical" in item else "assets") / item["name"]
        assert path.is_file() and path.stat().st_size == item["bytes"] and digest(path) == item["sha256"], item["name"]
    stock = []
    for component in ("art", "framework", "desktop"):
        stock.extend(json.loads((ROOT / "artifacts/container" / component / "inputs.json").read_text())["files"])
    patched, _, _ = overrides(stock)
    for logical, original in patched.items():
        assert native[logical]["sha256"] == original["sha256"], "Override changed: " + logical
    for command in ("sh", "toybox", "toolbox", "cmd", "sqlite3"):
        assert "/system/bin/" + command in native_links, command
    for command in ("ls", "cat", "readlink", "getprop"):
        assert "/system/bin/" + command in symlinks, command
    assert manifest["mutableDataPreserved"] and not manifest["rootRequired"]
    assert not any(path.startswith("/data/") for path in data), "User data included in immutable restore"
    assert not any(item["name"].endswith((".bc", ".gz")) for item in manifest["data"]), "APK asset transform trigger"
    assert all(item["name"].endswith(path.rsplit("/", 1)[1] + ".asset") for path, item in data.items()
               if path.endswith((".bc", ".gz")))
    sensor_instances = set()
    gnss_services = []
    for path, item in data.items():
        if not path.startswith("/vendor/etc/vintf/") or not path.endswith(".xml"):
            continue
        document = ET.parse(prepared / "assets" / item["name"])
        gnss_services.extend(document.findall("./hal[name='android.hardware.gnss']"))
        for hal in document.findall("./hal[name='android.hardware.sensors']"):
            sensor_instances.update(node.text for node in hal.findall("fqname"))
            for version in hal.findall("version"):
                for interface in hal.findall("interface"):
                    sensor_instances.update("@" + version.text + "::" + interface.findtext("name") + "/" + node.text
                                            for node in interface.findall("instance"))
    assert sensor_instances == {"@1.0::ISensors/default"}, "Unsupported image sensor service: " + str(sensor_instances)
    assert not gnss_services, "Image GNSS HAL has no host bridge and blocks LocationManager startup"
    print(json.dumps({"passed": True, "sourceImagePaths": len(image["inventory"]), "missingPaths": 0,
                      "systemBinPaths": sum(item["path"].startswith("/system/bin/") for item in image["inventory"]),
                      "baselineMissingFiles": image["baselineMissingFiles"],
                      "restoredFiles": len(image["files"]), "preservedNativeInputs": len(patched),
                      "hostSensorManifestVerified": True, "unbridgedGnssManifestExcluded": True}, indent=2))


if __name__ == "__main__":
    main()
