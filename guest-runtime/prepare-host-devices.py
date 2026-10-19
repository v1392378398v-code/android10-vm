#!/usr/bin/env python3
"""Extract device HAL link inputs before the desktop dependency closure exists."""
from prepare import ROOT, extract

OUT = ROOT / "artifacts/container/host-devices/lib"
PACKAGES = ("sensors@1.0", "vibrator@1.0", "health@1.0", "health@2.0")


def main():
    for package in PACKAGES:
        name = "android.hardware." + package + ".so"
        target = OUT / name
        for directory in ("/system/lib64", "/system/lib64/vndk-29", "/vendor/lib64"):
            if extract(directory + "/" + name, target):
                break
        else:
            raise RuntimeError("Missing host device HAL link input: " + name)


if __name__ == "__main__":
    main()
