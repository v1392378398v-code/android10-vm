#!/usr/bin/env python3
"""Run stock Android 10 app_process and Java Binder under an ordinary app UID."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid
from test_framework_support import wait_marker, stop_children, start_properties, start_hardware

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/container/framework"


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    report_path = OUT / "local-report.json"
    report_path.unlink(missing_ok=True)
    nonce = uuid.uuid4().hex
    children, handles = [], []
    identities = {}
    report = {"passed": False, "rootRequired": False, "uid": os.getuid(),
              "stockFramework": True, "stockServiceManager": True,
              "desktopVerified": False, "apkRunVerified": False}
    with tempfile.TemporaryDirectory(prefix="fw-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)
        socket = runtime.directory / "binder.sock"
        env = runtime.framework_environment()
        registry_env = runtime.registry_environment()

        def start(label, command, environment):
            log = OUT / ("local-" + label + ".log")
            handle = log.open("w", encoding="utf-8")
            child = subprocess.Popen(list(map(str, command)), env=environment, stdout=handle,
                                     stderr=subprocess.STDOUT)
            children.append(child)
            handles.append(handle)
            return child, log

        def framework(role):
            return runtime.framework_command(role, nonce)

        def identity(child):
            status = (Path("/proc") / str(child.pid) / "status").read_text()
            uid = re.search(r"^Uid:\s+(.*)$", status, re.M).group(1).split()
            capabilities = re.search(r"^CapEff:\s+(\w+)$", status, re.M).group(1)
            domain = (Path("/proc") / str(child.pid) / "attr/current").read_text().rstrip("\0\n")
            assert uid == [str(os.getuid())] * 4 and capabilities == "0000000000000000", status
            assert re.fullmatch(r"u:r:untrusted_app(?:_\d+)?:s0(?::.*)?", domain), domain
            return {"pid": child.pid, "uid": int(uid[0]), "capEff": capabilities, "selinux": domain}

        started = time.monotonic()
        try:
            env = start_properties(runtime, start)
            registry_env["A10VM_PROPERTIES"] = env["A10VM_PROPERTIES"]
            broker, log = start("broker", [runtime.native("ld-android.so"), runtime.native("binder-broker"), socket], registry_env)
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            identities["broker"] = identity(broker)
            manager_env = dict(env, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" + env["LD_PRELOAD"])
            manager, log = start("manager", [runtime.native("ld-android.so"), runtime.native("servicemanager")], manager_env)
            wait_marker(manager, log, "binder_context_ready=1", 3)
            identities["manager"] = identity(manager)
            hardware = start_hardware(runtime, start, env)
            identities["hwmanager"] = identity(hardware)
            server, log = start("server", framework("Server"), env)
            wait_marker(server, log, "framework_service_registered=" + nonce, 10)
            identities["server"] = identity(server)
            allowed = {str(runtime.native(name)) for name in runtime.names}
            required = {str(runtime.native(name)) for name in ("ld-android.so", "app_process64", "libart.so",
                        "libc.so", "libandroid_runtime.so", "libbinder.so", "liba10vm-binder-devices.so")}
            for line in (Path("/proc") / str(server.pid) / "maps").read_text().splitlines():
                fields = line.split(maxsplit=5)
                if len(fields) == 6 and "x" in fields[1] and fields[5].startswith("/"):
                    assert fields[5] in allowed, line
            client, client_log = start("client", framework("Client"), env)
            text = wait_marker(client, client_log, "framework_complete=1", 10)
            assert client.wait(timeout=3) == 0, text
            values = dict(re.findall(r"^(framework_\w+)=(.*)$", text, re.M))
            assert values["framework_sdk"] == "29" and values["framework_nonce"] == nonce, values
            assert values["framework_server_pid"] == str(server.pid) and values["framework_client_pid"] == str(client.pid), values
            assert values["framework_uid"] == str(os.getuid()) and values["framework_transactions"] == "64", values
            assert values["framework_euid"] == str(os.getuid()) and values["framework_cap_eff"] == "0000000000000000", values
            assert re.fullmatch(r"u:r:untrusted_app(?:_\d+)?:s0(?::.*)?", values["framework_selinux"])
            mappings = set(re.findall(r"^FRAMEWORK_MAP\t(.*)$", text, re.M))
            assert required <= mappings <= allowed, mappings
            report.update(transactions=64, elapsedMs=round((time.monotonic() - started) * 1000, 2),
                          identities=identities, client=values, executableMappings=len(mappings))
        finally:
            stop_children(children, handles)
        report["processCleanupPassed"] = all(not (Path("/proc") / str(child.pid)).exists() for child in children)
        assert report["processCleanupPassed"]
        missing = dict(env, A10VM_BINDER_PATH=str(runtime.directory / "missing.sock"))
        negative = subprocess.run(framework("Client"), env=missing, capture_output=True, timeout=15)
        (OUT / "local-missing-binder.log").write_bytes(negative.stdout + negative.stderr)
        assert negative.returncode != 0
        report.update(passed=True, missingBinderRejected=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
