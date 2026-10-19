#!/usr/bin/env python3
"""Compare interpreted ART with actual compiled code under an ordinary UID."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/container/art"


def main():
    assert os.getuid() >= 10000
    report = {"passed": False, "uid": os.getuid()}
    with tempfile.TemporaryDirectory(prefix="jit-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)
        environment = dict(runtime.environment, LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
        samples = {}
        for mode, options in (("interpreter", ["-Xint", "-Xusejit:false"]),
                              ("jit", ["-Xusejit:true", "-Xjitthreshold:1000"])):
            command = [str(runtime.native("ld-android.so")), str(runtime.native("dalvikvm64")),
                       *options, "-Xnoimage-dex2oat", "-Djava.library.path=" + str(runtime.libraries),
                       "-Xbootclasspath:" + ":".join(runtime.inputs["bootClassPath"]),
                       "-cp", str(runtime.directory / "framework-check.dex"), "io.a10vm.guest.JitCheck"]
            if mode == "jit":
                command.append("--require-jit")
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
            log = result.stdout + result.stderr
            (OUT / ("jit-" + mode + ".log")).write_text(log, encoding="utf-8")
            match = re.search(r"^jit_workload_ms=(.*)$", log, re.M)
            samples[mode] = {"exitCode": result.returncode, "workloadMs": float(match[1]) if match else None}
            if result.returncode:
                print(log[-3500:])
                break
        report["samples"] = samples
        if all(mode in samples and samples[mode]["exitCode"] == 0 for mode in ("interpreter", "jit")):
            report["speedup"] = round(samples["interpreter"]["workloadMs"] / samples["jit"]["workloadMs"], 2)
            report["passed"] = report["speedup"] >= 3
    (OUT / "jit-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
