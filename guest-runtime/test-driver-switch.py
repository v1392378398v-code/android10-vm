#!/usr/bin/env python3
"""Keep pending Binder replies while the same thread alternates AIDL and HIDL."""
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

OUT = ROOT / "artifacts/container/framework"
SOURCE = ROOT / "artifacts/container/runtime"


def main():
    assert os.getuid() >= 10000
    children, handles = [], []
    report = {"passed": False, "uid": os.getuid(), "rootRequired": False}
    with tempfile.TemporaryDirectory(prefix="ds-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary, {
            "binder-probe": SOURCE / "bin/binder-probe",
            "binder-broker": SOURCE / "bin/binder-broker",
            "liba10binder.so": SOURCE / "lib/liba10binder.so",
        })
        try:
            for name in ("binder", "hwbinder"):
                log = OUT / ("driver-switch-" + name + ".log")
                handle = log.open("w", encoding="utf-8")
                handles.append(handle)
                child = subprocess.Popen([runtime.native("ld-android.so"), runtime.native("binder-broker"),
                    runtime.directory / (name + ".sock")], env=runtime.registry_environment(),
                    stdout=handle, stderr=subprocess.STDOUT)
                children.append(child)
                wait_marker(child, log, "binder_broker_ready=1", 2)
            environment = dict(runtime.registry_environment(),
                               A10VM_HWBINDER_PATH=str(runtime.directory / "hwbinder.sock"))
            check = subprocess.run([runtime.native("ld-android.so"), runtime.native("binder-probe"),
                                    "driver-switch", runtime.directory / "binder.sock"],
                                   env=environment, capture_output=True, text=True, timeout=3)
            report["output"] = check.stdout + check.stderr
            assert check.returncode == 0 and "binder_driver_switch_complete=1\n" in check.stdout
            report.update(passed=True, rounds=64, queuedReplies=128)
            check = subprocess.run([runtime.native("ld-android.so"), runtime.native("binder-probe"),
                                    "driver-polling", runtime.directory / "binder.sock"],
                                   env=environment, capture_output=True, text=True, timeout=3)
            report["pollingOutput"] = check.stdout + check.stderr
            assert check.returncode == 0 and "binder_driver_polling_complete=1\n" in check.stdout
            report["pollingPassed"] = True
            check = subprocess.run([runtime.native("ld-android.so"), runtime.native("binder-probe"),
                                    "driver-fork-close", runtime.directory / "binder.sock"],
                                   env=environment, capture_output=True, text=True, timeout=3)
            report["forkCloseOutput"] = check.stdout + check.stderr
            assert check.returncode == 0 and "binder_driver_fork_close_complete=1\n" in check.stdout
            report["forkClosePassed"] = True
        except Exception as error:
            report["passed"] = False
            report["error"] = str(error)
        finally:
            stop_children(children, handles)
    (OUT / "driver-switch-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
