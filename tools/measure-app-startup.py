#!/usr/bin/env python3
"""Measure cold and warm guest Activity launches without clearing app data."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from app_startup_cases import CASES

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/test-apk-desktop.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
def guest(out, label, *arguments):
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(ROOT / "tools/apk-guest-command.py"),
                             "--package", desktop.PACKAGE, *arguments],
                            env=desktop.ENV, capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    (out / (label + ".log")).write_text(output, encoding="utf-8")
    if result.returncode or (arguments[0] != "--main" and "guest_command_result=0" not in output):
        raise RuntimeError("Guest command failed: " + label)
    return output, round((time.monotonic() - started) * 1000, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--package", choices=("io.a10vm", "io.a10vm.miui"), default="io.a10vm")
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    desktop.PACKAGE = args.package
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label) or not 1 <= args.runs <= 5:
        parser.error("Invalid label or runs")
    out = ROOT / "artifacts/performance" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "package": desktop.PACKAGE, "rootRequiredByGuest": False, "deviceRootUsedForAutomation": True,
              "applicationDataPreserved": True, "samples": [], "mediansMs": {}}
    try:
        server = desktop.log("framework-server.log")
        server_pid = re.findall(r"^desktop_pid=(\d+)$", server, re.M)[-1]
        for case in args.case or ["settings", "mt"]:
            package, intent = CASES[case]
            if "android.intent.category.LAUNCHER" in intent:
                resolved, _ = guest(out, case + "-launcher", "package", "resolve-activity", "--brief", *intent)
                component = re.search(r"^" + re.escape(package) + r"/[^\s]+$", resolved, re.M)
                if component is None:
                    raise AssertionError("Enabled launcher missing: " + package)
                intent = ["-n", component.group(0)]
            for index in range(args.runs):
                old_launches = len(re.findall(r"^desktop_application_launch=\d+:" +
                    re.escape(package) + "$", desktop.log("framework-server.log"), re.M))
                guest(out, f"{case}-{index}-stop", "activity", "force-stop", package)
                for mode in ("cold", "warm"):
                    label = f"{case}-{index}-{mode}"
                    output, wall = guest(out, label, "activity", "start-activity", "-W", *intent)
                    timing = {name: int(value) for name, value in re.findall(
                        r"^(TotalTime|WaitTime|ThisTime):\s*(\d+)$", output, re.M)}
                    status = re.search(r"^Status: (ok|timeout)$", output, re.M)
                    if "WaitTime" not in timing or status is None:
                        raise AssertionError("Activity launch timing missing: " + label)
                    drawn, drawn_wall = guest(out, label + "-drawn", "--main",
                                     "io.a10vm.guest.DesktopTaskCheck", package)
                    if "desktop_task_ready=1\n" not in drawn:
                        raise AssertionError("Application did not draw: " + label)
                    launches = re.findall(r"^desktop_application_launch=(\d+):" +
                        re.escape(package) + "$", desktop.log("framework-server.log"), re.M)
                    if len(launches) <= old_launches:
                        raise AssertionError("Fresh application process missing: " + label)
                    maps = desktop.device("/system/bin/cat /proc/" + launches[-1] + "/maps").decode()
                    report["samples"].append({"case": case, "mode": mode, "index": index,
                        **timing, "commandWallMs": wall, "drawnCheckWallMs": drawn_wall,
                        "readyWallMs": round(wall + drawn_wall, 3),
                        "applicationPid": int(launches[-1]), "drawn": True,
                        "activityStatus": status.group(1),
                        "cachedDexMappings": sum(".adex" in line for line in maps.splitlines())})
            for mode in ("cold", "warm"):
                samples = [row["WaitTime"] for row in report["samples"]
                           if row["case"] == case and row["mode"] == mode]
                report["mediansMs"][case + "-" + mode] = statistics.median(samples)
        status = desktop.device("run-as " + desktop.PACKAGE + " cat /proc/" + server_pid + "/status").decode()
        if re.search(r"^State:\s*[ZXTt]", status, re.M):
            raise AssertionError("Guest system server stopped")
        report.update(passed=True, sameSystemServerPid=int(server_pid))
    except Exception as error:
        report["error"] = str(error)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
