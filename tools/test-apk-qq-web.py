#!/usr/bin/env python3
"""Open QQ's real X5 page twice and check renderer survival and guest captures."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

spec = importlib.util.spec_from_file_location("desktop", Path(__file__).with_name("test-apk-desktop.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default="io.a10vm.miui", choices=("io.a10vm", "io.a10vm.miui"))
    parser.add_argument("--label", default="current")
    parser.add_argument("--url", default="https://m.v.qq.com/")
    parser.add_argument("--observe-seconds", type=float, default=30)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid label")
    if args.observe_seconds <= 0:
        parser.error("Observation duration must be positive")
    desktop.PACKAGE = args.package
    device = desktop.device
    desktop.device = lambda command, timeout=15: device("PATH=/system/bin:/system/xbin " + command, timeout)
    out = desktop.ROOT / "artifacts/qq-web" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "url": args.url, "rounds": [], "rootRequiredByGuest": False}
    def guest(label, *command):
        result = subprocess.run(["python3", str(desktop.ROOT / "tools/apk-guest-command.py"), "--package",
            args.package, "--uid", "1000", *command], env=desktop.ENV, capture_output=True, text=True, timeout=30)
        (out / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0 and not re.search(r"^Error(?: type \d+)?:", result.stdout, re.M), \
            label + ": " + result.stdout[-1200:] + result.stderr[-300:]
    pattern = r"desktop_application_launch=(\d+):com.tencent.mobileqq:privileged_process[12]\b"
    try:
        desktop.device("/system/bin/am start -n " + args.package + "/io.a10vm.ui.FullscreenActivity")
        server_pid = re.findall(r"^desktop_pid=(\d+)$", desktop.log("framework-server.log"), re.M)[-1]
        for index in range(2):
            label = "load-" + str(index + 1)
            guest(label + "-stop", "activity", "force-stop", "com.tencent.mobileqq")
            before = set(re.findall(pattern, desktop.log("framework-server.log")))
            guest(label + "-open", "activity", "start", "-n", "com.tencent.mobileqq/.activity.QQBrowserActivity",
                "-e", "url", args.url)
            deadline = time.monotonic() + 20
            while True:
                renderers = set(re.findall(pattern, desktop.log("framework-server.log"))) - before
                if renderers:
                    break
                assert time.monotonic() < deadline, "QQ did not launch an X5 renderer"
                time.sleep(.2)
            time.sleep(args.observe_seconds)
            alive = []
            for pid in sorted(renderers):
                query = "grep -l -E " + shlex.quote("application_pid=" + pid + "$")
                query += " files/guest-runtime/application-" + server_pid + "-*.log"
                names = desktop.device("run-as " + args.package + " /system/bin/sh -c " + shlex.quote(query)).decode().splitlines()
                assert len(names) == 1, "Renderer PID did not identify its application log"
                log = desktop.log(Path(names[0]).name)
                (out / (label + "-renderer-" + pid + ".log")).write_text(log, encoding="utf-8")
                assert not any(marker in log for marker in (
                    "FATAL EXCEPTION", "Fatal signal", "SIG_DFL handler", "catch signal: 31",
                    "**CRASHING**:seccomp-bpf")), "X5 renderer crashed"
                status = desktop.device("run-as " + args.package + " cat /proc/" + pid + "/status").decode()
                assert re.search(r"^State:\s*[ZXTt]", status, re.M) is None, "X5 renderer stopped"
                alive.append(pid)
            path = "/data/local/tmp/a10vm-qq-web.png"
            guest(label + "-capture", "--native", "image/system/bin/screencap", "-p", path)
            (out / (label + ".png")).write_bytes(desktop.device("run-as " + args.package +
                " cat files/guest-runtime/rootfs" + path))
            report["rounds"].append({"rendererPids": alive, "observedSeconds": args.observe_seconds,
                                    "screenshot": label + ".png"})
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
