"""Add the paired host camera HAL, provider and service to prepared APK inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
CAMERA = ROOT / "artifacts/container/camera"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_camera(prepared):
    path = prepared / "assets/guest-runtime-inputs.json"
    inputs = json.loads(path.read_text(encoding="utf-8"))
    files = {item["logical"]: item for item in inputs["files"]}
    links = {item["path"]: item for item in inputs.get("nativeLinks", [])}
    libraries = prepared / "jniLibs/arm64-v8a"

    def native(logical, source, guest, replace=False):
        if logical in files and not replace:
            return
        with source.open("rb") as stream:
            header = stream.read(20)
        assert header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\xb7\x00", source
        item = files.get(logical, {"logical": logical, "name": "liba10vm-camera-" +
                                 hashlib.sha256(logical.encode()).hexdigest()[:20] + ".so"})
        target = libraries / item["name"]
        shutil.copyfile(source, target)
        target.chmod(0o755)
        item.update(bytes=target.stat().st_size, sha256=digest(target), guestPath=guest)
        if logical.endswith(".so"):
            item["libraryName"] = logical
        files[logical] = item
        links["rootfs" + guest] = {"path": "rootfs" + guest, "logical": logical}

    native("cameraserver", CAMERA / "bin/cameraserver", "/system/bin/cameraserver", True)
    native("camera-provider", CAMERA / "bin/camera-provider",
           "/vendor/bin/hw/a10vm-camera-provider", True)
    for source in sorted((CAMERA / "lib").glob("*.so")):
        guest = "/vendor/lib64/hw/" + source.name if source.name == "camera.a10vm.so" else "/system/lib64/" + source.name
        native(source.name, source, guest, source.name in ("camera.a10vm.so", "libcameraservice.so",
                                                         "liba10vm-hal-modules.so"))
    inputs["files"] = list(files.values())
    inputs["nativeLinks"] = list(links.values())
    manifest_name = "guest-runtime/rootfs/vendor/etc/vintf/manifest/a10vm-camera.xml"
    manifest = prepared / "assets" / manifest_name
    manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "guest-runtime/native/host-camera.xml", manifest)
    seed_name = "guest-runtime/guest.prop"
    seed = prepared / "assets" / seed_name
    properties = dict(line.split("=", 1) for line in seed.read_text(encoding="utf-8").splitlines())
    properties["config.disable_cameraservice"] = "false"
    properties["ro.hardware.camera"] = "a10vm"
    # MIUI's built-in warning policy permits missing optional vendor tags on HAL1.
    properties["log.tag.VENDOR_TAG_NFE_RETHROW"] = "D"
    seed.write_text("".join(key + "=" + value + "\n" for key, value in properties.items()), encoding="utf-8")
    inputs["data"] = [item for item in inputs["data"] if item["name"] not in (manifest_name, seed_name)]
    for name in (manifest_name, seed_name):
        target = prepared / "assets" / name
        inputs["data"].append({"name": name, "bytes": target.stat().st_size, "sha256": digest(target)})
    inputs["propertyCount"] = len(properties)
    inputs["hostCameraBridge"] = True
    camera_name = "guest-runtime/rootfs/system/priv-app/MiuiCamera/MiuiCamera.apk"
    camera = prepared / "assets" / camera_name
    if camera.is_file() and not inputs.get("miuiCameraLegacyVideoSessions"):
        derived = CAMERA / "MiuiCamera-legacy.apk"
        subprocess.run(["sh", str(ROOT / "guest-runtime/build-miui-camera.sh"),
                        str(camera), str(derived)], check=True)
        shutil.copyfile(derived, camera)
        item = next(item for item in inputs["data"] if item["name"] == camera_name)
        item.update(bytes=camera.stat().st_size, sha256=digest(camera))
        inputs["miuiCameraLegacySessions"] = True
        inputs["miuiCameraLegacyVideoSessions"] = True
    path.write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    return {"hostCameraBridge": True, "nativeFiles": len(files), "rootRequired": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(stage_camera(arguments.prepared), indent=2))
