#!/usr/bin/env python3
"""Check guest and host video pixels across video switches or host Surface replacement."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/test-apk-desktop.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def guest(out, label, *arguments):
    result = subprocess.run([sys.executable, str(ROOT / "tools/apk-guest-command.py"), *arguments],
                            env=desktop.ENV, capture_output=True, text=True, timeout=30)
    (out / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise AssertionError("Guest command failed: " + label)
    return result.stdout


def sample(out, label, count, region, interval):
    bounds = None
    for node in desktop.ui().iter("node"):
        if node.get("content-desc") == "Android 10 桌面":
            bounds = tuple(map(int, re.findall(r"\d+", node.get("bounds"))))
            break
    if bounds is None:
        raise AssertionError("Host desktop Surface is not visible")
    layers = {"guest": {"frames": [], "samples": []}, "host": {"frames": [], "samples": []}}
    for index in range(count):
        target = "/data/local/tmp/a10vm-bilibili-video.png"
        guest(out, label + "-capture-" + str(index), "--native", "image/system/bin/screencap", "-p", target)
        path = out / (label + "-" + str(index) + ".png")
        path.write_bytes(desktop.device("run-as io.a10vm cat files/guest-runtime/rootfs" + target))
        screen = Image.open(path).convert("RGB")
        host_path = out / (label + "-host-" + str(index) + ".png")
        if desktop.screenshot(host_path) is None:
            raise AssertionError("Host app lost foreground during capture")
        for name, viewport in (("guest", screen), ("host", Image.open(host_path).convert("RGB").crop(bounds))):
            box = tuple(round(value * size) for value, size in zip(region, (viewport.width, viewport.height) * 2))
            frame = viewport.crop(box).resize((160, 90))
            pixels = list(frame.get_flattened_data())
            item = {"nonBlackFraction": round(sum(max(p) > 24 for p in pixels) / len(pixels), 4)}
            layer = layers[name]
            if layer["frames"]:
                item["pixelChange"] = round(sum(ImageStat.Stat(ImageChops.difference(layer["frames"][-1], frame)).mean) / 3, 3)
            layer["frames"].append(frame)
            layer["samples"].append(item)
        time.sleep(interval)
    result = {}
    for name, layer in layers.items():
        samples = layer["samples"]
        changing = sum(s.get("pixelChange", 0) > 1 for s in samples)
        result[name] = {"samples": samples, "changingFrames": changing,
                        "passed": all(s["nonBlackFraction"] > .10 for s in samples) and changing >= count - 1}
    result["passed"] = all(layer["passed"] for layer in result.values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="bilibili-current")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--background", action="store_true", help="Send the host app to Home before returning")
    parser.add_argument("--background-seconds", type=float, default=.5)
    parser.add_argument("--sample-interval", type=float, default=.5)
    parser.add_argument("--switch-video", nargs="+", type=int, help="Cycle through these video IDs")
    parser.add_argument("--expected-activity", help="Exact component for a different video playback layout")
    parser.add_argument("--settle-seconds", type=float, default=1)
    parser.add_argument("--region", default="0.05,0.08,0.95,0.30", help="Normalized video crop x0,y0,x1,y1")
    args = parser.parse_args()
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label) or args.cycles < 1 or args.samples < 2
            or args.background_seconds < 0 or args.sample_interval < 0 or args.settle_seconds < 0
            or (args.switch_video and any(video <= 0 for video in args.switch_video))):
        parser.error("Invalid label, cycles or samples")
    region = tuple(float(v) for v in args.region.split(","))
    if len(region) != 4 or not (0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1):
        parser.error("Invalid video crop")
    out = ROOT / "artifacts/app-compat" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "region": region, "cycles": [], "rootRequiredByGuest": False,
              "deviceRootUsedForAutomation": True,
              "backgroundSeconds": args.background_seconds, "sampleInterval": args.sample_interval,
              "trigger": "video switch" if args.switch_video else
              "host background" if args.background else "host Surface replacement"}
    try:
        server = desktop.log("framework-server.log")
        server_pid = re.search(r"^desktop_pid=(\d+)$", server, re.M).group(1)
        time.sleep(args.settle_seconds)
        drawn = guest(out, "drawn-before", "--main", "io.a10vm.guest.DesktopTaskCheck", "tv.danmaku.bili")
        activity = re.search(r"^desktop_task_drawn=(.+)$", drawn, re.M).group(1)
        if args.expected_activity:
            if activity != args.expected_activity:
                raise AssertionError("Unexpected Bilibili playback activity: " + activity)
        elif "DetailsActivity" not in activity and "VideoDetailsActivity" not in activity:
            raise AssertionError("Bilibili video detail page is not foreground: " + activity)
        report["activity"] = activity
        if not args.capture_only:
            desktop.device("/system/bin/am start --activity-reorder-to-front -n io.a10vm/.ui.FullscreenActivity")
            time.sleep(.5)
        report["before"] = sample(out, "before", args.samples, region, args.sample_interval)
        if not report["before"]["passed"]:
            raise AssertionError("Bilibili video is already black or frozen before Surface replacement")
        if not args.capture_only:
            for cycle in range(args.cycles):
                if args.switch_video:
                    video = args.switch_video[cycle % len(args.switch_video)]
                    guest(out, "switch-" + str(cycle), "activity", "start", "-a", "android.intent.action.VIEW",
                          "-d", "bilibili://video/" + str(video), "-p", "tv.danmaku.bili")
                elif args.background:
                    desktop.device("/system/bin/am start -a android.intent.action.MAIN -c android.intent.category.HOME")
                else:
                    desktop.device("/system/bin/am start --activity-reorder-to-front -n io.a10vm/.ui.MainActivity")
                if not args.switch_video:
                    time.sleep(args.background_seconds)
                desktop.device("/system/bin/am start --activity-reorder-to-front -n io.a10vm/.ui.FullscreenActivity")
                time.sleep(args.settle_seconds)
                current = guest(out, "drawn-return-" + str(cycle), "--main",
                                "io.a10vm.guest.DesktopTaskCheck", "tv.danmaku.bili")
                if "desktop_task_drawn=" + activity + "\n" not in current:
                    raise AssertionError("Bilibili navigated away from the original video")
                result = sample(out, "return-" + str(cycle), args.samples, region, args.sample_interval)
                if args.switch_video:
                    result["videoId"] = video
                report["cycles"].append(result)
                if not result["passed"]:
                    raise AssertionError("Bilibili video became black or frozen after " + report["trigger"])
        status = desktop.device("run-as io.a10vm cat /proc/" + server_pid + "/status").decode()
        if re.search(r"^State:\s*[ZXTt]", status, re.M):
            raise AssertionError("Guest system server stopped")
        report.update(passed=True, sameSystemServerPid=int(server_pid))
    except Exception as failure:
        report["error"] = str(failure)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
