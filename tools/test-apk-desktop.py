#!/usr/bin/env python3
"""Exercise the installed APK entry and retain its real desktop boot result."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts/device-desktop"
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
SERIAL = None
PACKAGE = "io.a10vm"
ROOT_CONTROL = False


def device(command, timeout=15):
    if SERIAL and ROOT_CONTROL:
        command = "su -c " + shlex.quote("PATH=/system/bin:/system/xbin " + command)
    argv = ["adb", "-s", SERIAL, "exec-out", command] if SERIAL else ["su", "-c", command]
    return subprocess.run(argv, env=ENV, capture_output=True, timeout=timeout, check=True).stdout


def log(role):
    return device("run-as " + PACKAGE + " cat files/guest-runtime/" + shlex.quote(role)).decode(errors="replace")


def screenshot(path):
    focus = device("/system/bin/dumpsys window").decode(errors="replace")
    if not re.search(r"mCurrentFocus=.*\b" + re.escape(PACKAGE) + "/", focus):
        path.unlink(missing_ok=True)
        return None
    path.write_bytes(device("/system/bin/screencap -p"))
    return str(path.relative_to(ROOT))


def ui():
    device("/system/bin/uiautomator dump /data/local/tmp/a10vm-desktop-ui.xml")
    return ET.fromstring(device("cat /data/local/tmp/a10vm-desktop-ui.xml"))


def click(text):
    deadline = time.monotonic() + 10
    while True:
        for node in ui().iter("node"):
            if node.get("text") == text and node.get("enabled") == "true":
                left, top, right, bottom = map(int, re.findall(r"\d+", node.get("bounds")))
                device("/system/bin/input tap %d %d" % ((left + right) // 2, (top + bottom) // 2))
                return
        if time.monotonic() >= deadline:
            raise AssertionError("APK control missing: " + text)
        time.sleep(.25)


def main():
    global SERIAL, OUT, PACKAGE, ROOT_CONTROL
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", help="Use this ADB device instead of the local shell")
    parser.add_argument("--root-control", action="store_true", help="Use remote root for test controls; guest identity is still checked")
    parser.add_argument("--package", choices=("io.a10vm", "io.a10vm.miui"), default="io.a10vm")
    parser.add_argument("--output", type=Path, default=OUT, help="Evidence directory")
    parser.add_argument("--inspect", action="store_true", help="Assert the current boot without restarting")
    parser.add_argument("--direct-start", action="store_true", help="Start the normal app service without a UI tap")
    parser.add_argument("--timeout", type=float, default=80)
    parser.add_argument("--stability-seconds", type=float, default=20)
    args = parser.parse_args()
    SERIAL, OUT, PACKAGE, ROOT_CONTROL = args.serial, args.output.resolve(), args.package, args.root_control
    rom = PACKAGE == "io.a10vm.miui"
    ready_marker = "rom_desktop_ready=1" if rom else "desktop_services_ready=1"
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "installedApk": True, "rootRequiredByGuest": False, "package": PACKAGE}
    report["rootUsedForTestControl"] = not SERIAL or ROOT_CONTROL
    if SERIAL:
        report["adbSerial"] = SERIAL
    started = time.monotonic()
    try:
        previous = ""
        previous_server = ""
        previous_input = ""
        if not args.inspect:
            try:
                previous = log("framework-client.log")
                previous_server = log("framework-server.log")
                previous_input = log("framework-input.log")
            except subprocess.CalledProcessError:
                pass
            device("/system/bin/am force-stop " + PACKAGE)
            device("/system/bin/am start -W -n " + PACKAGE + "/io.a10vm.ui.MainActivity")
            if args.direct_start:
                device("/system/bin/am start-foreground-service -n " + PACKAGE + "/io.a10vm.runtime.VmService "
                       "-a io.a10vm.START_NATIVE_DISPLAY")
            else:
                click("启动 Android 10 桌面")
            report["startMethod"] = "app-service" if args.direct_start else "UI tap"
        deadline = time.monotonic() + args.timeout
        while True:
            try:
                text = log("framework-client.log")
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise AssertionError("APK did not start a desktop check")
                time.sleep(.25)
                continue
            delta = text[len(previous):] if previous and text.startswith(previous) else text
            if not args.inspect and not delta:
                if time.monotonic() >= deadline:
                    raise AssertionError("APK did not start a new desktop check")
                time.sleep(.25)
                continue
            if ready_marker + "\n" in text:
                if args.inspect or ready_marker + "\n" in delta:
                    break
            server = log("framework-server.log")
            server_delta = server[len(previous_server):] if previous_server and server.startswith(previous_server) else server
            if "*** FATAL EXCEPTION IN SYSTEM PROCESS:" in server_delta or "*** WATCHDOG KILLING SYSTEM PROCESS:" in server_delta:
                raise AssertionError("Installed APK system server exited: " + server_delta[-1800:])
            if "exiting due to SIG_DFL handler for signal " in server_delta:
                raise AssertionError("Installed APK native startup crashed: " + server_delta[-1800:])
            if args.inspect or "java.lang.AssertionError:" in delta or "FATAL EXCEPTION" in delta:
                raise AssertionError("Installed APK desktop check failed: " + "\n".join(
                    line for line in delta.splitlines() if line.startswith("desktop_") or "AssertionError:" in line))
            if time.monotonic() >= deadline:
                raise AssertionError("Installed APK desktop boot timeout")
            time.sleep(.25)
        markers = ("rom_boot_completed=1", "rom_user_unlocked=true", "rom_home_package=com.miui.home") if rom else (
            "desktop_home_drawn=1", "desktop_user_unlocked=true", "desktop_home_resolved=com.android.launcher3")
        for marker in markers:
            assert marker + "\n" in text, marker
        identity_text = log("framework-server.log") if rom else text
        report["identity"] = dict(re.findall(r"^desktop_(pid|uid|euid|cap_eff|selinux)=(.*)$", identity_text, re.M))
        assert int(report["identity"]["uid"]) >= 10000, report["identity"]
        assert int(report["identity"]["cap_eff"], 16) == 0, report["identity"]
        while True:
            try:
                input_text = log("framework-input.log")
            except subprocess.CalledProcessError:
                input_text = ""
            if "desktop_input_ready=1\n" in input_text and (args.inspect or input_text != previous_input):
                break
            if time.monotonic() >= deadline:
                raise AssertionError("Installed APK input service did not become ready: " + input_text[-1800:])
            time.sleep(.25)
        input_identity = dict(re.findall(r"^desktop_input_(pid|uid|euid|cap_eff|selinux)=(.*)$", input_text, re.M))
        assert input_identity["uid"] == report["identity"]["uid"], input_identity
        assert int(input_identity["cap_eff"], 16) == 0, input_identity
        report.update(inputReady=True, inputIdentity=input_identity)
        report["bootSeconds"] = round(time.monotonic() - started, 3)
        if args.direct_start:
            device("/system/bin/am start -W -n " + PACKAGE + "/io.a10vm.ui.FullscreenActivity")
        if not args.inspect:
            surface_deadline = time.monotonic() + 15
            while True:
                screen = ui()
                surface = any(node.get("content-desc") == "Android 10 桌面" for node in screen.iter("node"))
                waiting = any(node.get("text") == "正在显示桌面，请稍候…" for node in screen.iter("node"))
                if surface and not waiting:
                    break
                if time.monotonic() >= surface_deadline:
                    raise AssertionError("APK did not automatically open a presented desktop Surface")
                time.sleep(.25)
        server = log("framework-server.log")
        server_pids = re.findall(r"^desktop_pid=(\d+)$", server, re.M)
        assert server_pids, "Guest system server PID missing"
        server_pid = server_pids[-1]
        stable_until = time.monotonic() + args.stability_seconds
        while True:
            server = log("framework-server.log")
            assert "*** FATAL EXCEPTION IN SYSTEM PROCESS:" not in server, "Guest system server crashed after drawing"
            assert "*** WATCHDOG KILLING SYSTEM PROCESS:" not in server, "Guest system server hung after drawing"
            assert re.findall(r"^desktop_pid=(\d+)$", server, re.M)[-1] == server_pid, "Guest system server restarted"
            status = device("run-as " + PACKAGE + " cat /proc/" + server_pid + "/status").decode()
            assert re.search(r"^State:\s*[ZXTt]", status, re.M) is None, "Guest system server stopped"
            assert re.search(r"^Uid:\s+(\d+)", status, re.M).group(1) == report["identity"]["uid"], \
                "Guest system server identity changed"
            launches = len(re.findall(r"^desktop_application_launch=\d+:com.android.systemui$", server, re.M))
            assert 1 <= launches <= 2, "SystemUI restart loop: %d launches" % launches
            if time.monotonic() >= stable_until:
                break
            time.sleep(.5)
        report.update(stabilitySeconds=args.stability_seconds, systemServerPid=server_pid,
                      systemUiLaunches=launches, systemServerAlive=True)
        input_status = device("run-as " + PACKAGE + " cat /proc/" + input_identity["pid"] + "/status").decode()
        assert re.search(r"^State:\s*[ZXTt]", input_status, re.M) is None, "Guest input service stopped"
        assert re.search(r"^Uid:\s+(\d+)", input_status, re.M).group(1) == input_identity["uid"], \
            "Guest input service identity changed"
        report.update(passed=True, launcherDrawn=True, surfaceOpened=not args.inspect)
    except Exception as error:
        report["error"] = str(error)
    finally:
        report["elapsedSeconds"] = round(time.monotonic() - started, 3)
        for role in ("client", "server", "compositor", "manager", "hwmanager", "input"):
            try:
                (OUT / ("apk-" + role + ".log")).write_text(log("framework-" + role + ".log"), encoding="utf-8")
            except (subprocess.SubprocessError, OSError):
                pass
        report["screenshot"] = None
        try:
            report["screenshot"] = screenshot(OUT / "apk-desktop.png")
        except (subprocess.SubprocessError, OSError) as error:
            report["captureError"] = str(error)
            report["passed"] = False
            report.setdefault("error", "Desktop evidence capture failed: " + str(error))
        (OUT / "apk-desktop-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
