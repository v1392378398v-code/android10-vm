#!/usr/bin/env python3
"""Exercise the ROM credential SDK and fdpp with separate ordinary-UID processes."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children


def main():
    assert os.getuid() >= 10000
    prepared = ROOT / "guest-runtime/build/rom-prepared/miui12"
    out = ROOT / "artifacts/performance"
    report = {"passed": False, "ordinaryUid": os.getuid(), "temporaryRuntimeRemoved": False}
    children, handles = [], []
    with tempfile.TemporaryDirectory(prefix="credential-", dir=out) as temporary:
        runtime = RuntimeInstance(Path(temporary) / "runtime", prepared=prepared)
        shutil.copyfile(ROOT / "artifacts/container/framework/dex/classes.dex", runtime.directory / "framework-check.dex")

        def start(role, command, environment):
            path = out / ("credential-" + role + ".txt")
            handle = path.open("w")
            child = subprocess.Popen(list(map(str, command)), env=environment, stdout=handle, stderr=subprocess.STDOUT)
            children.append(child)
            handles.append(handle)
            return child, path

        def command(mode):
            return [runtime.native("ld-android.so"), runtime.native("app_process64"), "-Xnoimage-dex2oat",
                    "/system/bin", "io.a10vm.guest.GuestCredentialCheck", mode]

        try:
            environment = runtime.framework_environment()
            broker, path = start("broker", [runtime.native("ld-android.so"), runtime.native("binder-broker"),
                                runtime.directory / "binder.sock"], runtime.registry_environment())
            wait_marker(broker, path, "binder_broker_ready=1", 3)
            manager, path = start("manager", [runtime.native("ld-android.so"), runtime.native("servicemanager")],
                    dict(environment, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" + environment["LD_PRELOAD"]))
            wait_marker(manager, path, "binder_context_ready=1", 3)
            baseline, path = start("before", command("client"), environment)
            try:
                baseline.wait(timeout=3)
                raise AssertionError("Missing credential service did not reproduce the SDK wait")
            except subprocess.TimeoutExpired:
                baseline.kill()
                baseline.wait(timeout=3)
                report["missingServiceReproduced"] = True
            server, path = start("server", command("server"), environment)
            wait_marker(server, path, "credential_server_ready=1", 10)
            client, path = start("after", command("client"), environment)
            assert client.wait(timeout=10) == 0, path.read_text()[-1800:]
            text = path.read_text()
            report["credentialChecks"] = dict(re.findall(r"^(credential_\w+)=(.*)$", text, re.M))
            assert report["credentialChecks"].get("credential_existing_service_preserved") == "1"
            fdpp, path = start("fdpp", [runtime.native("ld-android.so"), runtime.native("rom/system/bin/fdpp"), "daemon"],
                    dict(environment, A10VM_GUEST_UID="0", A10VM_GUEST_GID="1000",
                         LD_PRELOAD=str(runtime.native("liba10vm-rom-service-identity.so")) + ":" + environment["LD_PRELOAD"]))
            probe, path = start("fdpp-client", command("fdpp"),
                                dict(environment, A10VM_GUEST_UID="0", A10VM_GUEST_GID="1000"))
            assert probe.wait(timeout=10) == 0, path.read_text()[-1800:]
            assert "fdpp_registered=1" in path.read_text()
            report["fdppRegistered"] = True
            report["fdppProcessAlive"] = fdpp.poll() is None
            assert report["fdppProcessAlive"]
            status = (Path("/proc") / str(fdpp.pid) / "status").read_text()
            report["fdppKernelUid"] = int(re.search(r"^Uid:\s+(\d+)", status, re.M).group(1))
            report["fdppCapEff"] = re.search(r"^CapEff:\s+(\w+)", status, re.M).group(1)
            assert report["fdppKernelUid"] == os.getuid() and int(report["fdppCapEff"], 16) == 0
            report["passed"] = True
        except Exception as failure:
            report["error"] = str(failure)
        finally:
            stop_children(children, handles)
            for handle in handles:
                Path(handle.name).unlink()
    report["temporaryRuntimeRemoved"] = not Path(temporary).exists()
    (out / "credential-capabilities.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
