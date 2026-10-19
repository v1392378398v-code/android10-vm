#!/usr/bin/env python3
"""Check the reported Settings and third-party startup bugs on the installed APK."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location("desktop", Path(__file__).with_name("test-apk-desktop.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
OUT = desktop.ROOT / "artifacts/app-compat"
CASES = {
    "about": ("com.android.settings", ["-a", "android.settings.DEVICE_INFO_SETTINGS"]),
    "input-method": ("com.android.settings", ["-a", "android.settings.INPUT_METHOD_SETTINGS"]),
    "developer": ("com.android.settings", ["-a", "android.settings.APPLICATION_DEVELOPMENT_SETTINGS"]),
    "wifi": ("com.android.settings", ["-a", "android.settings.WIFI_SETTINGS"]),
    "appstore": ("com.tencent.android.qqdownloader", ["-n",
        "com.tencent.android.qqdownloader/com.tencent.pangu.link.SplashActivity"]),
    "miui-market": ("com.xiaomi.market", ["-n", "com.xiaomi.market/.ui.MarketTabActivity"]),
    "mt": ("bin.mt.plus", ["-a", "android.intent.action.MAIN", "-c",
        "android.intent.category.LAUNCHER", "-n", "bin.mt.plus/.MainLightIcon"]),
    "douyin": ("com.ss.android.ugc.aweme", ["-a", "android.intent.action.MAIN", "-c",
        "android.intent.category.LAUNCHER", "-n", "com.ss.android.ugc.aweme/.splash.SplashActivity"]),
    "qq": ("com.tencent.mobileqq", ["-n", "com.tencent.mobileqq/.activity.SplashActivity"]),
}


def guest(label, *arguments):
    try:
        result = subprocess.run([sys.executable, str(desktop.ROOT / "tools/apk-guest-command.py"),
                                "--package", desktop.PACKAGE, *arguments],
                                env=desktop.ENV, capture_output=True, text=True, timeout=30)
        output, code = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        output = "".join(value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                         for value in (error.stdout, error.stderr)) + "\nguest_command_timeout=30\n"
        code = 124
    (OUT / (label + ".log")).write_text(output, encoding="utf-8")
    return code, output


def application_logs():
    output = desktop.device("run-as " + desktop.PACKAGE + " /system/bin/sh -c " +
                            "'stat -c \"%n %s\" files/guest-runtime/application-*.log'").decode()
    return {Path(name).name: int(size) for name, size in (line.rsplit(" ", 1)
            for line in output.splitlines())}


def crashes_since(label, package, before):
    crashes = []
    server = desktop.log("framework-server.log")
    package_pids = set(re.findall(r"desktop_application_launch=(\d+):" + re.escape(package) + r"(?=[:\s]|$)", server))
    for name, size in sorted(application_logs().items()):
        if before.get(name) == size:
            continue
        raw = desktop.device("run-as " + desktop.PACKAGE + " cat files/guest-runtime/" + name)
        output = raw[before.get(name, 0):].decode(errors="replace")
        (OUT / (label + "-" + name)).write_text(output, encoding="utf-8")
        pid = re.search(r"application_pid=(\d+)", raw.decode(errors="replace"))
        belongs = "Process: " + package in output or bool(pid and pid.group(1) in package_pids)
        if belongs and any(marker in output for marker in (
                "FATAL EXCEPTION", "Fatal signal", "SIG_DFL handler", "catch signal: 31",
                "Ashmem region has a wrong protection mask")):
            crashes.append(name)
    return crashes


def server_alive():
    server = desktop.log("framework-server.log")
    pid = re.search(r"^desktop_pid=(\d+)$", server, re.M)
    if not pid:
        return False
    try:
        status = desktop.device("cat /proc/" + pid.group(1) + "/status").decode()
        return re.search(r"^State:\s*[ZRXT]", status, re.M) is None
    except subprocess.CalledProcessError:
        return False


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", choices=("io.a10vm", "io.a10vm.miui"), default="io.a10vm")
    parser.add_argument("--case", choices=list(CASES), action="append")
    parser.add_argument("--label")
    parser.add_argument("--settle-seconds", type=float,
                        help="Observation window; defaults to 60s for Douyin and 5s for other cases")
    args = parser.parse_args()
    desktop.PACKAGE = args.package
    if args.label:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
            parser.error("Invalid evidence label")
        OUT = OUT / args.label
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for label in args.case or CASES:
        package, intent = CASES[label]
        if not server_alive():
            results[label] = {"passed": False, "package": package, "error": "Guest system server exited"}
            print(json.dumps({label: results[label]}, ensure_ascii=False), flush=True)
            break
        guest(label + "-reset", "activity", "force-stop", package)
        before = application_logs()
        code, launch = guest(label + "-launch", "activity", "start-activity", *intent)
        if code != 0:
            guest(label + "-launch-stop", "activity", "force-stop", package)
        observation = args.settle_seconds if args.settle_seconds is not None else (60 if label == "douyin" else 5)
        time.sleep(observation)
        crashes = crashes_since(label, package, before)
        code_drawn, drawn = (1, "") if crashes else guest(
            label + "-drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", package)
        if not crashes:
            crashes = crashes_since(label, package, before)
        screenshot = desktop.screenshot(OUT / (label + ".png"))
        results[label] = {"passed": code == code_drawn == 0 and "guest_command_result=0\n" in launch
                          and "Error: Activity not started" not in launch
                          and "desktop_task_ready=1\n" in drawn and not crashes,
                          "package": package, "drawn": "desktop_task_ready=1\n" in drawn,
                          "crashes": crashes, "screenshot": screenshot, "observationSeconds": observation}
        results[label]["systemServerAlive"] = server_alive()
        results[label]["launchTimingMs"] = {name: int(value) for name, value in re.findall(
            r"^(TotalTime|WaitTime|ThisTime):\s*(\d+)$", launch, re.M)}
        (OUT / (label + "-server.log")).write_text(desktop.log("framework-server.log"), encoding="utf-8")
        if not results[label]["passed"]:
            guest(label + "-stop", "activity", "force-stop", package)
        print(json.dumps({label: results[label]}, ensure_ascii=False), flush=True)
    report = {"passed": all(item["passed"] for item in results.values()), "cases": results,
              "package": desktop.PACKAGE,
              "rootRequiredByGuest": False, "deviceRootUsedForAutomation": True}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
