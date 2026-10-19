#!/usr/bin/env python3
"""Measure visible desktop motion and exercise sustained APK touch input."""
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    parser.add_argument("--min-motion-fps", type=float, default=20)
    args = parser.parse_args()
    output = desktop.OUT / ("interaction-" + args.label)
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "label": args.label}
    recorder = None
    try:
        node = next((node for node in desktop.ui().iter("node")
                     if node.get("content-desc") == "Android 10 桌面"), None)
        assert node is not None, "Open the APK desktop Surface before measuring gestures"
        left, top, right, bottom = map(int, re.findall(r"\d+", node.get("bounds")))
        width, height = right - left, bottom - top

        def point(x, y):
            return round(left + x * width / 360), round(top + y * height / 640)

        def tap(x, y):
            desktop.device("/system/bin/input tap %d %d" % point(x, y))

        tap(180, 615)
        time.sleep(.5)
        remote = "/data/local/tmp/a10vm-interaction-" + args.label + ".mp4"
        recorder = subprocess.Popen(["su", "-c", "/system/bin/screenrecord --size 360x792 "
                                    "--bit-rate 2000000 --time-limit 9 " + shlex.quote(remote)],
                                   env=desktop.ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(.4)
        started = time.monotonic()
        gestures = []
        for index in range(3):
            for start, end in ((550, 130), (130, 550)):
                stamp = time.monotonic() - started
                desktop.device("/system/bin/input swipe %d %d %d %d 850" % (*point(180, start), *point(180, end)))
                gestures.append({"startSeconds": round(stamp, 3), "upward": start > end})
        report["gestureSeconds"] = round(time.monotonic() - started, 3)
        report["gestures"] = gestures
        stdout, stderr = recorder.communicate(timeout=12)
        assert recorder.returncode == 0, stderr.decode(errors="replace")
        movie = output / "gestures.mp4"
        movie.write_bytes(desktop.device("cat " + shlex.quote(remote)))
        crop_top = round((top + height * .12) * 792 / 3168)
        crop_height = round(height * .67 * 792 / 3168)
        crop_left = round(left * 360 / 1440)
        crop_width = round(width * 360 / 1440)
        analysis = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(movie), "-vf",
            "crop=%d:%d:%d:%d,scale=90:120,mpdecimate,showinfo" %
            (crop_width, crop_height, crop_left, crop_top), "-an", "-f", "null", "-"],
            capture_output=True, text=True, check=True, env=desktop.ENV)
        stamps = [float(value) for value in re.findall(r"pts_time:([\d.]+)", analysis.stderr)]
        # Ignore recording setup and the idle tail. Only count visibly different frames during gestures.
        active = [stamp for stamp in stamps if .4 <= stamp <= .4 + report["gestureSeconds"]]
        report["visibleMotionFps"] = round(len(active) / report["gestureSeconds"], 2)
        report["maxVisibleFrameGapMs"] = round(max((b - a for a, b in zip(active, active[1:])), default=9) * 1000, 2)
        report["inputHealthy"] = "FATAL EXCEPTION" not in desktop.log("framework-input.log")
        (output / "input.log").write_text(desktop.log("framework-input.log"), encoding="utf-8")
        assert report["inputHealthy"], "Sustained gesture stopped the input process"
        assert report["visibleMotionFps"] >= args.min_motion_fps, "Desktop gestures update too slowly"
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error) or repr(error)
    finally:
        if recorder is not None and recorder.poll() is None:
            recorder.terminate()
        (output / "screen.png").write_bytes(desktop.device("/system/bin/screencap -p"))
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
