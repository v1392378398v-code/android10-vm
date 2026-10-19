#!/usr/bin/env python3
"""Check installed guest mapper descriptors without starting the desktop."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hal-override", help="Guest path of a diagnostic HAL preload")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}

    def device(command):
        return subprocess.run(["adb", "-s", args.serial, "exec-out", command], env=env,
                              capture_output=True, text=True, check=True, timeout=10).stdout

    linker = device("run-as io.a10vm.miui readlink files/guest-runtime/lib/ld-android.so").strip()
    native = str(Path(linker).parent)
    manifest = json.loads((ROOT / "guest-runtime/build/rom-prepared/miui12/assets/guest-runtime-inputs.json").read_text())
    names = {item["logical"]: native + "/" + item["name"] for item in manifest["files"]}
    directory = "/data/data/io.a10vm.miui/files/guest-runtime"
    hal = args.hal_override or names["liba10vm-hal-modules.so"]
    values = {"PATH": "/system/bin", "A10VM_ROOTFS": directory + "/rootfs", "A10VM_HOST_ROOT": native,
              "A10VM_STATE_ROOT": str(Path(directory).parent), "A10VM_LD_CONFIG": directory + "/ld.config.txt",
              "A10VM_PROPERTIES": directory + "/boot-properties", "LD_PRELOAD": ":".join((
                  names["liba10vm-property-client.so"], hal, names["liba10vm-guest-devices.so"],
                  names["liba10vm-guest-log.so"]))}
    report = {"passed": True, "desktopStarted": False, "candidates": []}
    for suffix in ("qti-display", "2.1"):
        path = "/vendor/lib64/hw/android.hardware.graphics.mapper@2.0-impl-" + suffix + ".so"
        script = "export " + shlex.join([key + "=" + value for key, value in values.items()])
        script += "\nexec " + shlex.join([linker, directory + "/mapper-descriptor-check", path])
        output = device("run-as io.a10vm.miui /system/bin/sh -c " + shlex.quote(script))
        (args.output / (suffix + ".log")).write_text(output, encoding="utf-8")
        passed = "mapper_paired_descriptor=passed\n" in output
        report["candidates"].append({"requested": path, "passed": passed})
        report["passed"] &= passed
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
