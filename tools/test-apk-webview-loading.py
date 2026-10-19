#!/usr/bin/env python3
"""Verify HTTPS documents, visibility and process survival in the installed guest WebView."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
PACKAGE = "org.chromium.webview_shell"
SERIAL = None
EXPRESSION = """JSON.stringify({
  url: location.href, title: document.title, ready: document.readyState,
  visible: document.visibilityState,
  htmlBytes: document.documentElement.outerHTML.length,
  textLength: document.body ? document.body.innerText.length : 0,
  navigation: performance.getEntriesByType('navigation').map(e => ({
    status: e.responseStatus, bodyBytes: e.decodedBodySize})),
  images: Array.from(document.images).filter(e => e.naturalWidth > 0).length,
  failedImages: Array.from(document.images).filter(e => e.complete && !e.naturalWidth).length,
  errorPage: !!document.querySelector('#main-frame-error')
})"""


def device(command):
    argv = ["adb", "-s", SERIAL, "exec-out", command] if SERIAL else ["su", "-c", command]
    return subprocess.check_output(argv, env=ENV, timeout=10).decode(errors="replace")


def remote_metrics(name):
    if not SERIAL:
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), "--socket", name])
        return json.loads(device(command))
    port = subprocess.check_output(["adb", "-s", SERIAL, "forward", "tcp:0", "localabstract:" + name],
                                   env=ENV, timeout=10).decode().strip()
    try:
        return metrics("tcp:" + port)
    finally:
        subprocess.run(["adb", "-s", SERIAL, "forward", "--remove", "tcp:" + port],
                       env=ENV, check=True, timeout=10)


def metrics(name):
    cdp = runpy.run_path(str(ROOT / "tools/inspect-webview-viewport.py"))
    pages = []
    for target in cdp["targets"](name):
        if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
            continue
        result = cdp["call"](name, urlsplit(target["webSocketDebuggerUrl"]).path, "Runtime.evaluate",
                             {"expression": EXPRESSION, "returnByValue": True, "timeout": 2000})
        page = json.loads(result["result"]["value"])
        page["view"] = json.loads(target.get("description") or "{}")
        pages.append(page)
    return {"pages": pages}


def guest(out, label, *args):
    remote = ["--serial", SERIAL] if SERIAL else []
    result = subprocess.run([sys.executable, str(ROOT / "tools/apk-guest-command.py"), *remote, *args],
                            env=ENV, capture_output=True, text=True, timeout=30)
    (out / (label + ".log")).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("Guest command failed: " + label)


def main():
    global SERIAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="Use this ADB device without root automation")
    parser.add_argument("--socket", help=argparse.SUPPRESS)
    parser.add_argument("--label", default="webview-loading")
    parser.add_argument("--url", action="append")
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    SERIAL = args.serial
    if args.socket:
        print(json.dumps(metrics(args.socket)))
        return 0
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label) or args.rounds < 1:
        raise ValueError("Invalid label or rounds")
    out = ROOT / "artifacts/webview-viewport" / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "package": PACKAGE, "pages": []}
    report.update(rootRequiredByGuest=False, rootUsedForAutomation=not bool(SERIAL))
    if SERIAL:
        report["adbSerial"] = SERIAL
    urls = args.url or ["https://weixin.qq.com/", "https://m.v.qq.com/", "https://m.bilibili.com/"]
    try:
        for index, url in enumerate(urls * args.rounds):
            if urlsplit(url).scheme != "https":
                raise ValueError("Expected HTTPS URL")
            label = str(index + 1)
            guest(out, label + "-stop", "activity", "force-stop", PACKAGE)
            guest(out, label + "-launch", "activity", "start", "-W", "-a", "android.intent.action.VIEW",
                  "-d", url, "-n", PACKAGE + "/.WebViewBrowserActivity")
            server = device("run-as io.a10vm cat files/guest-runtime/framework-server.log")
            pid = re.findall(r"desktop_application_launch=(\d+):" + re.escape(PACKAGE) + r"\b", server)[-1]
            socket_name = "webview_devtools_remote_" + pid
            deadline = time.monotonic() + 20
            page = {}
            while time.monotonic() < deadline:
                sockets = device("cat /proc/net/unix")
                if "@" + socket_name in sockets:
                    for candidate in remote_metrics(socket_name)["pages"]:
                        if candidate["url"].split("#")[0].rstrip("/") == url.rstrip("/"):
                            page = candidate
                if page.get("ready") == "complete" and not page.get("errorPage", True):
                    break
                time.sleep(.25)
            checks = {"loaded": page.get("ready") == "complete" and not page.get("errorPage", True),
                      "httpBody": any(e.get("status") == 200 and e.get("bodyBytes", 0) > 1000
                                      for e in page.get("navigation", [])),
                      "document": page.get("htmlBytes", 0) > 1000 and page.get("textLength", 0) > 20,
                      "visible": page.get("visible") == "visible" and page.get("view", {}).get("visible")}
            status = device("run-as io.a10vm cat /proc/" + pid + "/status")
            checks["processAlive"] = re.search(r"^State:\s*[ZXTt]", status, re.M) is None
            page.update(requestedUrl=url, checks=checks)
            report["pages"].append(page)
            target = "/data/local/tmp/webview-loading-" + label + ".png"
            guest(out, label + "-capture", "--native", "image/system/bin/screencap", "-p", target)
            source = "files/guest-runtime/rootfs" + target
            command = "run-as io.a10vm cat " + shlex.quote(source)
            capture = ["adb", "-s", SERIAL, "exec-out", command] if SERIAL else ["su", "-c", command]
            screenshot = subprocess.check_output(capture, env=ENV, timeout=10)
            (out / (label + ".png")).write_bytes(screenshot)
            if not all(checks.values()):
                raise AssertionError("Page loading checks failed: " + url)
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
