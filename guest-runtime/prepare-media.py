#!/usr/bin/env python3
"""Collect the ARM64 libraries used to build original Android 10 media services."""
import json
import shutil

from prepare import APEX, ROOT, digest, extract, needed

OUT = ROOT / "artifacts/container/media/lib"
LIBRARIES = (
    "libbase libaudioclient libbinder libcamera_client libcodec2_client libcrypto libcutils "
    "libdl libgui libhidlbase libhidltransport libhidlmemory liblog libmedia libmedia_omx "
    "libmediadrm libmediametrics libmediautils libmemunreachable libnetd_client libpowermanager "
    "libstagefright libstagefright_foundation libstagefright_omx libutils libui libselinux "
    "libandroidicu libmediandk libavservices_minijail libc++ libc libm libunwind "
    "android.hardware.media.c2@1.0 android.hardware.media.omx@1.0 "
    "android.hardware.cas@1.0 android.hardware.cas.native@1.0 "
    "android.hidl.allocator@1.0 android.hidl.memory@1.0"
).split()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pending = [name + ".so" for name in LIBRARIES]
    seen = set()
    records = []
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        target = OUT / name
        for component in ("framework", "art"):
            source = ROOT / "artifacts/container" / component / "lib" / name
            if source.is_file():
                shutil.copyfile(source, target)
                break
        else:
            for directory in (APEX + "/lib64", "/system/lib64", "/system/lib64/vndk-29",
                              "/system/lib64/vndk-sp-29", "/vendor/lib64",
                              "/system/apex/com.android.media/lib64",
                              "/system/apex/com.android.media.swcodec/lib64"):
                source = directory + "/" + name
                if extract(source, target):
                    break
            else:
                raise RuntimeError("Missing ARM64 media dependency: " + name)
        with target.open("rb") as stream:
            header = stream.read(20)
        if header[:6] != b"\x7fELF\x02\x01" or header[18:20] != b"\xb7\x00":
            raise RuntimeError("Expected ARM64 media dependency: " + name)
        seen.add(name)
        records.append({"name": name, "source": str(source), "sha256": digest(target)})
        pending.extend(needed(target))
    (OUT.parent / "dependencies.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print("ARM64 media build dependencies:", len(records))


if __name__ == "__main__":
    main()
