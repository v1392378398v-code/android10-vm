#!/usr/bin/env python3
"""Compare native, WebView and HTML video pixels and touch on the installed guest."""
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
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/test-apk-desktop.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
ENV = desktop.ENV
PACKAGE = "io.a10vm.fixture.webview"
SOURCE = ROOT / "tools/fixtures/webview-viewport"
WORK = ROOT / "artifacts/webview-viewport/fixture"


def build():
    sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk")))
    android = sdk / "platforms/android-35/android.jar"
    for directory in (WORK / "classes", WORK / "dex"):
        directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(["javac", "--release", "8", "-cp", str(android), "-d", str(WORK / "classes"),
                    str(SOURCE / "ViewportActivity.java")], env=ENV, check=True)
    subprocess.run(["bash", str(sdk / "build-tools/35.0.0/d8"), "--min-api", "29", "--lib", str(android),
                    "--output", str(WORK / "dex"), *map(str, (WORK / "classes").rglob("*.class"))],
                   env=ENV, check=True)
    video = WORK / "viewport.mp4"
    if not video.is_file():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "color=c=0x304030:s=640x360:r=24,drawbox=x=140:y=0:w=360:h=360:color=0xff6000:t=fill",
            "-t", "3", "-an", "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(video)], env=ENV, check=True)
    playback = WORK / "playback.mp4"
    if not playback.is_file():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=640x360:rate=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "12", "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(playback)], env=ENV, check=True)
    unsigned, aligned, signed = (WORK / name for name in ("unsigned.apk", "aligned.apk", "webview-viewport.apk"))
    subprocess.run(["aapt2", "link", "--manifest", str(SOURCE / "AndroidManifest.xml"),
                    "-I", str(android), "-o", str(unsigned)], env=ENV, check=True)
    with zipfile.ZipFile(unsigned, "a") as archive:
        archive.write(WORK / "dex/classes.dex", "classes.dex")
        archive.write(SOURCE / "viewport.html", "assets/viewport.html")
        archive.write(video, "assets/viewport.mp4")
        archive.write(SOURCE / "playback.html", "assets/playback.html")
        archive.write(playback, "assets/playback.mp4")
    subprocess.run(["zipalign", "-f", "4", str(unsigned), str(aligned)], env=ENV, check=True)
    subprocess.run(["apksigner", "sign", "--ks", str(Path.home() / ".android/debug.keystore"),
                    "--ks-pass", "pass:android", "--out", str(signed), str(aligned)], env=ENV, check=True)
    return signed


def guest(out, label, *args):
    result = subprocess.run([sys.executable, str(ROOT / "tools/apk-guest-command.py"), *args],
                            env=ENV, capture_output=True, text=True, timeout=30)
    text = result.stdout + result.stderr
    (out / (label + ".log")).write_text(text, encoding="utf-8")
    if result.returncode:
        raise AssertionError(label + ": " + text[-1000:])
    return text


def read_report():
    return json.loads(desktop.device("run-as io.a10vm cat files/guest-runtime/rootfs/data/user/0/" +
                                    PACKAGE + "/files/viewport.json"))


