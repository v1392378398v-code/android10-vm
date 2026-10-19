"""Stage the audited Android 10 AOSP LatinIME APK and its matching native library."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PREPARED = ROOT / "guest-runtime/build/prepared"
SOURCE_APK = "/system/product/app/LatinIME/LatinIME.apk"
ROM_APK = "/system/app/A10vmKeyboard/LatinIME.apk"
APK_SHA256 = "d8353e848158226aa7e9fbec0ef9345b2d49adbafd2dc7688f2297cdccbe16b9"
JNI_SHA256 = "8d82db1ba4c41b343d6d331516939084705a6c60301a55a29b17c3b4f0758f68"
COMPONENT = "com.android.inputmethod.latin/.LatinIME"
OBSOLETE = [
    "rootfs/system/app/A10vmKeyboard/Keyboard.apk",
    "rootfs/system/app/A10vmKeyboard/lib/arm64/librime_jni.so",
    "rootfs/system/lib64/librime_jni.so",
    "rootfs/system/etc/a10vm-keyboard/default.custom.yaml",
    "lib/librime_jni.so",
]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_keyboard(prepared, source_prepared=SOURCE_PREPARED):
    source_inputs = json.loads((source_prepared / "assets/guest-runtime-inputs.json").read_text(encoding="utf-8"))
    if source_inputs["guestSdk"] != 29:
        raise ValueError("Expected audited Android 10 AOSP inputs")
    apk = source_prepared / ("assets/guest-runtime/rootfs" + SOURCE_APK)
    source_jni = next(item for item in source_inputs["files"] if item["logical"] == "libjni_latinime.so")
    jni = source_prepared / "jniLibs/arm64-v8a" / source_jni["name"]
    if digest(apk) != APK_SHA256 or digest(jni) != JNI_SHA256:
        raise ValueError("AOSP LatinIME APK/native pair checksum mismatch")
    manifest = prepared / "assets/guest-runtime-inputs.json"
    inputs = json.loads(manifest.read_text(encoding="utf-8"))
    apk_path = ROM_APK if inputs.get("runtimeProfile") == "miui12" else SOURCE_APK

    def asset(guest_path, source):
        name = "guest-runtime/rootfs" + guest_path
        target = prepared / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        inputs["data"] = [item for item in inputs["data"] if item["name"] != name]
        inputs["data"].append({"name": name, "bytes": target.stat().st_size, "sha256": digest(target)})

    for path in OBSOLETE:
        target = prepared / "assets/guest-runtime" / path
        if target.is_file() or target.is_symlink():
            target.unlink()
    removed = {"guest-runtime/" + path for path in OBSOLETE}
    inputs["data"] = [item for item in inputs["data"] if item["name"] not in removed]
    inputs["desktopPackages"].pop("system/app/A10vmKeyboard/Keyboard.apk", None)
    old = [item for item in inputs["files"] if item["logical"] == "librime_jni.so"]
    for item in old:
        (prepared / "jniLibs/arm64-v8a" / item["name"]).unlink(missing_ok=True)
    inputs["files"] = [item for item in inputs["files"] if item["logical"] != "librime_jni.so"]
    inputs["nativeLinks"] = [item for item in inputs.get("nativeLinks", []) if item["logical"] != "librime_jni.so"]

    asset(apk_path, apk)
    for name in ("NOTICE.md", "LICENSE"):
        asset("/system/etc/a10vm-keyboard/" + name, ROOT / "guest-runtime/keyboard" / name)
    existing = next((item for item in inputs["files"] if item["logical"] == "libjni_latinime.so"), None)
    if existing and existing["sha256"] != JNI_SHA256:
        raise ValueError("Conflicting LatinIME native library")
    native_name = existing["name"] if existing else "liba10vm-keyboard-latinime.so"
    native = prepared / "jniLibs/arm64-v8a" / native_name
    native.parent.mkdir(parents=True, exist_ok=True)
    if native.resolve() != jni.resolve():
        shutil.copyfile(jni, native)
    native.chmod(0o755)
    guest_jni = str(Path(apk_path).parent / "lib/arm64/libjni_latinime.so")
    library = {"logical": "libjni_latinime.so", "name": native_name, "bytes": native.stat().st_size,
               "sha256": digest(native), "libraryName": "libjni_latinime.so", "guestPath": guest_jni}
    inputs["files"] = [item for item in inputs["files"] if item["logical"] != library["logical"]] + [library]
    link = {"path": "rootfs" + guest_jni, "logical": library["logical"]}
    inputs["nativeLinks"] = [item for item in inputs["nativeLinks"] if item["path"] != link["path"]] + [link]
    inputs["desktopPackages"][apk_path[1:]] = apk_path
    inputs["obsoleteSystemAssets"] = list(OBSOLETE)
    inputs["bundledInputMethod"] = {
        "package": "com.android.inputmethod.latin", "component": COMPONENT, "version": "Android 10",
        "apk": apk_path, "sha256": APK_SHA256, "nativeLogical": library["logical"],
        "nativeLibrary": guest_jni, "nativeSha256": JNI_SHA256, "addedSystemApk": apk_path == ROM_APK,
        "sourceImageSha256": source_inputs["sourceImageSha256"],
        "source": "https://android.googlesource.com/platform/packages/inputmethods/LatinIME/+/android-10.0.0_r47/",
    }
    manifest.write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    return inputs["bundledInputMethod"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("--source-prepared", type=Path, default=SOURCE_PREPARED)
    arguments = parser.parse_args()
    print(json.dumps(stage_keyboard(arguments.prepared, arguments.source_prepared), indent=2))
