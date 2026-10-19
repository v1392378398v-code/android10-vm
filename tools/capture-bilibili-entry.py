#!/usr/bin/env python3
"""Capture guest video entry frames before waiting for playback to settle."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/test-apk-desktop.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--interval", type=float, default=.10)
    args = parser.parse_args()
    if (args.video <= 0 or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label)
            or not 2 <= args.frames <= 90 or not 0 <= args.interval <= 2):
        parser.error("Invalid video, label, frame count or interval")
    out = ROOT / "artifacts/app-compat" / args.label
    out.mkdir(parents=True, exist_ok=True)
    config = desktop.device("run-as io.a10vm cat files/guest-runtime/ld.config.txt").decode()
    runtime = next(path for path in re.findall(r"^dir\.guest = (.+)$", config, re.M)
                   if Path(path).name == "guest-runtime")
    guest_path = "/data/local/tmp/bili-entry-" + str(time.monotonic_ns())
    host_path = runtime + "/rootfs" + guest_path
    script = "mkdir -p " + shlex.quote(guest_path) + "\n"
    script += "printf ready > " + shlex.quote(guest_path + "/ready") + "\n"
    script += "i=0\nwhile [ \"$i\" -lt " + str(args.frames) + " ]; do\n"
    script += "  date +%s%N >> " + shlex.quote(guest_path + "/times") + "\n"
    script += "  /system/bin/screencap -p " + shlex.quote(guest_path) + "/frame-$i.png\n"
    script += "  i=$((i + 1))\n  sleep " + str(args.interval) + "\ndone\n"
    capture_log = (out / "capture.log").open("w", encoding="utf-8")
    recorder = subprocess.Popen([sys.executable, str(ROOT / "tools/apk-guest-command.py"),
                                 "--native", "image/system/bin/sh", "-c", script],
                                env=desktop.ENV, stdout=capture_log, stderr=subprocess.STDOUT)
    report = {"captured": False, "video": args.video, "frames": args.frames,
              "rootRequiredByGuest": False, "deviceRootUsedForAutomation": True,
              "visualVerdict": "Review the entry frame grid", "samples": []}
    try:
        deadline = time.monotonic() + 10
        while not desktop.device("run-as io.a10vm sh -c " + shlex.quote(
                "if test -f " + shlex.quote(host_path + "/ready") + "; then printf ready; fi")):
            if recorder.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Entry recorder did not start")
            time.sleep(.05)
        with (out / "launch.log").open("w", encoding="utf-8") as log:
            subprocess.run([sys.executable, str(ROOT / "tools/apk-guest-command.py"),
                "activity", "start", "-a", "android.intent.action.VIEW", "-d",
                "bilibili://video/" + str(args.video), "-p", "tv.danmaku.bili"],
                env=desktop.ENV, stdout=log, stderr=subprocess.STDOUT, timeout=30, check=True)
        if recorder.wait(timeout=90) != 0:
            raise RuntimeError("Entry recorder failed")
        timestamps = desktop.device("run-as io.a10vm cat " + shlex.quote(host_path + "/times")).decode().splitlines()
        grid = Image.new("RGB", (1080, 300 * ((args.frames + 3) // 4)), "white")
        draw = ImageDraw.Draw(grid)
        for index in range(args.frames):
            path = out / ("frame-" + str(index) + ".png")
            path.write_bytes(desktop.device("run-as io.a10vm cat " + shlex.quote(
                host_path + "/frame-" + str(index) + ".png")))
            frame = Image.open(path).convert("RGB")
            preview = frame.crop((0, 0, frame.width, round(frame.height * .55))).resize((270, 264))
            x, y = index % 4 * 270, index // 4 * 300
            elapsed = (int(timestamps[index]) - int(timestamps[0])) / 1e9
            draw.text((x + 5, y + 5), f"frame={index} t={elapsed:.3f}s", fill="black")
            grid.paste(preview, (x, y + 24))
            report["samples"].append({"index": index, "seconds": round(elapsed, 3), "path": str(path.relative_to(ROOT))})
        grid.save(out / "entry-grid.jpg")
        report["captured"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        if recorder.poll() is None:
            recorder.terminate()
            recorder.wait(timeout=5)
        capture_log.close()
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, indent=2))
    return 0 if report["captured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
