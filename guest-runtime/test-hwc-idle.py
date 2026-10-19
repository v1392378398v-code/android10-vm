#!/usr/bin/env python3
"""Exercise real HWC power, VSync wait and retained client targets under an ordinary UID."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children

OUT = ROOT / "artifacts/container/graphics/desktop"


def main():
    assert os.getuid() >= 10000
    stock = "--stock" in sys.argv
    report = {"passed": False, "uid": os.getuid(), "stock": stock}
    children, handles = [], []
    with tempfile.TemporaryDirectory(prefix="hwc-idle-", dir=ROOT / "artifacts") as temporary:
        libraries = {path.name: path for path in (OUT / "lib").glob("*.so")}
        if stock:
            libraries["hwcomposer.ranchu.so"] = OUT / "hwcomposer-v46.so"
        runtime = RuntimeInstance(temporary, dict(libraries,
            **{"desktop-hal-check": OUT / "bin/desktop-hal-check"}))
        environment = runtime.framework_environment()
        environment["A10VM_GPU_SOCKET"] = str(runtime.directory / "gpu.sock")
        try:
            host_log = OUT / ("hwc-idle-host-stock.log" if stock else "hwc-idle-host.log")
            handle = host_log.open("w")
            handles.append(handle)
            host = subprocess.Popen([str(OUT / "bin/desktop-gpu-host"), environment["A10VM_GPU_SOCKET"]],
                env={"PATH": "/system/bin"}, stdout=handle, stderr=subprocess.STDOUT)
            children.append(host)
            wait_marker(host, host_log, "desktop_gpu_ready=1", 3)
            result = subprocess.run([str(runtime.native("ld-android.so")), str(runtime.native("desktop-hal-check"))],
                env=environment, capture_output=True, text=True, timeout=8)
            text = result.stdout + result.stderr
            (OUT / ("hwc-idle-stock.log" if stock else "hwc-idle.log")).write_text(text)
            checks = "\n".join(row for row in text.splitlines() if row.startswith(("CHECK\t", "hwc_idle_switches=")))
            assert result.returncode == 0 and "desktop_hwc_idle_complete=1\n" in text, checks[-1500:] or text[-1500:]
            assert host.poll() is None
            frames = host_log.read_text()
            assert "desktop_gpu_frame=1 " in frames, "Fresh client target was not posted"
            assert "desktop_gpu_frame=120 " not in frames, "Retained client target was posted repeatedly"
            report.update(passed=True, disabledThreadBlocks=True, powerOffStopsVsync=True,
                          resumeStartsVsync=True, retainedTargetNotReposted=True, freshTargetAccepted=True,
                          waitingThreadClosed=True)
        except Exception as error:
            report["error"] = str(error)
        finally:
            stop_children(children, handles)
    (OUT / ("hwc-idle-stock-report.json" if stock else "hwc-idle-report.json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
