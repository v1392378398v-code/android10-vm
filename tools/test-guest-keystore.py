#!/usr/bin/env python3
"""Run stock software keymaster and keystore using a private ordinary-UID runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from guest_runtime_fixture import RuntimeInstance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "guest-runtime"))
from test_framework_support import start_properties, start_hardware, wait_marker


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    out = ROOT / "artifacts/clear-data/keystore"
    out.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "rootRequired": False, "uid": os.getuid()}
    children, handles = [], []
    with tempfile.TemporaryDirectory(prefix="key-", dir=ROOT / "artifacts") as temporary:
        runtime = RuntimeInstance(temporary)
        shutil.copyfile(ROOT / "artifacts/container/framework/dex/classes.dex", runtime.directory / "framework-check.dex")
        (runtime.rootfs / "data/misc/keystore").mkdir(parents=True, exist_ok=True)

        def start(role, command, environment):
            log = out / (role + ".log")
            stream = log.open("w", encoding="utf-8")
            handles.append(stream)
            child = subprocess.Popen(list(map(str, command)), env=environment, stdout=stream, stderr=subprocess.STDOUT)
            children.append(child)
            return child, log

        def native(logical, *args):
            return [runtime.native("ld-android.so"), runtime.native(logical), *args]

        def check(mode):
            result = subprocess.run(list(map(str, native("app_process64", "-Xnoimage-dex2oat",
                "-Djava.library.path=" + str(runtime.libraries), "/system/bin", "io.a10vm.guest.GuestKeyStoreCheck", mode))),
                env=dict(environment, A10VM_GUEST_UID="2000", A10VM_GUEST_GID="2000"),
                capture_output=True, text=True, timeout=25)
            log = result.stdout + result.stderr
            (out / (mode + ".log")).write_text(log, encoding="utf-8")
            assert result.returncode == 0 and "guest_keystore_complete=1\n" in log, log[-3500:]
            print("guest_keystore_" + mode + "=1", flush=True)

        try:
            environment = start_properties(runtime, start)
            environment.update(A10VM_GUEST_UID="1000", A10VM_GUEST_GID="1000")
            broker, log = start("broker", native("binder-broker", runtime.directory / "binder.sock"),
                                runtime.registry_environment())
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            policy = dict(environment, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" + environment["LD_PRELOAD"])
            manager, log = start("manager", native("servicemanager"), policy)
            wait_marker(manager, log, "binder_context_ready=1", 3)
            start_hardware(runtime, start, environment)
            master, log = start("keymaster", native("image/vendor/bin/hw/android.hardware.keymaster@3.0-service"),
                                dict(environment, A10VM_GUEST_UID="9999", A10VM_GUEST_GID="9999"))
            wait_marker(master, log, "Registration complete for android.hardware.keymaster@3.0::IKeymasterDevice/default.", 5)
            store, log = start("keystore", native("image/system/bin/keystore", "/data/misc/keystore"),
                               dict(environment, A10VM_GUEST_UID="1017", A10VM_GUEST_GID="1017"))
            wait_marker(store, log, "with interface name default and seclevel SOFTWARE", 5)
            check("create")
            store.terminate(); store.wait(timeout=3)
            store, log = start("keystore-restarted", native("image/system/bin/keystore", "/data/misc/keystore"),
                               dict(environment, A10VM_GUEST_UID="1017", A10VM_GUEST_GID="1017"))
            wait_marker(store, log, "with interface name default and seclevel SOFTWARE", 5)
            check("persisted")
            report.update(passed=True, aesGcm=True, rsaSignature=True, serviceRestartPersistence=True)
        except Exception as failure:
            report["error"] = str(failure)
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=3)
                    except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=3)
            for stream in handles: stream.close()
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
