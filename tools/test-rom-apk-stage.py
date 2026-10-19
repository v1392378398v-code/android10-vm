#!/usr/bin/env python3
"""Check ROM staging preserves inputs and catches missing boot dependencies."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("stage", Path(__file__).with_name("stage-rom-apk.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RomApkStageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.prepared = self.directory / "prepared"
        self.assets = self.prepared / "assets/guest-runtime"
        self.assets.mkdir(parents=True)
        (self.assets / "guest.prop").write_text("ro.build.version.sdk=29\n")
        self.inputs = {"guestSdk": 29, "rootRequired": False, "romFramework": True,
            "rootfsAliases": {"apex/com.android.runtime": "/system/apex/com.android.runtime.release"},
            "files": [{"logical": name} for name in ("libqti_performance.so", "rom/system/xbin/shelld",
                                                     "liba10vm-rom-service-identity.so")], "data": []}
        self.manifest = self.prepared / "assets/guest-runtime-inputs.json"
        self.save()
        self.bootstrap = self.directory / "bootstrap.dex"
        self.bootstrap.write_bytes(b"dex\n035\0test")
        self.output = self.directory / "output"

    def save(self):
        self.manifest.write_text(json.dumps(self.inputs))

    def test_cached_seed_restores_rom_first_api_and_hash(self):
        seed = self.assets / "guest.prop"
        seed.write_text("ro.build.version.sdk=29\nro.product.first_api_level=29\nfixture.keep=1\n")
        source = self.assets / "rootfs/system/build.prop"
        source.parent.mkdir(parents=True)
        source.write_text("ro.build.version.sdk=29\nro.product.cpu.abilist=arm64-v8a\n")
        vendor = self.assets / "rootfs/vendor/build.prop"
        vendor.parent.mkdir(parents=True)
        vendor.write_text("ro.product.first_api_level=28\n")
        self.inputs["propertyFiles"] = ["/system/build.prop", "/vendor/build.prop"]
        self.inputs["data"].append({"name": "guest-runtime/guest.prop", "bytes": seed.stat().st_size,
                                   "sha256": hashlib.sha256(seed.read_bytes()).hexdigest()})
        self.save()
        original = seed.read_bytes()
        module.stage(self.prepared, self.bootstrap, self.output)
        actual_seed = (self.output / "assets/guest-runtime/guest.prop").read_bytes()
        self.assertIn(b"ro.product.first_api_level=28\n", actual_seed)
        self.assertIn(b"fixture.keep=1\n", actual_seed)
        self.assertEqual(seed.read_bytes(), original)
        manifest = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        item, = [entry for entry in manifest["data"] if entry["name"] == "guest-runtime/guest.prop"]
        self.assertEqual(item["bytes"], len(actual_seed))
        self.assertEqual(item["sha256"], hashlib.sha256(actual_seed).hexdigest())
        self.assertEqual(manifest["propertyCount"], 3)

    def test_stage_preserves_rom_and_hashes_bootstrap(self):
        original = self.manifest.read_bytes()
        module.stage(self.prepared, self.bootstrap, self.output, ("qti_performance",))
        actual = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assertEqual(actual["rootfsAliases"], self.inputs["rootfsAliases"])
        self.assertEqual(actual["romBoot"]["services"][0]["logical"], "rom/system/xbin/shelld")
        self.assertEqual(actual["data"][-1]["sha256"], hashlib.sha256(self.bootstrap.read_bytes()).hexdigest())
        self.assertEqual((self.output / "assets/guest-runtime/rom-bootstrap.dex").read_bytes(), self.bootstrap.read_bytes())

    def test_refresh_framework_and_webview_preserves_cached_rom(self):
        old = self.assets / "framework-check.dex"
        old.write_bytes(b"dex\n035\0old bootstrap")
        self.inputs["data"].append({"name": "guest-runtime/framework-check.dex", "sha256": "old"})
        self.save()
        framework = self.directory / "framework.dex"
        framework.write_bytes(b"dex\n035\0current application bootstrap")
        webview = self.directory / "webview.apk"
        with zipfile.ZipFile(webview, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"manifest")
            archive.writestr("lib/arm64-v8a/libwebviewchromium.so", b"ARM64 provider")
        hardware = [{"package": "fixture.sla", "interface": "fixture.sla@1.0::ISla", "instance": "default"}]
        module.stage(self.prepared, self.bootstrap, self.output, framework_dex=framework,
                     webview_apk=webview, webview_package="com.android.webview", hardware_applications=hardware)
        actual = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        entry = [item for item in actual["data"] if item["name"] == "guest-runtime/framework-check.dex"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["sha256"], hashlib.sha256(framework.read_bytes()).hexdigest())
        self.assertEqual(old.read_bytes(), b"dex\n035\0old bootstrap")
        path = "system/app/A10vmWebView/WebView.apk"
        self.assertEqual(actual["desktopPackages"][path], "/" + path)
        self.assertEqual((self.output / "assets/guest-runtime/rootfs" / path).read_bytes(), webview.read_bytes())
        self.assertEqual(actual["romBoot"]["webviewPackage"], "com.android.webview")
        self.assertEqual(actual["romBoot"]["hardwareApplications"], hardware)

    def test_invalid_framework_preserves_existing_output(self):
        self.output.mkdir()
        marker = self.output / "previous"
        marker.write_text("keep")
        framework = self.directory / "invalid.dex"
        framework.write_bytes(b"invalid DEX")
        with self.assertRaisesRegex(ValueError, "framework DEX"):
            module.stage(self.prepared, self.bootstrap, self.output, framework_dex=framework)
        self.assertEqual(marker.read_text(), "keep")

    def test_system_apk_override_preserves_source_and_refreshes_hash(self):
        path = "system/app/XiaomiAccount/XiaomiAccount.apk"
        original = self.assets / "rootfs" / path
        original.parent.mkdir(parents=True)
        original.write_bytes(b"original ROM APK")
        self.inputs["desktopPackages"] = {path: "/" + path}
        name = "guest-runtime/rootfs/" + path
        self.inputs["data"].append({"name": name, "sha256": "old"})
        self.save()
        updated = self.directory / "account.apk"
        with zipfile.ZipFile(updated, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"original manifest")
            archive.writestr("classes.dex", b"credential-aware login")
        module.stage(self.prepared, self.bootstrap, self.output, system_apk_overrides=[(path, updated)])
        self.assertEqual(original.read_bytes(), b"original ROM APK")
        self.assertEqual((self.output / "assets" / name).read_bytes(), updated.read_bytes())
        inputs = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        self.assertEqual(inputs["desktopPackages"], self.inputs["desktopPackages"])
        entry, = [entry for entry in inputs["data"] if entry["name"] == name]
        self.assertEqual(entry["sha256"], hashlib.sha256(updated.read_bytes()).hexdigest())
        self.assertEqual(entry["bytes"], updated.stat().st_size)

    def test_unknown_system_apk_preserves_existing_output(self):
        self.output.mkdir()
        marker = self.output / "previous"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "existing ROM system APK"):
            module.stage(self.prepared, self.bootstrap, self.output,
                         system_apk_overrides=[("system/app/Unknown.apk", self.directory / "missing.apk")])
        self.assertEqual(marker.read_text(), "keep")

    def test_webview_provider_requires_paired_apk(self):
        with self.assertRaisesRegex(ValueError, "paired"):
            module.stage(self.prepared, self.bootstrap, self.output, webview_package="com.android.webview")
        self.assertFalse(self.output.exists())

    def test_missing_identity_preserves_existing_output(self):
        self.inputs["files"].pop()
        self.save()
        self.output.mkdir()
        marker = self.output / "previous"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "identity bridge"):
            module.stage(self.prepared, self.bootstrap, self.output)
        self.assertEqual(marker.read_text(), "keep")

    def test_fdpp_uses_rom_daemon_arguments_and_guest_identity(self):
        self.inputs["files"].append({"logical": "rom/system/bin/fdpp", "name": "libfdpp-executable.so"})
        self.save()
        module.stage(self.prepared, self.bootstrap, self.output)
        actual = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        service = next(item for item in actual["romBoot"]["services"] if item["role"] == "rom-fdpp")
        self.assertEqual(service["logical"], "rom/system/bin/fdpp")
        self.assertEqual(service["arguments"], ["daemon"])
        self.assertEqual((service["uid"], service["gid"]), ("0", "1000"))
        self.assertEqual(service["preload"], "liba10vm-rom-service-identity.so")

    def test_missing_jni_stops_before_staging(self):
        with self.assertRaisesRegex(ValueError, "boot JNI"):
            module.stage(self.prepared, self.bootstrap, self.output, ("absent",))
        self.assertFalse(self.output.exists())

    def test_miui_storage_client_gets_vintf_declaration(self):
        sdk = self.assets / "rootfs/system/framework/vendor.xiaomi.hardware.mtdservice-V1.1-java.jar"
        sdk.parent.mkdir(parents=True)
        sdk.write_bytes(b"ROM HIDL client fixture")
        module.stage(self.prepared, self.bootstrap, self.output)
        name = "guest-runtime/rootfs/vendor/etc/vintf/manifest/a10vm-mtd-storage.xml"
        declaration = (self.output / "assets" / name).read_bytes()
        self.assertIn(b"@1.1::IMTService/default", declaration)
        inputs = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        item, = [item for item in inputs["data"] if item["name"] == name]
        self.assertEqual(item["sha256"], hashlib.sha256(declaration).hexdigest())
        self.assertEqual(item["bytes"], len(declaration))

    def test_other_rom_does_not_declare_miui_storage(self):
        module.stage(self.prepared, self.bootstrap, self.output)
        self.assertFalse((self.output / "assets/guest-runtime/rootfs/vendor/etc/vintf/manifest/a10vm-mtd-storage.xml").exists())

    def test_hidden_theme_assets_keep_guest_paths(self):
        name = "guest-runtime/rootfs/system/media/theme/.data/icon"
        source = self.prepared / "assets" / name
        source.parent.mkdir(parents=True)
        source.write_bytes(b"theme")
        self.inputs["data"].append({"name": name, "bytes": 5, "sha256": hashlib.sha256(b"theme").hexdigest()})
        self.save()
        module.stage(self.prepared, self.bootstrap, self.output)
        actual = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())["data"][0]
        self.assertEqual(actual["installPath"], "rootfs/system/media/theme/.data/icon")
        self.assertFalse(any(part.startswith(".") for part in Path(actual["name"]).parts))
        self.assertEqual((self.output / "assets" / actual["name"]).read_bytes(), source.read_bytes())

    def test_cached_profile_pairs_rom_binder_and_current_network_bridge(self):
        filename = "liba10vm-guest-libbinder.so"
        source = self.prepared / "jniLibs/arm64-v8a" / filename
        source.parent.mkdir(parents=True)
        source.write_bytes(b"baseline binder")
        self.inputs["files"].append({"logical": "libbinder.so", "name": filename,
                                   "bytes": source.stat().st_size, "sha256": "old"})
        self.save()
        rom = self.directory / "libbinder.so"
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02\x01"
        header[18:20] = b"\xb7\x00"
        rom.write_bytes(header + b"ROM Binder with package sensor methods")
        netd_name = "liba10vm-guest-libnetd_client.so"
        netd_source = source.with_name(netd_name)
        netd_source.write_bytes(b"old network bridge")
        self.inputs["files"].append({"logical": "libnetd_client.so", "name": netd_name,
                                   "bytes": netd_source.stat().st_size, "sha256": "old"})
        self.save()
        netd = self.directory / "libnetd_client.so"
        netd.write_bytes(header + b"current network bridge with tagSocketWithPid")
        module.stage(self.prepared, self.bootstrap, self.output, rom_binder=rom, host_netd=netd)
        actual = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        binder = next(item for item in actual["files"] if item["logical"] == "libbinder.so")
        self.assertEqual((self.output / "jniLibs/arm64-v8a" / filename).read_bytes(), rom.read_bytes())
        self.assertEqual(binder["sha256"], hashlib.sha256(rom.read_bytes()).hexdigest())
        self.assertEqual(binder["bytes"], rom.stat().st_size)
        self.assertEqual(source.read_bytes(), b"baseline binder")
        network = next(item for item in actual["files"] if item["logical"] == "libnetd_client.so")
        self.assertEqual((self.output / "jniLibs/arm64-v8a" / netd_name).read_bytes(), netd.read_bytes())
        self.assertEqual(network["sha256"], hashlib.sha256(netd.read_bytes()).hexdigest())
        self.assertEqual(network["bytes"], netd.stat().st_size)
        self.assertEqual(netd_source.read_bytes(), b"old network bridge")
        self.assertEqual(actual["apkNativeOverrides"]["libnetd_client.so"]["sha256"], network["sha256"])

    def test_existing_transport_bridge_override_updates_only_staged_copy(self):
        name = "liba10vm-guest-liba10binder.so"
        source = self.prepared / "jniLibs/arm64-v8a" / name
        source.parent.mkdir(parents=True)
        source.write_bytes(b"previous transport")
        self.inputs["files"].append({"logical": "liba10binder.so", "name": name,
                                   "bytes": source.stat().st_size, "sha256": "old"})
        self.save()
        current = self.directory / "liba10binder.so"
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02\x01"
        header[18:20] = b"\xb7\x00"
        current.write_bytes(header + b"current Binder security context transport")
        module.stage(self.prepared, self.bootstrap, self.output, native_overrides=[("liba10binder.so", current)])
        actual = json.loads((self.output / "assets/guest-runtime-inputs.json").read_text())
        transport = next(item for item in actual["files"] if item["logical"] == "liba10binder.so")
        self.assertEqual((self.output / "jniLibs/arm64-v8a" / name).read_bytes(), current.read_bytes())
        self.assertEqual(transport["sha256"], hashlib.sha256(current.read_bytes()).hexdigest())
        self.assertEqual(source.read_bytes(), b"previous transport")


if __name__ == "__main__":
    unittest.main()
