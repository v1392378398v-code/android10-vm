#!/usr/bin/env python3
"""Check legacy OEM accounts and real ART initialization as an ordinary app UID."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="oem-accounts")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid label")
    assert os.getuid() >= 10000
    out = ROOT / "artifacts/performance"
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "rootRequired": False, "cases": []}
    native = ROOT / "artifacts/container/runtime"
    with tempfile.TemporaryDirectory(prefix="oem-accounts-", dir=out) as directory:
        runtime = RuntimeInstance(directory, {"oem-accounts-check": native / "bin/oem-accounts-check",
                                             "libc.so": native / "lib/libc.so"})
        seed = dict(line.split("=", 1) for line in (runtime.directory / "guest.prop").read_text().splitlines())
        for level in (28, 29, 30, None, 0):
            label = str(level) if level is not None else "missing"
            properties = dict(seed)
            if level is None:
                properties.pop("ro.product.first_api_level", None)
            else:
                properties["ro.product.first_api_level"] = str(level)
            supplied = runtime.directory / ("first-api-" + label + ".prop")
            supplied.write_text("".join(k + "=" + v + "\n" for k, v in properties.items()), encoding="utf-8")
            area = runtime.directory / ("properties-" + label)
            subprocess.run([str(runtime.native("seed-properties")), str(area), str(supplied)],
                           env={"PATH": "/system/bin"}, capture_output=True, check=True, timeout=5)
            environment = dict(runtime.environment, A10VM_PROPERTIES=str(area), A10VM_GUEST_UID="9802",
                               A10VM_GUEST_GID="9802")
            result = subprocess.run([str(runtime.native("ld-android.so")), str(runtime.native("oem-accounts-check")),
                                     "legacy" if level == 28 else "modern"], env=environment,
                                    capture_output=True, text=True, timeout=10)
            text = result.stdout + result.stderr
            (out / (args.label + "-" + label + ".log")).write_text(text, encoding="utf-8")
            checks = re.findall(r"^CHECK\t([^\t]+)\t(\d+)\t([01])$", text, re.M)
            report["cases"].append({"firstApiLevel": level, "passed": result.returncode == 0 and
                "oem_accounts_complete=1\n" in text, "checks": len(checks),
                "failedChecks": [name + ":" + uid for name, uid, ok in checks if ok != "1"]})
            if level == 28:
                environment = dict(runtime.framework_environment(), **environment)
                environment["A10VM_HWBINDER_PATH"] = str(runtime.directory / "hwbinder.sock")
                environment["A10VM_BOOT_IMAGE_START_NS"] = str(time.clock_gettime_ns(time.CLOCK_BOOTTIME))
                command = [runtime.native("ld-android.so"), runtime.native("app_process64"), "-Xnoimage-dex2oat",
                    "-Ximage:/system/framework/missing-boot-image.art", "-Djava.library.path=" + str(runtime.libraries),
                    "/system/bin", "--application", "io.a10vm.guest.BootImageCheck", "absent"]
                with (out / (args.label + "-broker.log")).open("w", encoding="utf-8") as stream, \
                        (out / (args.label + "-hwbinder.log")).open("w", encoding="utf-8") as hardware:
                    broker = subprocess.Popen([str(runtime.native("ld-android.so")),
                        str(runtime.native("binder-broker")), str(runtime.directory / "binder.sock")],
                        env=runtime.registry_environment(), stdout=stream, stderr=subprocess.STDOUT)
                    hwbroker = subprocess.Popen([str(runtime.native("ld-android.so")),
                        str(runtime.native("binder-broker")), str(runtime.directory / "hwbinder.sock")],
                        env=runtime.registry_environment(), stdout=hardware, stderr=subprocess.STDOUT)
                    try:
                        wait_marker(broker, out / (args.label + "-broker.log"), "binder_broker_ready=1", 5)
                        wait_marker(hwbroker, out / (args.label + "-hwbinder.log"), "binder_broker_ready=1", 5)
                        java = subprocess.run(list(map(str, command)), env=environment,
                                              capture_output=True, text=True, timeout=20)
                    finally:
                        for process in (broker, hwbroker):
                            process.terminate()
                            process.wait(timeout=5)
                text = java.stdout + java.stderr
                (out / (args.label + "-art.log")).write_text(text, encoding="utf-8")
                report["art"] = {"passed": java.returncode == 0 and "boot_image_complete=absent\n" in text,
                                 "exitCode": java.returncode}
    report["passed"] = all(row["passed"] for row in report["cases"]) and report["art"]["passed"]
    (out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
