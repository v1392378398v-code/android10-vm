#!/usr/bin/env python3
"""Check guest Java writes, cross-process reads and real property errors."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children, start_properties

OUT = ROOT / "artifacts/container/framework"


def main():
    (OUT / "property-service-report.json").unlink(missing_ok=True)
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    children, handles = [], []
    nonce = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="prop-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)

        def start(role, command, environment):
            log = OUT / ("property-" + role + ".log")
            handle = log.open("w", encoding="utf-8")
            child = subprocess.Popen(list(map(str, command)), env=environment, stdout=handle,
                                     stderr=subprocess.STDOUT)
            children.append(child)
            handles.append(handle)
            return child, log

        try:
            environment = start_properties(runtime, start)
            broker, log = start("broker", [runtime.native("ld-android.so"), runtime.native("binder-broker"),
                                runtime.directory / "binder.sock"], runtime.registry_environment())
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            for role in ("writer", "reader", "missing"):
                env = dict(environment)
                if role == "missing":
                    env["A10VM_PROPERTY_SOCKET"] += ".missing"
                command = [runtime.native("ld-android.so"), runtime.native("app_process64"),
                           "-Xnoimage-dex2oat", "/system/bin",
                           "io.a10vm.guest.PropertyCheck", role, nonce]
                child, log = start(role, command, env)
                marker = "property_missing_rejected=1" if role == "missing" else "property_" + role + "_ready=1"
                text = wait_marker(child, log, marker, 5)
                assert child.wait(timeout=2) == 0, text
                if role == "writer":
                    assert "property_readonly_rejected=1\n" in text
        finally:
            stop_children(children, handles)
    report = {"passed": True, "uid": os.getuid(), "rootRequired": False,
              "crossProcessRead": True, "readOnlyRejected": True, "missingServiceRejected": True,
              "processCleanupPassed": all(child.poll() is not None for child in children)}
    (OUT / "property-service-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
