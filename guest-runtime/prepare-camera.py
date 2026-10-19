#!/usr/bin/env python3
"""Extract Android 10 camera service dependencies for the paired guest provider."""
from prepare import APEX, ROOT, extract, needed


def main():
    output = ROOT / "artifacts/container/camera"
    (output / "lib").mkdir(parents=True, exist_ok=True)
    server = output / "bin/cameraserver"
    server.parent.mkdir(parents=True, exist_ok=True)
    assert extract("/system/bin/cameraserver", server), "Missing Android 10 cameraserver"
    pending = ["android.hardware.camera.common@1.0.so", "android.hardware.camera.device@1.0.so",
               "android.hardware.camera.provider@2.4.so", "android.hardware.graphics.mapper@3.0.so",
               *needed(server)]
    seen = set()
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        seen.add(name)
        paired = next((ROOT / "artifacts/container" / component / "lib" / name
                       for component in ("framework", "runtime", "media")
                       if (ROOT / "artifacts/container" / component / "lib" / name).is_file()), None)
        if paired is not None:
            pending.extend(needed(paired))
            continue
        target = output / "lib" / name
        for directory in (APEX + "/lib64", "/system/lib64", "/system/lib64/vndk-29",
                          "/system/lib64/vndk-sp-29", "/vendor/lib64"):
            if extract(directory + "/" + name, target):
                break
        else:
            raise ValueError("Missing camera dependency: " + name)
        pending.extend(needed(target))
    print("Prepared Android 10 camera dependency closure:", len(seen))


if __name__ == "__main__":
    main()
