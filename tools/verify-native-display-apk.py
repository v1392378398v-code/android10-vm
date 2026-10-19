#!/usr/bin/env python3
"""Check the native application artifact, its paired ELF inputs and JNI exports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "guest-runtime"))
from system_image import canonical_parent


def dex_strings(data):
    size, offset = struct.unpack_from("<II", data, 56)
    strings = set()
    for (start,) in struct.iter_unpack("<I", data[offset:offset + size * 4]):
        while data[start] & 0x80:
            start += 1
        start += 1
        strings.add(data[start:data.index(0, start)])
    return strings


ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("apk", nargs="?", type=Path, default=ROOT / "app/build/outputs/apk/debug/app-debug.apk")
parser.add_argument("--runtime-prepared", type=Path, default=ROOT / "guest-runtime/build/prepared")
args = parser.parse_args()
apk = args.apk.resolve()
expected = json.loads((ROOT / "app/build/native-display/assets/native-display-inputs.json").read_text())
runtime = json.loads((args.runtime_prepared / "assets/guest-runtime-inputs.json").read_text())
rom = runtime.get("runtimeProfile") == "miui12"
gradle = (ROOT / "app/build.gradle.kts").read_text()
versions = re.findall(r'"([^"]+)"', re.search(r'^\s*versionName\s*=(.*)$', gradle, re.M).group(1))
version_name = versions[0 if rom else -1]
version_codes = re.findall(r'\b(\d+)\b', re.search(r'^\s*versionCode\s*=(.*)$', gradle, re.M).group(1))
assert len(version_codes) in (1, 2), "Expected a constant or MIUI/baseline versionCode"
version_code = int(version_codes[0 if rom else -1])
badging = subprocess.check_output(["aapt2", "dump", "badging", str(apk)], text=True)
package = dict(re.findall(r"(\w+)='([^']*)'", badging.splitlines()[0]))
assert re.search(r"^(?:minSdkVersion|sdkVersion):'28'$", badging, re.M), "Expected Android 9 host minimum"
assert package["name"] == ("io.a10vm.miui" if rom else "io.a10vm")
assert package["versionName"] == version_name and int(package["versionCode"]) == version_code, package
display_files = {"liba10vm-p1-client.so", "liba10vm-desktop-window.so"}
assert {entry["name"] for entry in expected["files"]} == display_files and len(expected["files"]) == 2
assert runtime["guestSdk"] == 29 and runtime["loaderFromSource"] and runtime["artIntegrated"]
assert not runtime["rootRequired"] and runtime["desktopImplemented"]
runtime_names = {entry["logical"] for entry in runtime["files"]}
assert {"dalvikvm64", "ld-android.so", "libart.so", "libc.so", "libjavacore.so", "libmedia_jni.so",
        "seed-properties"} <= runtime_names
assert len(runtime_names) == len(runtime["files"])
native_inputs = expected["files"] + runtime["files"]
required = {entry["name"] for entry in native_inputs}
assert len(required) == len(native_inputs), "Duplicate native input names"
assert all(re.fullmatch(r"lib[A-Za-z0-9_.+-]+\.so", name) for name in required)
data_names = {entry["name"] for entry in runtime["data"]}
assert len(data_names) == len(runtime["data"])
assert all(name.startswith("guest-runtime/") and ".." not in Path(name).parts for name in data_names)
system_apks = {name for name in data_names if name.endswith(".apk")}
core_apks = {"guest-runtime/rootfs" + path for path in runtime["desktopPackages"].values()}
# The source image count excludes providers added when staging the runtime.
extra_apks = {"guest-runtime/rootfs/system/app/A10vmWebView/WebView.apk"} if rom and \
    runtime.get("romBoot", {}).get("webviewPackage") else set()
keyboard_apks = {"guest-runtime/rootfs" + runtime["bundledInputMethod"]["apk"]} if runtime.get("bundledInputMethod", {}).get("addedSystemApk") else set()
extra_apks |= keyboard_apks
assert extra_apks <= core_apks
assert runtime["allSystemPackages"] and len(core_apks) == runtime["systemApkCount"] + (len(extra_apks) if rom else 1 + len(keyboard_apks))
assert core_apks <= system_apks
if rom:
    assert core_apks == system_apks
    assert runtime["romBoot"]["bootstrapDex"] == "rom-bootstrap.dex"
else:
    image = json.loads((ROOT / "artifacts/container/system-image/inputs.json").read_text())
    assert system_apks == {"guest-runtime/rootfs" + item["path"] for item in image["inventory"]
                           if item["path"].endswith(".apk")} | keyboard_apks
assert not any(name.endswith((".bc", ".gz")) for name in data_names), "APK asset transform trigger"
assert {"/system/etc/prop.default", "/system/build.prop", "/vendor/default.prop", "/vendor/build.prop",
        "/system/product/build.prop", "/odm/etc/build.prop"} <= set(runtime["propertyFiles"])
aliases = {item["path"].removeprefix("rootfs"): item["target"] for item in runtime["symlinks"]}
assert {"guest-runtime/rootfs" + canonical_parent(path, aliases) for path in runtime["propertyFiles"]} <= data_names
if not rom:
    assert {"path": "rootfs/default.prop", "target": "system/etc/prop.default"} in runtime["symlinks"]
with zipfile.ZipFile(apk) as archive:
    names = archive.namelist()
    assert len(names) == len(set(names)), "Duplicate APK entries"
    assert {name for name in names if name.startswith("lib/")} == {"lib/arm64-v8a/" + name for name in required}
    assert {name for name in names if name.startswith("assets/")} == {
        "assets/native-display-inputs.json", "assets/guest-runtime-inputs.json",
        *("assets/" + name for name in data_names)}
    assert json.loads(archive.read("assets/native-display-inputs.json")) == expected
    assert json.loads(archive.read("assets/guest-runtime-inputs.json")) == runtime
    assert expected["backend"] == "native-arm64-gles-surface" and expected["inputProtocol"] == "touch-v2"
    assert not expected["rootRequired"] and expected["desktopImplemented"]
    assert (expected["width"], expected["height"], expected["targetHz"], expected["density"]) == (1080, 2160, 120, 480)
    for entry in native_inputs:
        data = archive.read("lib/arm64-v8a/" + entry["name"])
        assert len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"], entry["name"]
        assert data[:7] == b"\x7fELF\x02\x01\x01" and int.from_bytes(data[18:20], "little") == 183, entry["name"]
    for entry in runtime["data"]:
        data = archive.read("assets/" + entry["name"])
        assert len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"], entry["name"]
    if runtime.get("bundledInputMethod"):
        keyboard = runtime["bundledInputMethod"]
        jni = next(item for item in runtime["files"] if item["logical"] == keyboard["nativeLogical"])
        assert jni["guestPath"] == keyboard["nativeLibrary"] and jni["sha256"] == keyboard["nativeSha256"]
        assert {"path": "rootfs" + jni["guestPath"], "logical": keyboard["nativeLogical"]} in runtime["nativeLinks"]
    assert archive.read("assets/guest-runtime/runtime-check.dex").startswith(b"dex\n")
    if rom:
        assert b"Lio/a10vm/guest/RomBootstrap;" in dex_strings(
            archive.read("assets/guest-runtime/rom-bootstrap.dex"))
    assert b"Lio/a10vm/guest/GuestDisplayState;" in dex_strings(
        archive.read("assets/guest-runtime/framework-check.dex"))
    seed_lines = archive.read("assets/guest-runtime/guest.prop").decode("utf-8").splitlines()
    profiles = json.loads(archive.read("assets/guest-runtime/rootfs/system/etc/task_profiles.json"))
    assert {"HighPerformance", "TimerSlackNormal"} <= {entry["Name"] for entry in profiles["Profiles"]}
    cgroups = json.loads(archive.read("assets/guest-runtime/rootfs/system/etc/cgroups.json"))
    assert cgroups["Cgroups"]
    seed = dict(line.split("=", 1) for line in seed_lines)
    assert len(seed) == len(seed_lines) == runtime["propertyCount"] and len(seed) > 100
    assert seed["ro.build.version.sdk"] == "29" and seed["ro.product.cpu.abilist"] == "arm64-v8a"
    assert seed["ro.product.cpu.abilist32"] == "" and seed["ro.hardware"] == "a10vm"
    assert all(seed["ro.product." + field] for field in ("brand", "device", "manufacturer", "model", "name"))
    assert seed["ro.build.fingerprint"] and seed["ro.build.version.security_patch"]
    strings = set().union(*(dex_strings(archive.read(name)) for name in names
                            if re.fullmatch(r"classes\d*\.dex", name)))
    assert b"io.a10vm.START_NATIVE_DISPLAY" in strings
    assert b"Lio/a10vm/guestruntime/GuestRuntime;" in strings
    assert b"Lio/a10vm/guestruntime/GuestDisplayPower;" in strings
    for removed in (b"Lio/a10vm/runtime/NativeEngine;", b"Lio/a10vm/runtime/QmpClient;",
                    b"Lio/a10vm/display/VmDisplay;", b"Lio/a10vm/core/RfbClient;",
                    b"Lio/a10vm/core/QemuArguments;", b"su", b"/system/bin/su"):
        assert removed not in strings, removed
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temporary:
        renderer = Path(temporary) / "renderer.so"
        renderer.write_bytes(archive.read("lib/arm64-v8a/liba10vm-desktop-window.so"))
        symbols = subprocess.check_output(["readelf", "--dyn-syms", "--wide", str(renderer)], text=True)
        jni = {match.group(1) for match in re.finditer(r"Java_io_a10vm_nativedisplay_WindowBridge_(\w+)", symbols)}
        assert jni == {"create", "attach", "detach", "tap", "touch", "requestExit", "metrics", "intervals",
                       "resetTimings", "error", "description", "destroy", "displayMode"}, sorted(jni)
        assert "Java_io_a10vm_containerprobe_WindowBridge_" not in symbols

signer = shutil.which("apksigner")
if not signer:
    signer = str(Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk"))) / "build-tools/35.0.0/apksigner")
signature = subprocess.check_output([signer, "verify", "--verbose", "--print-certs", str(apk)], text=True)
assert "Verified using v2 scheme (APK Signature Scheme v2): true" in signature
lint = ET.parse(ROOT / "app/build/reports/lint-results-debug.xml").getroot()
counts = {severity: sum(issue.get("severity") == severity for issue in lint.iter("issue"))
          for severity in ("Error", "Fatal", "Warning")}
assert counts["Error"] == counts["Fatal"] == 0, counts
with apk.open("rb") as stream:
    apk_hash = hashlib.file_digest(stream, "sha256").hexdigest()
report = {"passed": True, "runtimeProfile": runtime.get("runtimeProfile", "android10"),
          "backend": expected["backend"], "rootRequired": False,
          "desktopImplemented": True, "desktopVerified": False,
          "apkRunVerified": False, "apk": {"path": str(apk.relative_to(ROOT)), "bytes": apk.stat().st_size,
          "versionName": version_name, "versionCode": version_code,
          "sha256": apk_hash, "v2SignatureVerified": True,
          "nativeFilesVerified": len(required), "runtimeDataFilesVerified": len(data_names),
          "systemApksVerified": len(system_apks),
          "jniExportsVerified": len(jni), "qemuPackaged": False, "tcgPackaged": False, "rfbPackaged": False,
          "guestImagePackaged": False}, "lint": counts, "inputs": expected, "runtimeInputs": runtime,
          "artIntegrated": True, "artGuestSdk": runtime["guestSdk"]}
destination = ROOT / "artifacts/container/graphics" / ("miui12-apk-report.json" if rom else "native-display-apk-report.json")
destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: report[key] for key in ("passed", "apk", "lint")}, indent=2))
