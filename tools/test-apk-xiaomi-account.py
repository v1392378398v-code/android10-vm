#!/usr/bin/env python3
"""Check MIUI login capabilities, storage HAL and the FindDevice provider."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


def run_guest(args):
    command = [sys.executable, str(ROOT / "tools/apk-guest-command.py"), "--package", "io.a10vm.miui",
               "--uid", "1000", *args]
    result = subprocess.run(command, env=ENV, capture_output=True, text=True, timeout=150)
    if result.returncode:
        failure = re.search(r"(?m)^java\.lang\.(?:AssertionError|\w*Exception):.*", result.stdout)
        if failure:
            markers = "\n".join(re.findall(r"(?m)^(?:account|mtd|finddevice)_\w+=.*$", result.stdout))
            raise AssertionError("Guest login check: " + markers + "\n" + failure[0])
        raise AssertionError("Guest login check: " + result.stdout[-1200:] + result.stderr[-500:])
    return result.stdout


def guest(main, args, expected):
    output = run_guest(["--main", "io.a10vm.guest." + main, *args])
    if expected + "\n" not in output:
        raise AssertionError(main + ": " + output[-2200:])
    return dict(re.findall(r"^((?:mtd|finddevice|account)_\w+)=(.*)$", output, re.M))


def account_page():
    output = run_guest(["--native", "rom/system/bin/dumpsys", "activity", "top"])
    for section in re.split(r"(?m)^  ACTIVITY ", output):
        if section.startswith("com.xiaomi.account/") and "mResumed=true" in section:
            return section
    raise AssertionError("The Xiaomi login activity is not resumed")


def view_center(page, resource):
    parents = []
    for line in page.splitlines():
        match = re.match(r"^(\s*)\S+\{.*? (-?\d+),(-?\d+)-(-?\d+),(-?\d+)(?: |\})", line)
        if not match:
            continue
        indent = len(match[1])
        left, top, right, bottom = map(int, match.groups()[1:])
        while parents and parents[-1][0] >= indent:
            parents.pop()
        x = left + (parents[-1][1] if parents else 0)
        y = top + (parents[-1][2] if parents else 0)
        parents.append((indent, x, y))
        if "app:id/" + resource + "}" in line:
            if right <= left or bottom <= top:
                raise AssertionError("Login control has no visible bounds: " + resource)
            return x + (right - left) // 2, y + (bottom - top) // 2
    raise AssertionError("Login control missing: " + resource)


def password_page():
    subprocess.run(["su", "-c", "/system/bin/am start -W -n io.a10vm.miui/io.a10vm.ui.FullscreenActivity"],
                   env=ENV, capture_output=True, check=True, timeout=15)
    run_guest(["activity", "force-stop", "com.xiaomi.account"])
    run_guest(["activity", "start", "-W", "-n", "com.xiaomi.account/.ui.LoginActivity"])
    page = account_page()
    x, y = view_center(page, "entry_to_password_login")
    started = time.monotonic()
    guest("GuestTap", [str(x), str(y)], "guest_tap_ready=1")
    deadline = time.monotonic() + 6
    while True:
        page = account_page()
        if "app:id/input_pwd_view}" in page and "android.widget.EditText{" in page:
            return {"passwordPageDrawn": True, "transitionElapsedMs": round((time.monotonic() - started) * 1000),
                    "coordinatesFromGuestView": True, "credentialsSubmitted": False}
        if time.monotonic() >= deadline:
            raise AssertionError("Password input did not appear after tapping the login control")
        time.sleep(.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-mode", choices=("roundtrip", "seed", "read"), default="roundtrip")
    parser.add_argument("--storage-only", action="store_true")
    parser.add_argument("--capability-only", action="store_true")
    parser.add_argument("--password-page", action="store_true")
    args = parser.parse_args()
    report = {"passed": False, "package": "io.a10vm.miui", "storageMode": args.storage_mode}
    try:
        if not args.capability_only:
            report["storage"] = guest("GuestMtdStorageCheck", [args.storage_mode], "mtd_hardware_credential_absent=1")
        if not args.storage_only and not args.capability_only:
            report["provider"] = guest("GuestFindDeviceCheck", [], "finddevice_provider_ready=1")
        if not args.storage_only:
            report["loginCapability"] = guest("GuestAccountCapabilityCheck", [], "account_capability_ready=1")
        if args.password_page:
            report["loginUi"] = password_page()
        report["passed"] = True
    except (AssertionError, subprocess.SubprocessError) as failure:
        report["error"] = str(failure)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
