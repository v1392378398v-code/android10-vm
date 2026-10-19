#!/usr/bin/env python3
"""Clear only an independent fixture through the installed guest's real package service."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import zipfile

spec = importlib.util.spec_from_file_location("desktop", Path(__file__).with_name("test-apk-desktop.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
ROOT, ENV = desktop.ROOT, desktop.ENV
PACKAGE = "io.a10vm.fixture.cleardata"
DATA = "files/guest-runtime/rootfs/data"


def build_fixture(large_mb=0):
    source = ROOT / "tools/fixtures/clear-data"
    work = ROOT / "artifacts/clear-data/fixture"
    sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk")))
    android = sdk / "platforms/android-35/android.jar"
    for directory in (work / "classes", work / "dex"):
        directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(["javac", "--release", "8", "-cp", str(android), "-d", str(work / "classes"),
                    *map(str, source.glob("*.java"))], env=ENV, check=True)
    subprocess.run(["bash", str(sdk / "build-tools/35.0.0/d8"), "--min-api", "29", "--lib", str(android),
                    "--output", str(work / "dex"), *map(str, (work / "classes").rglob("*.class"))],
                   env=ENV, check=True)
    unsigned = work / "unsigned.apk"
    subprocess.run(["aapt2", "link", "--manifest", str(source / "AndroidManifest.xml"),
                    "-I", str(android), "-o", str(unsigned)], env=ENV, check=True)
    with zipfile.ZipFile(unsigned, "a") as archive:
        archive.write(work / "dex/classes.dex", "classes.dex")
        gif = ROOT / "artifacts/app-compat/qq-native/libgiflibra.so"
        if gif.is_file():
            archive.write(gif, "lib/arm64-v8a/libgiflibra.so")
        if large_mb:
            with archive.open("assets/lifecycle-padding.bin", "w") as output:
                chunk = bytes(1024 * 1024)
                for _ in range(large_mb):
                    output.write(chunk)
    aligned, signed = work / "aligned.apk", work / "fixture.apk"
    subprocess.run(["zipalign", "-f", "4", str(unsigned), str(aligned)], env=ENV, check=True)
    subprocess.run(["apksigner", "sign", "--ks", str(Path.home() / ".android/debug.keystore"),
                    "--ks-pass", "pass:android", "--out", str(signed), str(aligned)], env=ENV, check=True)
    return signed


def guest(out, label, *args):
    started = time.monotonic()
    command = [sys.executable, str(ROOT / "tools/apk-guest-command.py"), *args]
    try:
        result = subprocess.run(command, env=ENV, capture_output=True, text=True, timeout=25)
        text = result.stdout + result.stderr
    except subprocess.TimeoutExpired as failure:
        text = (failure.stdout or b"").decode(errors="replace") + (failure.stderr or b"").decode(errors="replace")
        (out / (label + ".log")).write_text(text + "\nTIMED OUT\n", encoding="utf-8")
        raise AssertionError("Guest call blocked: " + label) from failure
    (out / (label + ".log")).write_text(text, encoding="utf-8")
    if result.returncode:
        raise AssertionError(label + ": " + text[-1500:])
    return text, round(time.monotonic() - started, 3)


def markers():
    paths = " ".join(DATA + "/" + tree + "/0/" + PACKAGE for tree in ("user", "user_de"))
    paths += " files/guest-runtime/rootfs/storage/emulated/0/Android/data/" + PACKAGE
    script = "for dir in " + paths + '; do if [ -d "$dir" ]; then find "$dir" -name marker; fi; done'
    return desktop.device("run-as io.a10vm /system/bin/sh -c " + shlex.quote(script)).decode().splitlines()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    parser.add_argument("--large-mb", type=int, default=0, help="Add a stored APK asset and CE/DE data of this size")
    parser.add_argument("--keystore", action="store_true", help="Verify real application AES-GCM keys through clearing and uninstall")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid evidence label")
    if not 0 <= args.large_mb <= 1024:
        parser.error("Expected 0 to 1024 MiB")
    out = ROOT / "artifacts/clear-data" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "package": PACKAGE, "rootRequiredByGuest": False}
    try:
        server_pid = re.search(r"^desktop_pid=(\d+)$", desktop.log("framework-server.log"), re.M).group(1)
        report["systemServerPid"] = int(server_pid)
        fixture = build_fixture(args.large_mb)
        report.update(apkBytes=fixture.stat().st_size, largeDataBytesPerTree=args.large_mb * 1024 * 1024)
        guest(out, "install", "--install", str(fixture))
        path, _ = guest(out, "installed-path", "package", "path", PACKAGE)
        code_path = re.search(r"^package:(/data/app/[^\n]+)/base\.apk$", path, re.M).group(1)
        details, _ = guest(out, "installed-details", "package", "dump", PACKAGE)
        uid = re.search(r"\buserId=(\d+)", details).group(1)
        launch = ["activity", "start", "-n", PACKAGE + "/.DataActivity"]
        if args.keystore:
            launch += ["--ez", "keystore", "true"]
        if args.large_mb:
            launch += ["--ez", "large", "true"]
        for cycle in range(1 if args.large_mb else 2):
            prefix = str(cycle) + "-"
            guest(out, prefix + "launch", *launch)
            guest(out, prefix + "drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", PACKAGE)
            before = markers()
            assert len(before) == 7, "Fixture did not populate CE/DE/cache/external storage: " + str(before)
            if args.large_mb:
                sizes = desktop.device("run-as io.a10vm stat -c %s " + " ".join(
                    DATA + "/" + tree + "/0/" + PACKAGE + "/files/clear-probe/nested/marker"
                    for tree in ("user", "user_de"))).decode().splitlines()
                assert sizes == [str(args.large_mb * 1024 * 1024)] * 2, "Large data fixture changed: " + str(sizes)
            clear, seconds = guest(out, prefix + "clear", "package", "clear", "--user", "0", PACKAGE)
            assert "Success\n" in clear, "Clear callback did not succeed: " + clear
            after = markers()
            assert not after, "Clear left application data: " + str(after)
            guest(out, prefix + "home", "activity", "start", "-a", "android.intent.action.MAIN",
                  "-c", "android.intent.category.HOME")
            guest(out, prefix + "home-drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", "com.android.launcher3")
            report.setdefault("cycles", []).append({"clearSeconds": seconds, "markersBefore": len(before),
                                                    "markersAfter": len(after), "desktopResponsive": True})
            print(json.dumps(report["cycles"][-1]), flush=True)
        guest(out, "relaunch", *launch)
        guest(out, "relaunch-drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", PACKAGE)
        prefs = desktop.device("run-as io.a10vm cat " + DATA + "/user/0/" + PACKAGE + "/shared_prefs/probe.xml").decode()
        assert 'value="1"' in prefs, "Preferences did not reset: " + prefs
        if args.keystore:
            guest(out, "key-persistence-stop", "activity", "force-stop", PACKAGE)
            guest(out, "key-persistence-launch", *launch)
            guest(out, "key-persistence-drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", PACKAGE)
        guest(out, "finish-home", "activity", "start", "-a", "android.intent.action.MAIN",
              "-c", "android.intent.category.HOME")
        guest(out, "uninstall", "package", "uninstall", PACKAGE)
        guest(out, "finish-home-drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", "com.android.launcher3")
        # Package removal broadcasts finish after the uninstall result is delivered.
        for _ in range(6):
            status = desktop.device("cat /proc/" + server_pid + "/status").decode()
            assert re.search(r"^State:\s*[ZRXT]", status, re.M) is None, "System server exited after uninstall"
            assert "desktop_pid=" + server_pid + "\n" in desktop.log("framework-server.log"), "System server restarted"
            time.sleep(.5)
        listing, _ = guest(out, "removed-package", "package", "list", "packages", PACKAGE)
        assert "package:" + PACKAGE + "\n" not in listing, "Package remained registered"
        desktop.device("run-as io.a10vm test ! -e files/guest-runtime/rootfs" + code_path)
        assert not markers(), "Uninstall left fixture data"
        if args.keystore:
            guest(out, "uid-keys-removed", "--uid", uid, "--main", "io.a10vm.guest.GuestKeyStoreCheck",
                  "cleared", "a10vm-lifecycle-fixture")
            report["nativeKeyStoreLifecycle"] = True
        report["codeRemoved"] = True
        report["externalStorageAliases"] = 7
        report["fixtureRemoved"] = True
        report["passed"] = True
    except Exception as failure:
        report["error"] = str(failure)
        try:
            guest(out, "failure-stop-fixture", "activity", "force-stop", PACKAGE)
        except Exception:
            pass
    finally:
        for name in ("framework-server.log", "framework-installer.log"):
            (out / name).write_text(desktop.log(name), encoding="utf-8")
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
