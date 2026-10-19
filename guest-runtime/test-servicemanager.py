#!/usr/bin/env python3
"""Exercise the stock Android 10 service manager through the packaged Binder ABI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children

OUT = ROOT / "artifacts/container/framework"


def main():
    (OUT / "stock-servicemanager-report.json").unlink(missing_ok=True)
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    nonce = uuid.uuid4().hex
    children, handles = [], []
    report = {"passed": False, "rootRequired": False, "uid": os.getuid(),
              "stockServiceManager": True, "desktopVerified": False}
    with tempfile.TemporaryDirectory(prefix="sm-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)
        environment = runtime.framework_environment()

        def start(role, command, env):
            log = OUT / ("stock-" + role + ".log")
            handle = log.open("w", encoding="utf-8")
            child = subprocess.Popen(list(map(str, command)), env=env, stdout=handle,
                                     stderr=subprocess.STDOUT)
            children.append(child)
            handles.append(handle)
            return child, log

        started = time.monotonic()
        try:
            broker, log = start("broker", [runtime.native("ld-android.so"),
                runtime.native("binder-broker"), runtime.directory / "binder.sock"],
                runtime.registry_environment())
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            policy = dict(environment, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" +
                          environment["LD_PRELOAD"])
            manager, manager_log = start("manager", [runtime.native("ld-android.so"),
                runtime.native("servicemanager")], policy)
            server, log = start("server", runtime.framework_command("Server", nonce), environment)
            wait_marker(server, log, "framework_service_registered=" + nonce, 5)
            client, log = start("client", runtime.framework_command("Client", nonce), environment)
            text = wait_marker(client, log, "framework_complete=1", 5)
            assert client.wait(timeout=2) == 0 and "framework_transactions=64" in text, text
            assert manager.poll() is None and server.poll() is None, manager_log.read_text()
            report.update(passed=True, transactions=64,
                          elapsedMs=round((time.monotonic() - started) * 1000, 2))
        except Exception as error:
            report["error"] = str(error)[-1600:]
        finally:
            stop_children(children, handles)
            report["processCleanupPassed"] = all(child.poll() is not None for child in children)
            (OUT / "stock-servicemanager-report.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
