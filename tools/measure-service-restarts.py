#!/usr/bin/env python3
"""Count guest service launches over a bounded window without restarting them."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import time

spec = importlib.util.spec_from_file_location("desktop", Path(__file__).with_name("test-apk-desktop.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def launches(text):
    return Counter(re.findall(r"^desktop_application_launch=\d+:([^\n]+)$", text, re.M))


def assert_foreground():
    focus = desktop.device("/system/bin/dumpsys window").decode(errors="replace")
    assert re.search(r"mCurrentFocus=.*\b" + re.escape(desktop.PACKAGE) + "/", focus), "Host focus changed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", choices=("io.a10vm", "io.a10vm.miui"), default="io.a10vm.miui")
    parser.add_argument("--label", required=True)
    parser.add_argument("--seconds", type=float, default=15)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label) or not 1 <= args.seconds <= 30:
        parser.error("Invalid label or sample duration")
    desktop.PACKAGE = args.package
    assert_foreground()
    before = desktop.log("framework-server.log")
    pid = re.search(r"^desktop_pid=(\d+)$", before, re.M).group(1)
    started = time.monotonic()
    time.sleep(args.seconds)
    after = desktop.log("framework-server.log")
    assert_foreground()
    assert re.search(r"^desktop_pid=(\d+)$", after, re.M).group(1) == pid, "System server changed"
    previous, current = launches(before), launches(after)
    delta = {name: current[name] - previous[name] for name in current if current[name] > previous[name]}
    report = {"package": args.package, "systemServerPid": int(pid),
              "elapsedSeconds": round(time.monotonic() - started, 3), "launchesDuringSample": delta,
              "findDeviceLaunches": delta.get("com.xiaomi.finddevice", 0),
              "updaterLaunches": delta.get("com.android.updater", 0),
              "findDeviceLaunchesTotal": current.get("com.xiaomi.finddevice", 0),
              "updaterLaunchesTotal": current.get("com.android.updater", 0),
              "hostForegroundAtBothReads": True,
              "rootRequiredByGuest": False, "deviceRootUsedForAutomation": True,
              "limitation": "Bounded launch counts only; does not verify all service functions"}
    out = desktop.ROOT / "artifacts/performance"
    out.mkdir(parents=True, exist_ok=True)
    (out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
