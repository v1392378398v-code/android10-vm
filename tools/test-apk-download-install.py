#!/usr/bin/env python3
"""Download an independent APK through the guest provider and install its actual bytes."""
import argparse
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent.parent
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", choices=("io.a10vm", "io.a10vm.miui"), default="io.a10vm.miui")
    parser.add_argument("--label", default="current")
    parser.add_argument("--apk", type=Path, default=ROOT / "artifacts/clear-data/fixture/fixture.apk")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("Invalid evidence label")
    apk = args.apk.resolve()
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    out = ROOT / "artifacts/download-install" / args.label
    out.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(apk.parent)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    report = {"passed": False, "package": args.package, "apkBytes": apk.stat().st_size,
              "sha256": digest, "rootRequiredByGuest": False}
    command = [sys.executable, str(ROOT / "tools/apk-guest-command.py"), "--package", args.package,
               "--uid", "1000", "--main", "io.a10vm.guest.GuestDownloadCheck",
               f"http://127.0.0.1:{server.server_port}/{apk.name}",
               "/storage/emulated/0/Download/a10vm-download-install-check.apk", digest]
    try:
        result = subprocess.run(command, env=ENV, capture_output=True, text=True, timeout=90)
        text = result.stdout + result.stderr
        (out / "download-install.log").write_text(text, encoding="utf-8")
        match = re.search(r"^guest_download_install=(.+)$", text, re.M)
        if not match:
            failure = re.search(r"(?:AssertionError|Exception): (.+)", text)
            raise AssertionError("Download/install failed: " + (failure.group(1) if failure else text[-1800:]))
        report["download"] = json.loads(match.group(1))
        assert result.returncode == 0 and report["download"]["installed"], "Package install failed"
        assert report["download"]["sha256"] == digest, "APK hash differs"
        report["passed"] = True
    except Exception as failure:
        report["error"] = str(failure)
    finally:
        server.shutdown()
        server.server_close()
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
