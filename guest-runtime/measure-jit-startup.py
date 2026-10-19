#!/usr/bin/env python3
"""Compare default and earlier JIT compilation on identical fresh Android 10 runtimes."""
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/performance/jit-startup"


def main():
    assert os.getuid() >= 10000
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"uid": os.getuid(), "passed": False, "samples": []}
    options = ["-Xjitthreshold:3000", "-Xjitwarmupthreshold:1000", "-Xjitosrthreshold:6000"]
    try:
        with tempfile.TemporaryDirectory(prefix="jit-startup-", dir=OUT) as temporary:
            runtime = RuntimeInstance(temporary)
            env = dict(runtime.environment, LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
            # Copy the newly compiled check into this isolated fixture, never into the installed app.
            import shutil
            shutil.copyfile(ROOT / "artifacts/container/framework/dex/classes.dex",
                            runtime.directory / "framework-check.dex")
            results = set()
            for run in range(3):
                for mode in (("default", "early") if run % 2 == 0 else ("early", "default")):
                    command = [str(runtime.native("ld-android.so")), str(runtime.native("dalvikvm64")),
                        *(options if mode == "early" else []), "-Xnoimage-dex2oat",
                        "-Djava.library.path=" + str(runtime.libraries),
                        "-Xbootclasspath:" + ":".join(runtime.inputs["bootClassPath"]),
                        "-cp", str(runtime.directory / "framework-check.dex"),
                        "io.a10vm.guest.JitStartupCheck"]
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                    log = result.stdout + result.stderr
                    (OUT / (f"{run}-{mode}.log")).write_text(log, encoding="utf-8")
                    assert result.returncode == 0, log[-3000:]
                    rows = re.findall(r"jit_startup_pass=(\d+) ms=([\d.]+) result=(-?\d+)", log)
                    assert len(rows) == 4, log
                    assert "jit_startup_cap_eff=0000000000000000" in log, log
                    results.update(row[2] for row in rows)
                    report["samples"].append({"run": run, "mode": mode,
                        "passMs": [float(row[1]) for row in rows]})
            assert len(results) == 1, "Runtime workload results differ"
        for mode in ("default", "early"):
            rows = [row["passMs"] for row in report["samples"] if row["mode"] == mode]
            report[mode] = {"firstPassMedianMs": statistics.median(row[0] for row in rows),
                           "totalMedianMs": statistics.median(sum(row) for row in rows)}
        report["passed"] = True
    except (AssertionError, OSError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
