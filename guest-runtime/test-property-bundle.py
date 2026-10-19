#!/usr/bin/env python3
"""Check image-file restoration, runtime overrides and Android product derivation."""
from pathlib import Path
import tempfile
import unittest

from property_bundle import merge, parse


class PropertyBundleTests(unittest.TestCase):
    def test_partition_precedence_and_runtime_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "system").mkdir()
            (root / "vendor").mkdir()
            (root / "system/build.prop").write_text(
                "ro.product.system.model=system-model\nro.product.system.brand=system-brand\n"
                "ro.build.id=QP1A\nro.build.version.release=10\nro.build.version.incremental=123\n"
                "ro.build.type=userdebug\nro.build.tags=test-keys\nro.product.system.name=product\n"
                "ro.product.system.device=device\nro.build.date.utc=1757251109\n", encoding="utf-8")
            (root / "vendor/build.prop").write_text(
                "ro.product.vendor.model=vendor-model\nro.hardware=redroid\n", encoding="utf-8")
            overrides = root / "overrides.prop"
            overrides.write_text("ro.hardware=a10vm\nro.product.cpu.abilist32=\n", encoding="utf-8")
            sources = ["/system/build.prop", "/vendor/build.prop"]
            properties = merge(root, sources, overrides)
            self.assertEqual(properties["ro.product.model"], "vendor-model")
            self.assertEqual(properties["ro.hardware"], "a10vm")
            self.assertEqual(properties["ro.build.date.utc"], "1757251109")
            self.assertEqual(properties["ro.product.cpu.abilist32"], "")
            self.assertEqual(properties["ro.build.fingerprint"],
                             "system-brand/product/device:10/QP1A/123:userdebug/test-keys")
            overrides.write_text("ro.product.property_source_order=system,vendor\n"
                                 "ro.product.brand=explicit\nro.build.fingerprint=explicit-fingerprint\n",
                                 encoding="utf-8")
            properties = merge(root, sources, overrides)
            self.assertEqual(properties["ro.product.model"], "system-model")
            self.assertEqual(properties["ro.product.brand"], "explicit")
            self.assertEqual(properties["ro.build.fingerprint"], "explicit-fingerprint")

    def test_comments_duplicates_and_empty_values(self):
        self.assertEqual(parse("# comment\n ro.model = first\nro.model=last\nro.empty=\n"),
                         {"ro.model": "last", "ro.empty": ""})
        with self.assertRaises(ValueError):
            parse("ro.broken\n")


if __name__ == "__main__":
    unittest.main()
