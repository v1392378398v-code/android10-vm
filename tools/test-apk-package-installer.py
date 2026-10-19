#!/usr/bin/env python3
"""Open the real installer from an app declaring REQUEST_INSTALL_PACKAGES."""
import argparse
import io
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import zipfile
from PIL import Image

spec = importlib.util.spec_from_file_location("desktop", Path(__file__).with_name("test-apk-desktop.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
ROOT, ENV = desktop.ROOT, desktop.ENV
SOURCE = "io.a10vm.fixture.installer"
TARGET = "io.a10vm.fixture.installtarget"


def build(out):
    sdk = Path.home() / "Android/Sdk"
    android = sdk / "platforms/android-35/android.jar"
    source = ROOT / "tools/fixtures/package-installer"
    classes, dex = out / "classes", out / "dex"
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    def run(*args):
        subprocess.run(args, env=ENV, check=True, capture_output=True)
    run("javac", "--release", "8", "-cp", str(android), "-d", str(classes), str(source / "InstallActivity.java"))
    run("bash", str(sdk / "build-tools/35.0.0/d8"), "--min-api", "29", "--lib", str(android),
        "--output", str(dex), *map(str, classes.rglob("*.class")))
    artifacts = []
    for name, manifest in (("source", "AndroidManifest.xml"), ("target", "TargetManifest.xml")):
        unsigned, aligned, signed = (out / (name + suffix) for suffix in ("-unsigned.apk", "-aligned.apk", ".apk"))
        run("aapt2", "link", "--manifest", str(source / manifest), "-I", str(android), "-o", str(unsigned))
        with zipfile.ZipFile(unsigned, "a") as archive:
            archive.write(dex / "classes.dex", "classes.dex")
        run("zipalign", "-f", "4", str(unsigned), str(aligned))
        run("apksigner", "sign", "--ks", str(Path.home() / ".android/debug.keystore"),
            "--ks-pass", "pass:android", "--out", str(signed), str(aligned))
        unsigned.unlink()
        aligned.unlink()
        artifacts.append(signed)
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default="io.a10vm.miui", choices=("io.a10vm", "io.a10vm.miui"))
    parser.add_argument("--label", default="current")
    parser.add_argument("--max-prepare-seconds", type=float, default=8)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid label")
    desktop.PACKAGE = args.package
    device = desktop.device
    desktop.device = lambda command, timeout=15: device("PATH=/system/bin:/system/xbin " + command, timeout)
    out = ROOT / "artifacts/package-installer" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "package": args.package, "source": SOURCE, "target": TARGET}
    def guest(label, *command, check=True):
        result = subprocess.run(["python3", str(ROOT / "tools/apk-guest-command.py"), "--package", args.package,
            "--uid", "1000", *command], env=ENV, capture_output=True, text=True, timeout=30)
        (out / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        if check:
            assert result.returncode == 0, label + ": " + result.stdout[-1200:] + result.stderr[-300:]
        return result.stdout
    def installer_ui(label):
        path = "/data/local/tmp/a10vm-installer-ui.png"
        guest(label, "--native", "image/system/bin/screencap", "-p", path)
        data = desktop.device("run-as " + args.package + " cat files/guest-runtime/rootfs" + path)
        (out / (label + ".png")).write_bytes(data)
        return Image.open(io.BytesIO(data)).convert("RGB")
    def button(screen):
        # The paired MIUI installer uses one wide blue confirmation button.
        # Locate its actual raster bounds instead of assuming a device resolution.
        rows = []
        for y in range(screen.height // 2, screen.height):
            blue = sum(1 for x in range(0, screen.width, 4)
                if (lambda p: p[0] < 70 and 90 < p[1] < 210 and p[2] > 230)(screen.getpixel((x, y))))
            if blue >= screen.width * .6 / 4:
                rows.append(y)
        if len(rows) >= screen.height * .015:
            return screen.width // 2, (rows[0] + rows[-1]) // 2
        return None
    def tap(label, point):
        guest(label, "--main", "io.a10vm.guest.GuestTap", *map(str, point))
    try:
        desktop.device("/system/bin/am start -n " + args.package + "/io.a10vm.ui.FullscreenActivity")
        source, target = build(out)
        if "package:" in guest("target-before", "package", "path", TARGET, check=False):
            guest("target-remove", "package", "uninstall", TARGET)
        guest("source-install", "--install", str(source))
        guest("source-permission", "package", "grant", SOURCE, "android.permission.READ_EXTERNAL_STORAGE")
        guest("source-appop", "appops", "set", SOURCE, "REQUEST_INSTALL_PACKAGES", "allow")
        guest("source-stop", "activity", "force-stop", SOURCE)
        guest("installer-stop", "activity", "force-stop", "com.miui.packageinstaller")
        path = "/storage/emulated/0/Download/a10vm-ui-install-target.apk"
        physical = "files/guest-runtime/rootfs" + path
        script = "cat > " + shlex.quote(physical)
        with target.open("rb") as stream:
            subprocess.run(["su", "-c", "PATH=/system/bin:/system/xbin run-as " + args.package +
                " /system/bin/sh -c " + shlex.quote(script)], env=ENV, stdin=stream, check=True, timeout=10)
        started = time.monotonic()
        guest("source-launch", "activity", "start", "-n", SOURCE + "/io.a10vm.fixture.installer.InstallActivity",
            "-e", "apk", path)
        pid = None
        deadline = started + 35
        text = ""
        while time.monotonic() < deadline:
            server = desktop.log("framework-server.log")
            pids = re.findall(r"desktop_application_launch=(\d+):com.miui.packageinstaller\b", server)
            if pids:
                pid = pids[-1]
                script = ("grep -l -E " + shlex.quote("application_pid=" + pid + "$") +
                    " files/guest-runtime/application-*.log")
                logs = desktop.device("run-as " + args.package + " /system/bin/sh -c " + shlex.quote(script)).decode().splitlines()
                if logs:
                    text = desktop.log(Path(logs[-1]).name)
            screen = installer_ui("prepare-ui")
            install = button(screen)
            if install is not None:
                report["prepareSeconds"] = round(time.monotonic() - started, 3)
                break
            time.sleep(.2)
        (out / "installer.log").write_text(text, encoding="utf-8")
        assert report.get("prepareSeconds", 35) <= args.max_prepare_seconds, "Installer scan blocked on cloud preparation"
        report["networkError"] = "MIUIPI_NetworkErrorUtils" in text
        assert not report["networkError"], "Installer displayed the cloud network error"
        tap("install-tap", install)
        deadline = time.monotonic() + 35
        attempts = 0
        while time.monotonic() < deadline:
            installed = guest("target-installed", "package", "path", TARGET, check=False)
            if "package:" in installed:
                report["installed"] = True
                report["installedPath"] = re.search(r"^package:(.+)$", installed, re.M).group(1)
                break
            confirm = button(installer_ui("confirmation-ui"))
            if confirm is not None:
                attempts += 1
                assert attempts <= 2, "Installer repeatedly requested confirmation"
                tap("confirmation-tap", confirm)
            time.sleep(.2)
        assert report.get("installed"), "GUI installation did not create the target package"
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
