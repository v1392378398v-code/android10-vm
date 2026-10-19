#!/usr/bin/env python3
"""Verify stock boot image mappings and compare framework startup without the image."""
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
    parser.add_argument("--label", default="boot-image-v28")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    assert 1 <= args.samples <= 10
    out = ROOT / "artifacts/performance"
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "uid": os.getuid(), "rootRequired": False, "samples": []}
    with tempfile.TemporaryDirectory(prefix="boot-image-", dir=ROOT / "artifacts/container/framework") as directory:
        runtime = RuntimeInstance(directory)
        environment = runtime.framework_environment()
        modes = ("loaded", "absent") if args.benchmark else ("loaded",)
        broker_log = out / (args.label + "-broker.log")
        with broker_log.open("w", encoding="utf-8") as stream:
            broker = subprocess.Popen([str(runtime.native("ld-android.so")), str(runtime.native("binder-broker")),
                                       str(runtime.directory / "binder.sock")], env=runtime.registry_environment(),
                                      stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_marker(broker, broker_log, "binder_broker_ready=1", 3)
                for index in range(args.samples):
                    for mode in modes:
                        command = [runtime.native("ld-android.so"), runtime.native("app_process64"), "-Xnoimage-dex2oat"]
                        if mode == "absent":
                            command.append("-Ximage:/system/framework/missing-boot-image.art")
                        command += ["-Djava.library.path=" + str(runtime.libraries), "/system/bin",
                                    "--application", "--nice-name=boot-image-check",
                                    "io.a10vm.guest.BootImageCheck", mode]
                        environment["A10VM_BOOT_IMAGE_START_NS"] = str(time.clock_gettime_ns(time.CLOCK_BOOTTIME))
                        started = time.monotonic()
                        result = subprocess.run(list(map(str, command)), env=environment, capture_output=True,
                                                text=True, timeout=15)
                        log = result.stdout + result.stderr
                        (out / f"{args.label}-{mode}-{index}.log").write_text(log, encoding="utf-8")
                        timings = dict((name, int(value)) for name, value in re.findall(r"^boot_image_(entry|ready)_ms=(\d+)$", log, re.M))
                        passed = result.returncode == 0 and f"boot_image_complete={mode}\n" in log
                        report["samples"].append({"mode": mode, "exitCode": result.returncode, "passed": passed,
                                                  "entryMs": timings.get("entry"), "readyMs": timings.get("ready"),
                                                  "elapsedMs": round((time.monotonic() - started) * 1000, 3)})
                        if not passed:
                            print(log[-2000:])
                            break
                    if not report["samples"][-1]["passed"]:
                        break
            finally:
                broker.terminate()
                broker.wait(timeout=3)
    report["passed"] = len(report["samples"]) == args.samples * len(modes) and all(row["passed"] for row in report["samples"])
    (out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
