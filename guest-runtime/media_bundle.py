"""Android media services, dynamic codec plugins, sounds and trust resources."""
import posixpath
import stat


PROGRAMS = {
    "media": "/system/bin/mediaserver",
    "media-extractor": "/system/bin/mediaextractor",
    "media-metrics": "/system/bin/mediametrics",
    "media-drm": "/system/bin/mediadrmserver",
    "drm": "/system/bin/drmserver",
    "media-omx": "/vendor/bin/hw/android.hardware.media.omx@1.0-service",
    "media-codec": "/system/apex/com.android.media.swcodec/bin/mediaswcodec",
}


def resources(inventory):
    paths, libraries = [], {}
    for directory in ("/system/etc/security/cacerts", "/system/media/audio", "/system/product/media/audio",
                      "/system/apex/com.android.media/etc", "/system/apex/com.android.media.swcodec/etc",
                      "/system/etc/seccomp_policy", "/vendor/etc/seccomp_policy"):
        for path, mode in inventory.walk(directory):
            if stat.S_ISREG(mode):
                paths.append(path)
    paths.append("/system/apex/com.android.media.swcodec/apex_manifest.json")
    for directory in ("/vendor/etc", "/system/etc"):
        for path, mode in inventory.walk(directory):
            if stat.S_ISREG(mode) and posixpath.basename(path).startswith(("media_codecs", "media_profiles")) and path.endswith(".xml"):
                paths.append(path)
    for directory in ("/system/apex/com.android.media/lib64/extractors", "/system/apex/com.android.media.swcodec/lib64", "/vendor/lib64/soundfx"):
        for path, mode in inventory.walk(directory):
            name = posixpath.basename(path)
            if stat.S_ISREG(mode) and name.endswith(".so") and ("/extractors/" in path or "/soundfx/" in path or name.startswith("libcodec2_soft_")):
                libraries[name] = path
    for path, mode in inventory.walk("/system/lib64"):
        name = posixpath.basename(path)
        if stat.S_ISREG(mode) and name.endswith(".so") and (name in ("libmedia_jni.so", "libsfplugin_ccodec.so") or
                name.startswith(("libstagefright_soft_", "libstagefright_softomx_", "libstagefrighthw"))):
            libraries[name] = path
    return paths, libraries