def bounds(image, color, region=None):
    pixels = image.convert("RGB")
    if region:
        pixels = pixels.crop(region)
    mask = Image.new("1", pixels.size)
    mask.putdata([all(abs(p[i] - color[i]) <= 16 for i in range(3)) for p in pixels.getdata()])
    box = mask.getbbox()
    if box is None:
        raise AssertionError("Rendered color missing: " + str(color))
    return tuple(value + region[index % 2] for index, value in enumerate(box)) if region else box


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="current")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--guest-only", action="store_true", help="Capture and inject inside the guest")
    parser.add_argument("--software", action="store_true", help="Force the WebView software Canvas for diagnosis")
    parser.add_argument("--url", help="Open a video page in the same fixture after the local checks")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid evidence label")
    apk = build()
    print("fixture_apk=" + str(apk), flush=True)
    if args.build_only:
        return 0
    out = ROOT / "artifacts/webview-viewport" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "rootRequiredByGuest": False}
    try:
        guest(out, "install", "--install", str(apk))
        guest(out, "stop", "activity", "force-stop", PACKAGE)
        fixture_id = str(time.time_ns())
        launch = ["activity", "start", "-n", PACKAGE + "/.ViewportActivity", "--es", "fixtureId", fixture_id]
        if args.software:
            launch += ["--ez", "software", "true"]
        guest(out, "launch", *launch)
        guest(out, "drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", PACKAGE)
        deadline = time.monotonic() + 15
        while True:
            try:
                metrics = read_report()
                if metrics.get("fixtureId") == fixture_id and metrics["video"]["readyState"] >= 2:
                    break
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                pass
            if time.monotonic() > deadline:
                raise AssertionError("HTML video did not become ready")
            time.sleep(.5)
        report["metrics"] = metrics
        if args.guest_only:
            target = "/data/local/tmp/a10vm-viewport.png"
            guest(out, "capture", "--native", "image/system/bin/screencap", "-p", target)
            (out / "screen.png").write_bytes(desktop.device("run-as io.a10vm cat " +
                "files/guest-runtime/rootfs" + target))
            image = Image.open(out / "screen.png")
            left, top, right, bottom = 0, 0, image.width, image.height
            report["hostSurfaceVerified"] = False
        else:
            ui = desktop.ui()
            surfaces = [node for node in ui.iter("node") if node.get("content-desc") == "Android 10 桌面"]
            if len(surfaces) != 1:
                raise AssertionError("Guest Surface is not in the foreground")
            left, top, right, bottom = map(int, re.findall(r"\d+", surfaces[0].get("bounds")))
            if desktop.screenshot(out / "screen.png") is None:
                raise AssertionError("Guest Surface lost foreground before capture")
            image = Image.open(out / "screen.png").crop((left, top, right, bottom))
            report["hostSurfaceVerified"] = True
        image.save(out / "guest.png")
        boxes, errors = {}, []
        native = metrics["native"]
        expected = {}
        for name in ("square", "circle", "canvas", "touch", "fixed", "fixedCircle", "groupLeft", "groupRight"):
            rect = metrics[name]
            x = (native["x"] + rect["x"] * metrics["dpr"]) * image.width / 1080
            y = (native["y"] + rect["y"] * metrics["dpr"]) * image.height / 1920
            width = rect["width"] * metrics["dpr"] * image.width / 1080
            height = rect["height"] * metrics["dpr"] * image.height / 1920
            expected[name] = [round(v, 2) for v in (x, y, x + width, y + height)]
        for name, color in {
            "nativeSquare": (0, 180, 80), "nativeCircle": (230, 0, 200),
            "square": (230, 0, 0), "circle": (0, 96, 255), "canvas": (255, 176, 0),
            "videoSquare": (255, 96, 0), "touch": (0, 220, 220),
            "fixed": (160, 32, 192), "fixedCircle": (0, 144, 144),
            "groupLeft": (48, 80, 200), "groupRight": (17, 17, 17)}.items():
            try:
                # Limit color matching to the target, not similarly colored antialiased text elsewhere.
                region = None
                if name in expected:
                    x, y, r, b = expected[name]
                    region = (max(0, int(x) - 8), max(0, int(y) - 8),
                              min(image.width, int(r) + 9), min(image.height, int(b) + 9))
                boxes[name] = bounds(image, color, region)
            except AssertionError as failure:
                errors.append(name + ": " + str(failure))
        report["pixelBounds"] = boxes
        for name in ("nativeSquare", "nativeCircle", "square", "circle", "canvas", "videoSquare", "fixedCircle"):
            if name not in boxes:
                continue
            x, y, r, b = boxes[name]
            ratio = (r - x) / (b - y)
            if abs(ratio - 1) > .03:
                errors.append(name + " aspect=" + str(round(ratio, 4)))
        if abs(metrics["dpr"] - native["density"]) > .01 or \
                abs(metrics["viewport"]["width"] * metrics["dpr"] - native["width"]) > 1:
            errors.append("WebView/native viewport mismatch")
        for name in expected:
            if name in boxes and any(abs(a - b) > 3 for a, b in zip(boxes[name], expected[name])):
                errors.append(name + " rendered bounds disagree with DOM: " + str(boxes[name]) +
                              " vs " + str(expected[name]))
        report["expectedBounds"] = expected
        touch = metrics["touch"]
        x = (native["x"] + (touch["x"] + touch["width"] / 2) * metrics["dpr"]) * (right - left) / 1080
        y = (native["y"] + (touch["y"] + touch["height"] / 2) * metrics["dpr"]) * (bottom - top) / 1920
        if args.guest_only:
            guest(out, "touch", "--native", "image/system/bin/sh", "-c",
                  "/system/bin/input tap %d %d" % (x, y))
        else:
            desktop.device("/system/bin/input tap %d %d" % (left + x, top + y))
        time.sleep(1)
        after = read_report()
        report["touchClicked"] = after["clicks"] == metrics["clicks"] + 1
        report["videoAdvancing"] = after["video"]["time"] != metrics["video"]["time"] and not after["video"]["paused"]
        if not report["touchClicked"]:
            errors.append("Rendered touch target is not at its DOM coordinates")
        if not report["videoAdvancing"]:
            errors.append("HTML video did not advance")
        report["errors"] = errors
        report["passed"] = not errors
        if args.url:
            guest(out, "video-page-stop", "activity", "force-stop", PACKAGE)
            guest(out, "video-page-launch", "activity", "start", "-n", PACKAGE + "/.ViewportActivity",
                  "--es", "url", args.url)
            time.sleep(5)
            desktop.screenshot(out / "video-page.png")
    except Exception as failure:
        report["error"] = str(failure)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
