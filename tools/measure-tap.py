#!/usr/bin/env python3
"""Measure a visible response to one host-side tap, only while A10VM has focus."""

import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import time
import zlib


def clock():
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def require_focus():
    windows = subprocess.check_output(["/system/bin/dumpsys", "window", "displays"], text=True)
    focused = re.search(r"mCurrentFocus=(.*)", windows)
    if focused is None or "io.a10vm/" not in focused[1]:
        raise RuntimeError("A10VM is not the focused window; no capture or tap performed")


def capture():
    require_focus()
    started = clock()
    raw = subprocess.check_output(["/system/bin/screencap"])
    width, height, kind = struct.unpack_from("<III", raw)
    if kind not in (1, 2) or width * height > 16777216:
        raise ValueError(f"Unexpected screen format: {width}x{height}, {kind}")
    header = len(raw) - width * height * 4
    if header not in (12, 16):
        raise ValueError(f"Unexpected screen header: {header}")
    return (width, height, raw[header:]), started, clock()


def sample(frame, region):
    width, height, pixels = frame
    left, top, right, bottom = region
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("Measurement region is outside the display")
    return [pixels[(y * width + x) * 4:(y * width + x) * 4 + 3]
            for y in range(top, bottom, 16) for x in range(left, right, 16)]


def difference(before, after):
    return sum(any(abs(a - b) > 12 for a, b in zip(old, new))
               for old, new in zip(before, after)) / len(before)


def write_png(path, frame):
    width, height, pixels = frame
    rows = b"".join(b"\0" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                     chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tap", nargs=2, type=int, required=True, metavar=("X", "Y"))
    parser.add_argument("--region", nargs=4, type=int, required=True, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--budget", type=float, default=1.5)
    args = parser.parse_args()
    if not 2 <= args.seconds <= 60:
        parser.error("Use a measurement window between 2 and 60 seconds")
    args.output.mkdir(parents=True, exist_ok=True)
    before, _, _ = capture()
    if not (0 <= args.tap[0] < before[0] and 0 <= args.tap[1] < before[1]):
        parser.error("Tap is outside the display")
    before_sample = sample(before, args.region)
    time.sleep(1)
    stable, _, _ = capture()
    idle_change = difference(before_sample, sample(stable, args.region))
    if idle_change > 0.02:
        raise RuntimeError(f"Baseline is still changing ({idle_change:.1%}); no tap performed")
    require_focus()
    started = clock()
    injection = subprocess.Popen(["/system/bin/input", "tap", *map(str, args.tap)])
    samples = []
    last_unchanged = 0
    injection_finished = None
    changed = None
    after = before
    try:
        while clock() - started < args.seconds:
            if injection_finished is None and injection.poll() is not None:
                if injection.returncode != 0:
                    raise RuntimeError("Host input command failed")
                injection_finished = clock() - started
            after, captured_start, captured_end = capture()
            delta = difference(before_sample, sample(after, args.region))
            samples.append({"captureStartSeconds": round(captured_start - started, 3),
                            "captureEndSeconds": round(captured_end - started, 3),
                            "changedFraction": round(delta, 4)})
            if delta > 0.10:
                changed = captured_end - started
                break
            last_unchanged = captured_start - started
            time.sleep(0.35)
    finally:
        injection.wait(timeout=5)
    report = {"passed": changed is not None and changed <= args.budget, "tap": args.tap,
              "region": args.region, "budgetSeconds": args.budget,
              "tapCommandStartSeconds": round(started, 3),
              "tapCommandObservedExitSeconds": injection_finished,
              "lastUnchangedSeconds": round(last_unchanged, 3),
              "firstVisibleChangeSeconds": None if changed is None else round(changed, 3),
              "samples": samples,
              "note": "End-to-end host input to visible screen; capture interval bounds the measurement, not guest dispatch time"}
    write_png(args.output / "before.png", before)
    write_png(args.output / "after.png", after)
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
