#!/usr/bin/env python3
"""Verify init directory restoration and compatible seccomp policy merging."""
from pathlib import Path
import tempfile
import unittest

from rom_runtime_profile import init_data_directories, paired_audio_links, transport_policy, rom_properties


class ProfileCompatibilityTest(unittest.TestCase):
    def test_first_api_level_comes_from_rom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "system").mkdir()
            (root / "vendor").mkdir()
            (root / "system/build.prop").write_text(
                "ro.build.version.sdk=29\nro.product.cpu.abilist=arm64-v8a\n")
            vendor = root / "vendor/build.prop"
            for level in (28, 29, 30):
                with self.subTest(level=level):
                    vendor.write_text("ro.product.first_api_level=" + str(level) + "\n")
                    self.assertEqual(rom_properties(root)["ro.product.first_api_level"], str(level))
            vendor.write_text("")
            self.assertEqual(rom_properties(root)["ro.product.first_api_level"], "29")

    def test_rom_property_aliases_stay_inside_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "system").mkdir()
            (root / "system/build.prop").write_text(
                "ro.build.version.sdk=29\nro.product.cpu.abilist=arm64-v8a\n")
            (root / "vendor/odm/etc").mkdir(parents=True)
            (root / "vendor/odm/etc/build.prop").write_text("ro.product.odm.model=odm-model\n")
            (root / "odm").mkdir()
            (root / "odm/etc").symlink_to("/vendor/odm/etc")
            self.assertEqual(rom_properties(root)["ro.product.model"], "odm-model")

    def test_rom_properties_derive_partition_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "system").mkdir()
            (root / "vendor").mkdir()
            (root / "system/build.prop").write_text(
                "ro.build.version.sdk=29\nro.product.cpu.abilist=arm64-v8a,armeabi-v7a\n"
                "ro.product.system.device=system-device\nro.product.system.model=system-model\n")
            (root / "vendor/build.prop").write_text(
                "ro.product.vendor.device=vendor-device\nro.product.vendor.model=vendor-model\n")
            properties = rom_properties(root)
            self.assertEqual(properties["ro.product.device"], "vendor-device")
            self.assertEqual(properties["ro.product.model"], "vendor-model")
            self.assertEqual(properties["ro.product.cpu.abilist"], "arm64-v8a")
            (root / "system/build.prop").write_text("ro.build.version.sdk=30\nro.product.cpu.abilist=arm64-v8a\n")
            with self.assertRaises(ValueError):
                rom_properties(root)

    def test_init_directories_keep_user_data_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "init.miui.rc").write_text("on post-fs-data\n    mkdir /data/system/theme 0775 theme theme\n"
                "    mkdir /data/data 0771 system system\n    mkdir /data/data/pkg/cache 0771 system system\n"
                "    write /sys/example \\\n        value\n    mkdir /data/${dynamic} 0755 root root\n"
                "    mkdir /data/../system 0755 root root\n")
            self.assertEqual(init_data_directories(root), {"data/system/theme", "data/user/0", "data/user/0/pkg/cache"})

    def test_transport_policy_preserves_existing_filters(self):
        merged = transport_policy("# original\nsocket: arg0 == 1\nioctl: arg1 == 0xc0306201\ngetuid: 1\n",
                                  "socket: arg0 == 1\ngetuid: 1\nsendmsg: 1\nrecvmsg: 1\n")
        self.assertEqual(merged.count("socket:"), 1)
        self.assertEqual(merged.count("getuid:"), 1)
        self.assertIn("ioctl: arg1 == 0xc0306201\n", merged)
        self.assertIn("sendmsg: 1\n", merged)
        self.assertIn("readlinkat: 1\n", merged)

    def test_audio_implementations_follow_host_bridge_versions(self):
        hw = "rootfs/vendor/lib64/hw/"
        old = "android.hardware.audio@4.0-impl.so"
        newer = "android.hardware.audio@5.0-impl.so"
        bridge = [{"guestPath": "/vendor/lib64/hw/" + old, "logical": "host-audio"}]
        paired, disabled = paired_audio_links([
            {"path": hw + old, "logical": "rom-audio4"},
            {"path": hw + newer, "logical": "rom-audio5"},
            {"path": hw + "gralloc.ranchu.so", "logical": "gralloc"}], bridge)
        self.assertEqual(paired[0]["logical"], "host-audio")
        self.assertEqual(paired[1]["logical"], "gralloc")
        self.assertEqual(disabled, [hw + newer])
        self.assertEqual(paired_audio_links(paired, bridge), (paired, []))


if __name__ == "__main__":
    unittest.main()
