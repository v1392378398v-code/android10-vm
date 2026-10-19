#!/usr/bin/env python3
"""Run production native window/input endpoints with the packaged Android 10 ELF set."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import subprocess
import tempfile
import time
from contextlib import nullcontext
from native_display_stall import GlStall
from guest_runtime_fixture import RuntimeInstance

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "app/build/native-display/jniLibs/arm64-v8a"
OUT = ROOT / "artifacts/container/graphics"


def verify_guest(text, runtime):
    expected = {str(runtime.native(name)) for name in (
        "ld-android.so", "libc.so", "libdl.so", "libm.so", "libc++.so", "libunwind.so",
        "libnetd_client.so", "liba10vm-p1-client.so",
    )}
    stages = text.split("identity_stage=exit\n")
    assert len(stages) == 2, "Missing exit identity"
    for stage in stages:
        mappings = set()
        for line in stage.splitlines():
            if line.startswith("MAP\t"):
                fields = line[4:].split(maxsplit=5)
                if len(fields) == 6 and "x" in fields[1] and fields[5].startswith("/"):
                    mappings.add(fields[5])
        assert mappings == expected, {"wrongMappings": sorted(mappings)}
        for key in ("uid", "euid"):
            assert re.findall(r"^" + key + r"=(\d+)$", stage, re.M) == [str(os.getuid())]
        assert re.findall(r"^nonce=(.*)$", stage, re.M) == ["native-window-local"]
        assert re.findall(r"^cap_eff=(.*)$", stage, re.M) == ["0000000000000000"]
        assert re.findall(r"^visible_sdk=(.*)$", stage, re.M) == ["29"]
        contexts = re.findall(r"^selinux=(.*)$", stage, re.M)
        assert len(contexts) == 1 and re.fullmatch(r"u:r:untrusted_app(?:_\d+)?:s0(?::.*)?", contexts[0]), contexts
    return sorted(expected)


def run_window(mode, report):
    stem = "native-window" + ("-" + mode.removeprefix("--") if mode else "")
    host_log_path, guest_log_path = OUT / (stem + "-host.log"), OUT / (stem + "-guest.log")
    report.update(hostLog=str(host_log_path.relative_to(ROOT)), guestLog=str(guest_log_path.relative_to(ROOT)))
    with tempfile.TemporaryDirectory(prefix="native-window-", dir=os.environ.get("TMPDIR")) as temporary:
        directory = Path(temporary)
        runtime = RuntimeInstance(directory / "guest-runtime", {"liba10vm-p1-client.so": LIB / "liba10vm-p1-client.so"})
        environment = {"PATH": "/system/bin", "TMPDIR": temporary}
        host = subprocess.Popen([str(OUT / "bin/window-host"), temporary] + ([mode] if mode else []),
                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        guest = None
        host_log = ""
        try:
            assert select.select([host.stdout], [], [], 10)[0], "Native host readiness timeout"
            ready = host.stdout.readline()
            host_log = ready
            assert "HOST_WINDOW_READY" in ready, ready
            report["hostGpu"] = ready.strip()
            fixture = GlStall(directory) if mode == "--stall-input" else nullcontext()
            with fixture as proxy, guest_log_path.open("w", encoding="utf-8") as output:
                guest = subprocess.Popen([str(runtime.native("ld-android.so")), str(runtime.native("liba10vm-p1-client.so")),
                                          "--window", proxy.path if proxy else str(directory / "gles.sock"),
                                          str(directory / "input.sock"), "native-window-local"],
                                          env=dict(runtime.environment, TMPDIR=temporary),
                                         stdout=output, stderr=subprocess.STDOUT)
                if proxy:
                    deadline = time.monotonic() + 8
                    while not (directory / "stall.input-sent").exists():
                        assert time.monotonic() < deadline and host.poll() is None, "Input burst did not start"
                        assert proxy.error is None, proxy.error
                        time.sleep(.005)
                    start = time.monotonic()
                    try:
                        while "CLIENT_TOUCH_APPLIED sequence=205 active=0" not in guest_log_path.read_text():
                            assert time.monotonic() - start < 1, "Input waited for the paused GL stream"
                            assert guest.poll() is None and proxy.error is None, proxy.error
                            time.sleep(.005)
                        report["inputDeliveredDuringGlPause"] = True
                    finally:
                        (directory / "stall.release").touch()
                host_log += host.communicate(timeout=12)[0]
                guest.wait(timeout=5)
            guest_log = guest_log_path.read_text()
            report.update(hostExit=host.returncode, guestExit=guest.returncode)
            assert host.returncode == 0 and "HOST_WINDOW_OK" in host_log, "Window host failed; see host log"
            assert guest.returncode == 0, "Window guest failed; see guest log"
            stop = re.findall(r"CLIENT_WINDOW_STOP_RECEIVED sequence=(\d+) applied=(\d+)", guest_log)
            assert stop == [("205", "205")], {"stop": stop, "expectedEvents": 205}
            assert "CLIENT_WINDOW_DONE frames=" in guest_log, "Missing guest completion"
            report["guestMappings"] = verify_guest(guest_log, runtime)
            frame_data = re.search(r"HOST_WINDOW_OK frames=(\d+) input=(\d+) echo=(\d+) swaps=(\d+)", host_log)
            assert frame_data, "Missing host completion"
            report["frames"], report["inputEvents"], report["echoSequence"], swaps = map(int, frame_data.groups())
            assert report["inputEvents"] == 205 and swaps == 0
            if mode != "--stop-pending":
                assert report["frames"] >= 50 and report["echoSequence"] == 205
        finally:
            for child in (guest, host):
                if child is not None and child.poll() is None:
                    child.kill()
                    if child is host:
                        host_log += child.communicate(timeout=3)[0]
                    else:
                        child.wait(timeout=3)
            host_log_path.write_text(host_log, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stop-pending", action="store_true")
    group.add_argument("--stall-input", action="store_true")
    args = parser.parse_args()
    mode = "--stop-pending" if args.stop_pending else "--stall-input" if args.stall_input else ""
    stem = "native-window" + ("-" + mode.removeprefix("--") if mode else "")
    report = {"stage": "rootless native display integration", "mode": mode or "normal", "passed": False,
              "uid": os.getuid(), "apkRunVerified": False, "surfaceVerified": False, "desktopVerified": False}
    try:
        assert os.getuid() >= 10000, "Use the ordinary Termux UID"
        manifest = json.loads((ROOT / "app/build/native-display/assets/native-display-inputs.json").read_text())
        for entry in manifest["files"]:
            path = (ROOT / "native-display/build/prepared/jniLibs/arm64-v8a" / entry["name"]
                    if entry["name"] == "liba10vm-p1-window.so" else LIB / entry["name"])
            assert path.stat().st_size == entry["bytes"] and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        report["inputs"] = manifest
        run_window(mode, report)
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    (OUT / (stem + "-report.json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("inputs", "guestMappings")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
