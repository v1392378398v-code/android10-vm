#!/usr/bin/env python3
"""Require both advancing media time and changing presented pixels in guest WebView."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import time
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("viewport", ROOT / "tools/test-apk-webview-viewport.py")
viewport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewport)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="video-current")
    parser.add_argument("--muted", action="store_true")
    parser.add_argument("--guest-only", action="store_true", help="Capture the guest compositor without host UI focus")
    parser.add_argument("--standby-before", action="store_true", help="Stop Via and the fixture, then require audio standby")
    parser.add_argument("--seconds", type=int, default=8, choices=range(5, 10))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid evidence label")
    out = ROOT / "artifacts/webview-viewport" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "muted": args.muted, "hostSurfaceVerified": not args.guest_only,
              "samples": [], "pixelChanges": []}
    previous = None
    try:
        apk = viewport.build()
        if not args.guest_only:
            viewport.desktop.device("/system/bin/am start -W -n io.a10vm/.ui.FullscreenActivity")
            surfaces = [n for n in viewport.desktop.ui().iter("node")
                        if n.get("content-desc") == "Android 10 桌面"]
            if len(surfaces) != 1:
                raise AssertionError("Presented guest Surface missing")
            left, top, right, bottom = map(int, re.findall(r"\d+", surfaces[0].get("bounds")))
        viewport.guest(out, "install", "--install", str(apk))
        viewport.guest(out, "stop", "activity", "force-stop", viewport.PACKAGE)
        if args.standby_before:
            viewport.guest(out, "via-stop", "activity", "force-stop", "mark.via")
            deadline = time.monotonic() + 8
            while True:
                audio = viewport.guest(out, "audio-before", "--native", "image/system/bin/dumpsys",
                                       "media.audio_flinger")
                standby = re.search(r"^Output thread .*?^  Standby: (\w+)", audio, re.M | re.S)
                if standby and standby.group(1) == "yes":
                    report["audioStandbyBefore"] = True
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("Guest audio did not enter standby before playback")
                time.sleep(.5)
        fixture_id = str(time.time_ns())
        viewport.guest(out, "launch", "activity", "start", "-n", viewport.PACKAGE + "/.ViewportActivity",
                       "--es", "fixtureId", fixture_id, "--ez", "playback", "true",
                       "--ez", "muted", str(args.muted).lower())
        viewport.guest(out, "drawn", "--main", "io.a10vm.guest.DesktopTaskCheck", viewport.PACKAGE)
        deadline = time.monotonic() + 10
        while True:
            metrics = viewport.read_report()
            if metrics.get("fixtureId") == fixture_id and metrics["video"]["readyState"] >= 2:
                break
            if time.monotonic() >= deadline:
                raise AssertionError("Playback did not produce its first frame")
            time.sleep(.25)
        for index in range(args.seconds):
            metrics = viewport.read_report()
            if metrics.get("fixtureId") != fixture_id or metrics.get("visibility") != "visible":
                raise AssertionError("Playback fixture lost foreground")
            path = out / ("screen-%02d.png" % index)
            if args.guest_only:
                target = "/data/local/tmp/a10vm-playback.png"
                viewport.guest(out, "capture-%02d" % index, "--native", "image/system/bin/screencap", "-p", target)
                path.write_bytes(viewport.desktop.device("run-as io.a10vm cat " +
                    "files/guest-runtime/rootfs" + target))
            elif viewport.desktop.screenshot(path) is None:
                raise AssertionError("Host desktop Surface lost foreground")
            image = Image.open(path).convert("RGB")
            if args.guest_only:
                left, top, right, bottom = 0, 0, image.width, image.height
            native, video = metrics["native"], metrics["video"]
            x = left + (native["x"] + video["x"] * metrics["dpr"]) * (right - left) / 1080
            y = top + (native["y"] + video["y"] * metrics["dpr"]) * (bottom - top) / 1920
            width = video["width"] * metrics["dpr"] * (right - left) / 1080
            height = video["height"] * metrics["dpr"] * (bottom - top) / 1920
            frame = image.crop(tuple(round(v) for v in (x, y, x + width, y + height))).resize((160, 90))
            frame.save(out / ("video-%02d.png" % index))
            if previous is not None:
                report["pixelChanges"].append(round(sum(ImageStat.Stat(
                    ImageChops.difference(previous, frame)).mean) / 3, 3))
            previous = frame
            report["samples"].append(metrics)
            print(json.dumps({"sample": index, "video": video}), flush=True)
            time.sleep(.5)
        first, last = (report["samples"][i]["video"] for i in (0, -1))
        report["timeAdvanced"] = last["time"] - first["time"]
        report["framesDecoded"] = last["decodedFrames"] - first["decodedFrames"]
        report["changingScreens"] = sum(value > 1 for value in report["pixelChanges"])
        frame_skews = [abs(s["video"]["lastFrame"]["skewMs"]) for s in report["samples"]
                       if s["video"].get("lastFrame")]
        report["maxMediaFrameSkewMs"] = round(max(frame_skews), 3) if frame_skews else None
        report["passed"] = report["timeAdvanced"] >= 3 and report["framesDecoded"] >= 24 \
            and report["changingScreens"] >= 3 and bool(frame_skews) and max(frame_skews) <= 100 \
            and not any(s["video"]["error"] for s in report["samples"])
        audio = viewport.guest(out, "audio-after", "--native", "image/system/bin/dumpsys", "media.audio_flinger")
        latency = re.search(r"Threadloop write latency stats: ave=([\d.]+)", audio)
        if latency:
            report["audioLatencyMs"] = float(latency.group(1))
    except Exception as failure:
        report["error"] = str(failure)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
