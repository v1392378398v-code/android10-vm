#!/usr/bin/env python3
"""Verify the AOSP APK/native pair, old system assets, and repeatable staging."""
import json
from pathlib import Path
import tempfile
import unittest

from keyboard_bundle import SOURCE_PREPARED, ROM_APK, stage_keyboard


class KeyboardBundleTest(unittest.TestCase):
    def test_aosp_keyboard_has_native_library_and_repeatable_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = Path(temporary)
            manifest = prepared / "assets/guest-runtime-inputs.json"
            manifest.parent.mkdir()
            old_apk = prepared / "assets/guest-runtime/rootfs/system/app/A10vmKeyboard/Keyboard.apk"
            old_apk.parent.mkdir(parents=True)
            old_apk.write_bytes(b"old-keyboard")
            manifest.write_text(json.dumps({
                "runtimeProfile": "miui12", "files": [], "nativeLinks": [],
                "data": [{"name": str(old_apk.relative_to(prepared / "assets"))}],
                "desktopPackages": {"system/app/A10vmKeyboard/Keyboard.apk": "/system/app/A10vmKeyboard/Keyboard.apk"},
            }))
            stage_keyboard(prepared)
            inputs = json.loads(manifest.read_text())
            libraries = [item for item in inputs["files"] if item["logical"] == "libjni_latinime.so"]
            self.assertEqual(len(libraries), 1, "A preinstalled keyboard must include its native library")
            library = libraries[0]
            native = prepared / "jniLibs/arm64-v8a" / library["name"]
            baseline = json.loads((SOURCE_PREPARED / "assets/guest-runtime-inputs.json").read_text())
            source = next(item for item in baseline["files"] if item["logical"] == library["logical"])
            self.assertEqual(native.read_bytes(), (SOURCE_PREPARED / "jniLibs/arm64-v8a" / source["name"]).read_bytes())
            self.assertIn({"path": "rootfs/system/app/A10vmKeyboard/lib/arm64/libjni_latinime.so",
                           "logical": "libjni_latinime.so"}, inputs["nativeLinks"])
            self.assertEqual(inputs["desktopPackages"][ROM_APK[1:]], ROM_APK)
            self.assertFalse(old_apk.exists())
            self.assertNotIn("system/app/A10vmKeyboard/Keyboard.apk", inputs["desktopPackages"])
            self.assertEqual(inputs["bundledInputMethod"]["package"], "com.android.inputmethod.latin")
            stage_keyboard(prepared)
            self.assertEqual(inputs, json.loads(manifest.read_text()))


if __name__ == "__main__":
    unittest.main()
