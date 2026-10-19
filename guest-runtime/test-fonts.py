#!/usr/bin/env python3
"""Exercise first Paint metrics through the real guest application bootstrap."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import stop_children, wait_marker

OUT = ROOT / "artifacts/container/desktop"


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    report = {"passed": False, "uid": os.getuid(), "rootRequired": False}
    with tempfile.TemporaryDirectory(prefix="fonts-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)
        children, handles = [], []
        command = [runtime.native("ld-android.so"), runtime.native("app_process64"),
                   "-Xnoimage-dex2oat", "/system/bin", "io.a10vm.guest.FontCheck"]
        try:
            log = OUT / "fonts-broker.log"
            handle = log.open("w", encoding="utf-8")
            handles.append(handle)
            broker = subprocess.Popen([str(runtime.native("ld-android.so")), str(runtime.native("binder-broker")),
                                       str(runtime.directory / "binder.sock")], env=runtime.registry_environment(),
                                      stdout=handle, stderr=subprocess.STDOUT)
            children.append(broker)
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            result = subprocess.run(list(map(str, command)), env=runtime.framework_environment(),
                                    capture_output=True, text=True, timeout=10)
            text = result.stdout + result.stderr
            (OUT / "fonts-check.log").write_text(text, encoding="utf-8")
            report.update(exitCode=result.returncode, log=text[-2500:])
            assert result.returncode == 0 and "guest_fonts_ready=1\n" in text, text[-1000:]
            report["passed"] = True
        except Exception as error:
            report["error"] = str(error)
        finally:
            stop_children(children, handles)
    (OUT / "fonts-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
