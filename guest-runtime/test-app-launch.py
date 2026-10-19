#!/usr/bin/env python3
"""Exercise the real exec-based guest main used by WebView relro helpers."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker

OUT = ROOT / "artifacts/container/framework"


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="launch-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)
        shutil.copyfile(OUT / "dex/classes.dex", runtime.directory / "framework-check.dex")
        environment = runtime.framework_environment()
        environment.update(A10VM_APP_PROCESS=str(runtime.native("app_process64")),
                           A10VM_LIBRARY_PATH=str(runtime.libraries))
        command = [runtime.native("ld-android.so"), runtime.native("app_process64"),
                   "-Xnoimage-dex2oat", "-Djava.library.path=" + str(runtime.libraries),
                   "/system/bin", "io.a10vm.guest.ProcessLaunchCheck"]
        broker_log = OUT / "app-launch-broker.log"
        with broker_log.open("w", encoding="utf-8") as stream:
            broker = subprocess.Popen([str(runtime.native("ld-android.so")),
                str(runtime.native("binder-broker")), str(runtime.directory / "binder.sock")],
                env=runtime.registry_environment(), stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_marker(broker, broker_log, "binder_broker_ready=1", 3)
                result = subprocess.run(list(map(str, command)), env=environment,
                                        capture_output=True, text=True, timeout=30)
                log = result.stdout + result.stderr
                (OUT / "app-launch.log").write_text(log, encoding="utf-8")
                for child_log in runtime.directory.glob("application-*.log"):
                    (OUT / ("app-launch-" + child_log.name)).write_bytes(child_log.read_bytes())
            finally:
                broker.terminate()
                broker.wait(timeout=3)
    child_zygote = "child_zygote_listener_complete=1\n" in log
    isolated = "isolated_code_paths_launch_complete=1\n" in log
    report = {"passed": result.returncode == 0 and "process_launch_complete=1\n" in log and child_zygote and isolated,
              "childZygoteListenerVerified": child_zygote,
              "isolatedCodePathsVerified": isolated,
              "uid": os.getuid(), "rootRequired": False, "exitCode": result.returncode,
              "elapsedSeconds": round(time.monotonic() - began, 3)}
    (OUT / "app-launch-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        print(log[-1600:])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
