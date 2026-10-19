"""Cover plugins loaded with dlopen rather than through ELF dependencies."""
import stat
import unittest

from media_bundle import resources


class Inventory:
    def __init__(self, paths):
        self.paths = paths

    def walk(self, directory):
        return [(path, stat.S_IFREG | 0o644) for path in self.paths
                if path.startswith(directory + "/")]


class MediaBundleTests(unittest.TestCase):
    def test_product_charging_sound_is_included(self):
        path = "/system/product/media/audio/ui/ChargingStarted.ogg"
        paths, _ = resources(Inventory([path]))
        self.assertIn(path, paths)

    def test_media_framework_jni_is_included(self):
        path = "/system/lib64/libmedia_jni.so"
        _, libraries = resources(Inventory([path]))
        self.assertEqual(libraries.get("libmedia_jni.so"), path)

    def test_stagefright_codec2_plugin_is_included(self):
        path = "/system/lib64/libsfplugin_ccodec.so"
        _, libraries = resources(Inventory([path]))
        self.assertEqual(libraries.get("libsfplugin_ccodec.so"), path)

    def test_omx_loader_and_components_are_included(self):
        paths = ["/system/lib64/" + name for name in (
            "libstagefrighthw.so", "libstagefright_softomx_plugin.so",
            "libstagefright_soft_aacdec.so", "libstagefright_soft_avcdec.so")]
        _, libraries = resources(Inventory(paths))
        self.assertEqual(set(libraries.values()), set(paths))

    def test_apex_extractors_and_codec2_components_are_included(self):
        paths = ["/system/apex/com.android.media/lib64/extractors/libmp4extractor.so",
                 "/system/apex/com.android.media.swcodec/lib64/libcodec2_soft_avcdec.so",
                 "/vendor/lib64/soundfx/libbundlewrapper.so"]
        _, libraries = resources(Inventory(paths))
        self.assertEqual(set(libraries.values()), set(paths))

    def test_unrelated_libraries_are_excluded(self):
        _, libraries = resources(Inventory(["/system/lib64/libunrelated.so"]))
        self.assertEqual(libraries, {})


if __name__ == "__main__":
    unittest.main()
