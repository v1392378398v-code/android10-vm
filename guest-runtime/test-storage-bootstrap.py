#!/usr/bin/env python3
"""Check first-boot user directories before any volume callback or system service."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children


def main():
    assert os.getuid() >= 10000, "Run using an ordinary app UID"
    out = ROOT / "artifacts/container/framework/storage-bootstrap"
    out.mkdir(parents=True, exist_ok=True)
    children, handles = [], []
    with tempfile.TemporaryDirectory(prefix="storage-", dir=ROOT / "artifacts") as temporary:
        runtime = RuntimeInstance(temporary)
        shutil.copyfile(ROOT / "artifacts/container/framework/dex/classes.dex",
                        runtime.directory / "framework-check.dex")

        def start(role, logical, environment, *arguments):
            log = out / (role + ".log")
            stream = log.open("w", encoding="utf-8")
            handles.append(stream)
            process = subprocess.Popen(list(map(str, [runtime.native("ld-android.so"), runtime.native(logical),
                                                      *arguments])), env=environment, stdout=stream, stderr=stream)
            children.append(process)
            return process, log

        try:
            broker, log = start("broker", "binder-broker", runtime.registry_environment(),
                                runtime.directory / "binder.sock")
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            environment = runtime.framework_environment()
            policy = dict(environment, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" +
                          environment["LD_PRELOAD"])
            manager, log = start("manager", "servicemanager", policy)
            wait_marker(manager, log, "binder_context_ready=1", 3)
            result = subprocess.run(list(map(str, [runtime.native("ld-android.so"), runtime.native("app_process64"),
                "-Xnoimage-dex2oat", "/system/bin", "io.a10vm.guest.GuestStorageCheck"])),
                env=environment, capture_output=True, text=True, timeout=10)
            text = result.stdout + result.stderr
            (out / "check.log").write_text(text, encoding="utf-8")
            assert result.returncode == 0 and all(marker + "=1\n" in text for marker in (
                "guest_storage_ready_before_services", "guest_storage_database_opened",
                "guest_storage_existing_data_preserved")), text[-2000:]
        finally:
            stop_children(children, handles)
    print("Guest first-boot storage and SQLite: passed using ordinary UID " + str(os.getuid()))


if __name__ == "__main__":
    main()
