#!/usr/bin/env python3
"""Check that destroying and replacing the host Surface keeps the guest alive."""
import json
import importlib.util
import argparse
from pathlib import Path
import re
import subprocess
import time

spec = importlib.util.spec_from_file_location("desktop", Path(__file__).with_name("test-apk-desktop.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def await_power(interactive):
    expected = "guest_display_interactive=" + str(interactive).lower() + "\n"
    deadline = time.monotonic() + 10
    while True:
        result = subprocess.run(["python3", str(desktop.ROOT / "tools/apk-guest-command.py"),
            "--uid", "1000", "--main", "io.a10vm.guest.GuestDisplayState", "inspect"],
            env=desktop.ENV, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise AssertionError(result.stdout[-1000:] + result.stderr[-500:])
        if expected in result.stdout and expected in desktop.log("framework-display-state.log"):
            return
        if time.monotonic() >= deadline:
            raise AssertionError("Guest display did not follow host visibility: " + expected.strip())
        time.sleep(.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--check-power", action="store_true")
    args = parser.parse_args()
    assert args.cycles > 0
    report = {"passed": False, "cycles": args.cycles}
    try:
        server = desktop.log("framework-server.log")
        pid = re.search(r"^desktop_pid=(\d+)$", server, re.M).group(1)
        host_pid = desktop.device("/system/bin/pidof io.a10vm").decode().split()[0]

        def workers():
            text = desktop.device("/system/bin/cat /proc/" + host_pid + "/task/*/stat").decode()
            names = [row.split("(", 1)[1].rsplit(")", 1)[0] for row in text.splitlines()]
            return sum(name in ("a10-gpu-worker", "a10-compositor") for name in names)

        counts = [workers()]
        if args.check_power:
            await_power(True)
        for _ in range(args.cycles):
            desktop.device("/system/bin/input keyevent HOME" if args.check_power else
                           "/system/bin/am start -W -n io.a10vm/.ui.MainActivity")
            time.sleep(.3)
            if args.check_power:
                await_power(False)
            desktop.device("cat /proc/" + pid + "/status")
            desktop.device("/system/bin/am start -W -n io.a10vm/.ui.FullscreenActivity")
            if args.check_power:
                await_power(True)
            deadline = time.monotonic() + 10
            while True:
                screen = desktop.ui()
                surface = any(n.get("content-desc") == "Android 10 桌面" for n in screen.iter("node"))
                waiting = any(n.get("text") == "正在显示桌面，请稍候…" for n in screen.iter("node"))
                if surface and not waiting:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("Replacement Surface did not present a frame")
                time.sleep(.2)
            time.sleep(.3)
            desktop.device("cat /proc/" + pid + "/status")
            counts.append(workers())
        report["gpuWorkerCounts"] = counts
        baseline = counts[1] if args.check_power and args.cycles > 1 else counts[0]
        assert counts[-1] <= baseline + 1, "GPU workers grew across Surface replacements"
        report["gpuWorkerBaseline"] = baseline
        server = desktop.log("framework-server.log")
        assert "*** FATAL EXCEPTION" not in server and "*** WATCHDOG" not in server
        report.update(passed=True, sameSystemServerPid=int(pid), surfaceReplaced=True, framePresented=True)
        if args.check_power:
            report.update(backgroundTurnsDisplayOff=True, foregroundWakesDisplay=True,
                          transitionsVerified=args.cycles * 2)
    except Exception as error:
        report["error"] = str(error)
    out = desktop.ROOT / "artifacts/performance"
    out.mkdir(parents=True, exist_ok=True)
    (out / "surface-lifecycle.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
