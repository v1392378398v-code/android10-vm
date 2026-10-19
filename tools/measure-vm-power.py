#!/usr/bin/env python3
"""Measure VM CPU work and Surface submissions in a stationary foreground or background scene."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import statistics
import time
from app_startup_cases import CASES

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("performance", ROOT / "tools/measure-desktop-performance.py")
performance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(performance)
device, guest = performance.device, performance.guest


def temperature():
    battery = device("/system/bin/dumpsys battery")
    value = re.search(r"^\s*temperature:\s*(\d+)", battery, re.M)
    return int(value.group(1)) / 10 if value else None


def assert_host_state(background):
    foreground = bool(re.search(r"mCurrentFocus=.*\bio\.a10vm/", device("/system/bin/dumpsys window")))
    if foreground == background:
        raise AssertionError("Host focus changed from the requested measurement scene")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--case", choices=("qq", "wechat", "douyin", "settings"), default="qq")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--seconds", type=int, default=6)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label) or not 3 <= args.seconds <= 30:
        parser.error("Invalid label or duration")
    out = ROOT / "artifacts/performance"
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "case": args.case, "background": args.background,
              "rootRequiredByGuest": False, "deviceRootUsedForAutomation": True}
    try:
        identity = device("run-as io.a10vm cat files/guest-runtime/framework-server.log")
        uid = re.search(r"^desktop_uid=(\d+)$", identity, re.M).group(1)
        server = re.search(r"^desktop_pid=(\d+)$", identity, re.M).group(1)
        package, intent = CASES[args.case]
        guest("activity", "start-activity", "-W", *intent)
        device("/system/bin/am start -W -n io.a10vm/.ui.FullscreenActivity")
        time.sleep(1)
        layers = device("/system/bin/dumpsys SurfaceFlinger --list").splitlines()
        layers = [row for row in layers if "io.a10vm/" in row and "SurfaceView" in row and "(BLAST)" in row]
        if len(layers) != 1:
            raise AssertionError("Expected one desktop Surface")
        layer = layers[0].removeprefix("RequestedLayerState{").split(" parentId=", 1)[0]
        if args.background:
            device("/system/bin/input keyevent HOME")
            time.sleep(1)
        else:
            device("/system/bin/dumpsys SurfaceFlinger --latency-clear " + shlex.quote(layer))
        assert_host_state(args.background)
        initial_temperature = temperature()
        names = {row.split()[0]: row.split()[2] for row in
                 device("/system/bin/ps -A -o PID,UID,NAME").splitlines()[1:]
                 if len(row.split()) >= 3 and row.split()[1] == uid}
        before = performance.cpu(uid)
        started = time.monotonic()
        presents = set()
        for _ in range(args.seconds):
            time.sleep(1)
            if not args.background:
                for row in device("/system/bin/dumpsys SurfaceFlinger --latency " + shlex.quote(layer)).splitlines()[1:]:
                    values = row.split()
                    if len(values) == 3 and all(value.isdecimal() for value in values):
                        actual = int(values[1])
                        if 0 < actual < 2**63 - 1:
                            presents.add(actual)
        after = performance.cpu(uid)
        elapsed = time.monotonic() - started
        assert_host_state(args.background)
        rows = [{"pid": int(pid), "name": names.get(pid, ""), "cpuTicks": after[pid][0] - values[0]}
                for pid, values in before.items() if pid in after and after[pid][1] == values[1]]
        ticks = sum(row["cpuTicks"] for row in rows)
        times = sorted(presents)
        intervals = [(b - a) / 1e6 for a, b in zip(times, times[1:])]
        status = device("run-as io.a10vm cat /proc/" + server + "/status")
        if re.search(r"^State:\s*[ZXTt]", status, re.M):
            raise AssertionError("Guest system server stopped")
        report.update(passed=True, hostSceneVerified=True, uid=int(uid), systemServerPid=int(server),
                      cpuCores=round(ticks / os.sysconf("SC_CLK_TCK") / elapsed, 3),
                      elapsedSeconds=round(elapsed, 3), presentFrames=len(times),
                      presentsPerSecond=round(len(times) / elapsed, 2),
                      intervalMedianMs=round(statistics.median(intervals), 3) if intervals else None,
                      batteryTemperatureBeforeC=initial_temperature, batteryTemperatureAfterC=temperature(),
                      processes=sorted(rows, key=lambda row: row["cpuTicks"], reverse=True),
                      limitation="CPU and Surface work proxies; short samples do not establish steady-state temperature")
    except Exception as error:
        report["error"] = str(error)
    (out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
