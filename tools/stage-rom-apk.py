#!/usr/bin/env python3
"""Stage the verified MIUI trial as separate APK inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from rom_runtime_profile import arm64, rom_properties

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "guest-runtime/build/rom-prepared/miui12"


def stage(prepared, bootstrap, output=OUTPUT, boot_jni=(), rom_binder=None, host_netd=None, native_overrides=(),
          framework_dex=None, webview_apk=None, webview_package=None, hardware_applications=(), system_apk_overrides=(),
          host_camera=False, keyboard=False):
    prepared, bootstrap, output = prepared.resolve(strict=True), bootstrap.resolve(strict=True), output.resolve()
    inputs = json.loads((prepared / "assets/guest-runtime-inputs.json").read_text())
    if not inputs.get("romFramework") or inputs["guestSdk"] != 29 or inputs["rootRequired"]:
        raise ValueError("Expected the rootless Android 10 ROM trial inputs")
    first_api_level = rom_properties(prepared / "assets/guest-runtime/rootfs")["ro.product.first_api_level"] \
        if inputs.get("propertyFiles") else None
    native = {item["logical"] for item in inputs["files"]}
    for name in boot_jni:
        if "lib" + name + ".so" not in native:
            raise ValueError("Missing ROM boot JNI: " + name)
    if not bootstrap.read_bytes().startswith(b"dex\n"):
        raise ValueError("Expected a ROM bootstrap DEX")
    if framework_dex is not None and not framework_dex.read_bytes().startswith(b"dex\n"):
        raise ValueError("Expected a framework DEX")
    if bool(webview_apk) != bool(webview_package):
        raise ValueError("WebView APK and package must be paired")
    if webview_apk is not None:
        with zipfile.ZipFile(webview_apk) as archive:
            archive.getinfo("AndroidManifest.xml")
            archive.getinfo("lib/arm64-v8a/libwebviewchromium.so")
    for path, source in system_apk_overrides:
        if path not in inputs.get("desktopPackages", {}):
            raise ValueError("Expected an existing ROM system APK: " + path)
        with zipfile.ZipFile(source) as archive:
            archive.getinfo("AndroidManifest.xml")
    replacements = []
    for logical, source in (("libbinder.so", rom_binder), ("libnetd_client.so", host_netd), *native_overrides):
        if source is None:
            continue
        source = source.resolve(strict=True)
        item = next((item for item in inputs["files"] if item["logical"] == logical), None)
        if item is None or not arm64(source):
            raise ValueError("Expected an ARM64 library: " + logical)
        replacements.append((item, source))
    if output == prepared or output in prepared.parents or prepared in output.parents:
        raise ValueError("ROM staging must be separate from the prepared input")
    services = []
    if "rom/system/xbin/shelld" in native:
        if "liba10vm-rom-service-identity.so" not in native:
            raise ValueError("Missing ROM service identity bridge")
        services.append({"role": "rom-shelld", "logical": "rom/system/xbin/shelld", "uid": "0", "gid": "0",
                         "preload": "liba10vm-rom-service-identity.so"})
    if "rom/system/bin/fdpp" in native:
        if "liba10vm-rom-service-identity.so" not in native:
            raise ValueError("Missing ROM service identity bridge")
        services.append({"role": "rom-fdpp", "logical": "rom/system/bin/fdpp", "uid": "0", "gid": "1000",
                         "preload": "liba10vm-rom-service-identity.so", "arguments": ["daemon"]})
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(prepared, output)
    for item, source in replacements:
        target = output / "jniLibs/arm64-v8a" / item["name"]
        shutil.copyfile(source, target)
        item.update(bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        inputs.setdefault("apkNativeOverrides", {})[item["logical"]] = {"source": str(source), "sha256": item["sha256"]}
    # AAPT filters dot directories used by MIUI themes; encode only the APK asset name.
    for item in inputs["data"]:
        name = item["name"]
        if not any(part.startswith(".") for part in Path(name).parts):
            continue
        encoded = "guest-runtime/rom-encoded/" + hashlib.sha256(name.encode()).hexdigest() + ".asset"
        target = output / "assets" / encoded
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(output / "assets" / name, target)
        item.setdefault("installPath", name.removeprefix("guest-runtime/"))
        item["name"] = encoded
    def record_asset(name):
        target = output / "assets" / name
        inputs["data"] = [item for item in inputs["data"] if item["name"] != name]
        inputs["data"].append({"name": name, "bytes": target.stat().st_size,
                               "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})

    def install_asset(name, source):
        target = output / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        record_asset(name)

    if first_api_level is not None:
        seed = output / "assets/guest-runtime/guest.prop"
        properties = dict(line.split("=", 1) for line in seed.read_text(encoding="utf-8").splitlines())
        properties["ro.product.first_api_level"] = first_api_level
        seed.write_text("".join(k + "=" + v + "\n" for k, v in properties.items()), encoding="utf-8")
        record_asset("guest-runtime/guest.prop")

    install_asset("guest-runtime/rom-bootstrap.dex", bootstrap)
    if framework_dex is not None:
        install_asset("guest-runtime/framework-check.dex", framework_dex)
    for path, source in system_apk_overrides:
        install_asset("guest-runtime/rootfs/" + path, source)
    if (output / "assets/guest-runtime/rootfs/system/framework/vendor.xiaomi.hardware.mtdservice-V1.1-java.jar").is_file():
        install_asset("guest-runtime/rootfs/vendor/etc/vintf/manifest/a10vm-mtd-storage.xml",
                      ROOT / "guest-runtime/native/miui-mtd-storage.xml")
    if webview_apk is not None:
        path = "system/app/A10vmWebView/WebView.apk"
        install_asset("guest-runtime/rootfs/" + path, webview_apk)
        inputs.setdefault("desktopPackages", {})[path] = "/" + path
    inputs.update(propertyCount=len((output / "assets/guest-runtime/guest.prop").read_text().splitlines()),
                  runtimeProfile="miui12", romBoot={"bootstrapDex": "rom-bootstrap.dex",
                  "bootJni": list(boot_jni), "services": services})
    if webview_package:
        inputs["romBoot"]["webviewPackage"] = webview_package
    if hardware_applications:
        inputs["romBoot"]["hardwareApplications"] = list(hardware_applications)
    (output / "assets/guest-runtime-inputs.json").write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    if any(item.get("installPath", item["name"].removeprefix("guest-runtime/")) ==
           "rootfs/system/framework/services.jar" for item in inputs["data"]):
        import sys
        sys.path.insert(0, str(ROOT / "guest-runtime"))
        from package_queries_bundle import stage_package_queries
        inputs = stage_package_queries(output)
    if host_camera or inputs.get("hostCameraBridge"):
        import sys
        sys.path.insert(0, str(ROOT / "guest-runtime"))
        from camera_bundle import stage_camera
        stage_camera(output)
        inputs = json.loads((output / "assets/guest-runtime-inputs.json").read_text())
    if keyboard:
        import sys
        sys.path.insert(0, str(ROOT / "guest-runtime"))
        from keyboard_bundle import stage_keyboard
        stage_keyboard(output)
        inputs = json.loads((output / "assets/guest-runtime-inputs.json").read_text())
    return {"prepared": str(output), "nativeFiles": len(inputs["files"]), "dataFiles": len(inputs["data"]),
            "package": "io.a10vm.miui", "romBoot": inputs["romBoot"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prepared", type=Path)
    parser.add_argument("bootstrap", type=Path)
    parser.add_argument("--boot-jni", action="append", default=[])
    parser.add_argument("--rom-binder", type=Path, help="Pair a cached ROM profile with its original Binder ABI")
    parser.add_argument("--host-netd", type=Path, help="Use the current host network bridge with cached ROM inputs")
    parser.add_argument("--framework-dex", type=Path, help="Use the current application/runtime bootstrap classes")
    parser.add_argument("--host-camera", action="store_true", help="Bundle the paired ordinary-UID host camera bridge")
    parser.add_argument("--webview-apk", type=Path, help="Bundle an Android 10 compatible standalone ARM64 WebView")
    parser.add_argument("--webview-package", help="Select the bundled WebView provider in this ROM")
    parser.add_argument("--hardware-application", action="append", default=[], metavar="PACKAGE=INTERFACE/INSTANCE",
                        help="Start an optional persistent ROM application only when its HAL is registered")
    parser.add_argument("--native-override", action="append", default=[], metavar="LOGICAL=PATH",
                        help="Refresh an existing native bridge in cached ROM inputs")
    parser.add_argument("--system-apk-override", action="append", default=[], metavar="ROM_PATH=APK",
                        help="Refresh an existing system APK while preserving its ROM package path")
    args = parser.parse_args()
    print(json.dumps(stage(args.prepared, args.bootstrap, boot_jni=args.boot_jni,
                           rom_binder=args.rom_binder, host_netd=args.host_netd,
                           framework_dex=args.framework_dex, webview_apk=args.webview_apk,
                           host_camera=args.host_camera, keyboard=True,
                           webview_package=args.webview_package,
                           hardware_applications=[{"package": name, "interface": interface, "instance": instance}
                               for name, (interface, instance) in
                               ((name, service.rsplit("/", 1)) for name, service in
                                (value.split("=", 1) for value in args.hardware_application))],
                           native_overrides=[(name, Path(path)) for name, path in
                                             (value.split("=", 1) for value in args.native_override)],
                           system_apk_overrides=[(name, Path(path)) for name, path in
                                                 (value.split("=", 1) for value in args.system_apk_override)]), indent=2))


if __name__ == "__main__":
    main()
