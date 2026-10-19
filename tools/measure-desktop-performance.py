#!/usr/bin/env python3
"""Measure real guest Settings swipes on the installed host Surface."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from app_startup_cases import CASES

ROOT = Path(__file__).resolve().parent.parent
ENV = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
PACKAGE = "io.a10vm"


def device(command):
    return subprocess.run(["su", "-c", command], env=ENV, capture_output=True,
                          check=True, timeout=20).stdout.decode(errors="replace")


def guest(*args):
    result = subprocess.run(["python3", str(ROOT / "tools/apk-guest-command.py"), "--package", PACKAGE, *args],
                            env=ENV, capture_output=True, text=True, timeout=30)
    if result.returncode or "guest_command_result=0" not in result.stdout:
        raise RuntimeError(result.stdout[-1500:] + result.stderr[-500:])


def cpu(uid):
    rows = device("/system/bin/ps -A -o PID,UID,NAME").splitlines()[1:]
    pids = [r.split()[0] for r in rows if len(r.split()) >= 3 and r.split()[1] == uid]
    if not pids:
        raise AssertionError("Guest processes missing")
    text = device("/system/bin/cat " + " ".join("/proc/" + p + "/stat" for p in pids))
    result = {}
    for row in text.splitlines():
        pid, fields = row.split("(", 1)[0].strip(), row.rsplit(")", 1)[1].split()
        result[pid] = (int(fields[11]) + int(fields[12]), int(fields[19]))
    return result


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 3)


def host_running(uid):
    rows = device("/system/bin/ps -A -o PID,UID,NAME").splitlines()[1:]
    pids = [r.split()[0] for r in rows if len(r.split()) >= 3 and
            r.split()[1] == uid and r.split()[2] == PACKAGE]
    if not pids:
        raise AssertionError("Host application process missing")
    for pid in pids:
        wait = device("/system/bin/cat /proc/" + pid + "/wchan").strip()
        if wait == "do_freezer_trap":
            raise AssertionError("Host application is frozen by the device: " + pid)


def main():
    global PACKAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--swipes", type=int, default=8)
    parser.add_argument("--case", choices=list(CASES), default="settings")
    parser.add_argument("--axis", choices=("vertical", "horizontal"), default="vertical")
    parser.add_argument("--min-fps", type=float, default=0)
    parser.add_argument("--max-p95-ms", type=float, default=0)
    parser.add_argument("--package", choices=("io.a10vm", "io.a10vm.miui"), default="io.a10vm")
    args = parser.parse_args()
    if args.min_fps < 0 or args.max_p95_ms < 0:
        parser.error("Frame thresholds must be nonnegative")
    PACKAGE = args.package
    out = ROOT / "artifacts/performance"
    out.mkdir(parents=True, exist_ok=True)
    report = {"label": args.label, "passed": False, "case": args.case, "package": PACKAGE,
              "swipeAxis": args.axis, "scenario": args.case + " alternating 500ms " + args.axis + " swipes"}
    try:
        identity = device("run-as " + PACKAGE + " cat files/guest-runtime/framework-server.log")
        uid = re.search(r"^desktop_uid=(\d+)$", identity, re.M).group(1)
        host_running(uid)
        package, intent = CASES[args.case]
        guest("activity", "start-activity", "-W", *intent)
        result = subprocess.run(["python3", str(ROOT / "tools/apk-guest-command.py"), "--package", PACKAGE, "--main",
            "io.a10vm.guest.DesktopTaskCheck", package], env=ENV, capture_output=True, text=True, timeout=30)
        if result.returncode or "desktop_task_ready=1" not in result.stdout:
            raise AssertionError("Guest application did not finish drawing: " + package)
        device("/system/bin/am start -W -n " + PACKAGE + "/io.a10vm.ui.FullscreenActivity")
        host_running(uid)
        time.sleep(.5)
        device("/system/bin/uiautomator dump /data/local/tmp/a10vm-perf-ui.xml")
        ui = ET.fromstring(device("/system/bin/cat /data/local/tmp/a10vm-perf-ui.xml"))
        nodes = [n for n in ui.iter("node") if n.get("content-desc") == "Android 10 桌面"]
        if not nodes:
            raise AssertionError("Desktop Surface is not visible")
        left, top, right, bottom = map(int, re.findall(r"\d+", nodes[0].get("bounds")))
        layers = device("/system/bin/dumpsys SurfaceFlinger --list").splitlines()
        layers = [l for l in layers if PACKAGE + "/" in l and "SurfaceView" in l and "(BLAST)" in l]
        if len(layers) != 1:
            raise AssertionError("Expected one desktop Surface: " + repr(layers))
        # Android 15 includes the layer ID in its debug name.
        layer = layers[0].removeprefix("RequestedLayerState{").split(" parentId=", 1)[0]
        device("/system/bin/dumpsys SurfaceFlinger --latency-clear " + shlex.quote(layer))
        before = cpu(uid)
        samples = set()
        started = time.monotonic()
        x = (left + right) // 2
        y1, y2 = top + (bottom - top) * 3 // 4, top + (bottom - top) // 4
        y = (top + bottom) // 2
        x1, x2 = left + (right - left) * 3 // 4, left + (right - left) // 4
        for index in range(args.swipes):
            focus = device("/system/bin/dumpsys window")
            if not re.search(r"mCurrentFocus=.*\b" + re.escape(PACKAGE) + "/", focus):
                raise AssertionError("Host focus changed before swipe")
            a, b = ((x1, x2) if index % 2 == 0 else (x2, x1)) if args.axis == "horizontal" else \
                ((y1, y2) if index % 2 == 0 else (y2, y1))
            points = (a, y, b, y) if args.axis == "horizontal" else (x, a, x, b)
            device("/system/bin/input swipe %d %d %d %d 500" % points)
            text = device("/system/bin/dumpsys SurfaceFlinger --latency " + shlex.quote(layer))
            for row in text.splitlines()[1:]:
                fields = row.split()
                if len(fields) == 3 and all(v.isdecimal() for v in fields):
                    actual = int(fields[1])
                    if 0 < actual < 2**63 - 1:
                        samples.add(actual)
        elapsed = time.monotonic() - started
        after = cpu(uid)
        focus = device("/system/bin/dumpsys window")
        if not re.search(r"mCurrentFocus=.*\b" + re.escape(PACKAGE) + "/", focus):
            raise AssertionError("Host focus changed during measurement")
        times = sorted(samples)
        intervals = [(b - a) / 1e6 for a, b in zip(times, times[1:])]
        if len(intervals) < 20:
            raise AssertionError("Too few actual Surface presents: %d" % len(times))
        ticks = sum(after[p][0] - b[0] for p, b in before.items()
                    if p in after and after[p][1] == b[1])
        report.update(passed=True, uid=int(uid), elapsedSeconds=round(elapsed, 3),
                      surface=layer, presentFrames=len(times),
                      presentFps=round((len(times) - 1) * 1e9 / (times[-1] - times[0]), 2),
                      intervalMedianMs=percentile(intervals, .5), intervalP95Ms=percentile(intervals, .95),
                      intervalMaxMs=round(max(intervals), 3),
                      cpuSeconds=round(ticks / os.sysconf("SC_CLK_TCK"), 3),
                      cpuCores=round(ticks / os.sysconf("SC_CLK_TCK") / elapsed, 3),
                      guestUidProcesses=len(before), swipes=args.swipes,
                      limitation="Includes input-command gaps; Surface presentation, not input-to-photon latency")
        (out / (args.label + "-presents.json")).write_text(json.dumps(times) + "\n", encoding="utf-8")
        if args.min_fps and report["presentFps"] < args.min_fps:
            raise AssertionError("Surface FPS below requested threshold: %s < %s" %
                                 (report["presentFps"], args.min_fps))
        if args.max_p95_ms and report["intervalP95Ms"] > args.max_p95_ms:
            raise AssertionError("P95 frame interval above requested threshold: %s > %s" %
                                 (report["intervalP95Ms"], args.max_p95_ms))
    except Exception as error:
        report["passed"] = False
        report["error"] = str(error)
    (out / (args.label + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
