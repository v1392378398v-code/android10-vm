#!/usr/bin/env python3
"""Require a real guest camera, live preview callbacks and a JPEG capture."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--id", type=int, default=0)
    args = parser.parse_args()
    report = {"passed": False, "cameraId": args.id, "captureRequested": not args.list}
    main_class = "CameraQueryCheck" if args.list else "GuestCameraCheck"
    command = [sys.executable, str(ROOT / "tools/apk-guest-command.py"), "--package", "io.a10vm.miui",
               "--uid", "1000", "--main", "io.a10vm.guest." + main_class]
    if not args.list:
        command.append(str(args.id))
    try:
        result = subprocess.run(command, env=ENV, capture_output=True, text=True, timeout=45)
        markers = dict(re.findall(r"(?m)^(camera_\w+)=(.*)$", result.stdout))
        report["markers"] = markers
        count = int(markers.get("camera_count", markers.get("camera_query_count", "0")))
        assert count > 0, "Guest camera enumeration is empty"
        assert result.returncode == 0, "Guest camera check failed: " + "\n".join(
            line for line in result.stdout.splitlines() if "AssertionError" in line or "Caused by:" in line)
        if not args.list:
            assert markers.get("camera_preview_frames") == "3", "Guest preview has no frames"
            assert markers.get("camera_surface_frames") == "3", "Guest preview surface has no frames"
            assert markers.get("camera_capture_ready") == "1", "Guest JPEG capture failed"
        report["passed"] = True
    except (AssertionError, subprocess.SubprocessError, ValueError) as error:
        report["error"] = str(error)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
