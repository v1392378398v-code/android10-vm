#!/usr/bin/env python3
"""Exercise Android 10 HwBinder in separate processes over its private channel."""
import json
import os
import pathlib
import subprocess
import tempfile
import time

root = pathlib.Path(__file__).resolve().parents[2]
runtime = root / "artifacts/container/runtime"
output = runtime / "hwbinder"
linker = runtime / "bin/source-linker64"
program = runtime / "bin/hwbinder-probe"
inspector = runtime / "bin/binder-probe"
broker = runtime / "bin/binder-broker"
output.mkdir(parents=True, exist_ok=True)
report = output / "local-report.json"
report.unlink(missing_ok=True)
libraries = {
    "libc.so": "libc.so",
    "libdl.so": "libdl.so",
    "libm.so": "libm.so",
    "libc++.so": "libc++.so",
    "libunwind.so": "libunwind.so",
    "liblog.so": "liblog.so",
    "libbase.so": "libbase.so",
    "libcutils.so": "libcutils.so",
    "libutils.so": "libutils.so",
    "libbinderthreadstate.so": "libbinderthreadstate.so",
    "libbinder.so": "libbinder.so",
    "liba10binder.so": "liba10binder.so",
    "libhwbinder.so": "libhwbinder.so",
    "libhidlbase.so": "libhidlbase.so",
    "liba10hidl-values.so": "liba10hidl-values.so",
}
required = {
    line.strip() for line in (root / "container-probe/hwbinder/checks.txt").read_text().splitlines()
    if line.strip()
}


def wait_marker(child, log, marker, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = log.read_text(errors="replace")
        if marker in text:
            return text
        if child.poll() is not None:
            raise AssertionError((child.returncode, log.name, text[-6000:]))
        time.sleep(0.02)
    raise AssertionError(("timeout", log.name, log.read_text(errors="replace")[-6000:]))


with tempfile.TemporaryDirectory(prefix="a10hw-", dir=os.environ.get(
        "TMPDIR", "/data/data/com.termux/files/usr/tmp")) as temporary:
    directory = pathlib.Path(temporary)
    seed = directory / "properties"
    env = {"PATH": "/system/bin", "TMPDIR": str(directory)}
    seeded = subprocess.run([
        str(root / "artifacts/container/properties/bin/property-probe"), "run", str(seed),
        "hwbinder-seed", "/system/bin/linker64",
    ], env=env, capture_output=True, text=True, timeout=15)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    for alias, name in libraries.items():
        (directory / alias).symlink_to(runtime / "lib" / name)
    config = directory / "ld.config.txt"
    config.write_text(f"dir.probe = {program.parent}\n[probe]\nnamespace.default.isolated = true\n"
                      f"namespace.default.search.paths = {directory}\n"
                      f"namespace.default.permitted.paths = {runtime}\n", encoding="utf-8")
    env.update(A10VM_PROPERTIES=str(seed), A10VM_LD_CONFIG=str(config))
    socket = directory / "hwbinder.sock"
    children = []
    logs = []

    def start(label, binary, args, extra=None):
        log = output / f"local-{label}.log"
        handle = log.open("w", encoding="utf-8")
        child = subprocess.Popen([str(linker), str(binary), *map(str, args)],
                                 env=dict(env, **(extra or {})), stdout=handle,
                                 stderr=subprocess.STDOUT)
        children.append(child)
        logs.append(handle)
        return child, log

    def inspect():
        result = subprocess.run([str(linker), str(inspector), "inspect", str(socket)],
                                env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode == 0, result.stdout + result.stderr
        line = next(line for line in result.stdout.splitlines() if line.startswith("STATS\t"))
        values = list(map(int, line.split("\t")[1:]))
        assert len(values) == 28, values
        return values

    def wait_reclaimed(timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            stats = inspect()
            if all(value == 0 for value in stats[:8]) and stats[13] == 0 and stats[14] == 0:
                return stats
            time.sleep(0.02)
        raise AssertionError(("HwBinder resources remained", stats))

    try:
        daemon, daemon_log = start("broker", broker, [socket])
        wait_marker(daemon, daemon_log, "binder_broker_ready=1")
        registry, registry_log = start("registry", program, ["registry", socket])
        registry_text = wait_marker(registry, registry_log, "hwbinder_registry_ready=1")
        assert "CHECK\thwbinder_registry_context\t1\n" in registry_text, registry_text
        service, service_log = start("service", program, ["service", socket])
        service_text = wait_marker(service, service_log, "hwbinder_service_ready=1")
        assert "CHECK\thwbinder_service_registered\t1\n" in service_text, service_text
        caller, caller_log = start("client", program, ["client", socket], {
            "A10VM_HWBINDER_SERVICE_PID": next(
                line.split("=", 1)[1] for line in service_text.splitlines()
                if line.startswith("hwbinder_pid=")
            ),
        })
        client_text = wait_marker(caller, caller_log, "hwbinder_client_complete=", 15)
        assert "hwbinder_client_complete=1\n" in client_text, client_text
        check_rows = [line.split("\t") for line in client_text.splitlines()
                      if line.startswith("CHECK\t")]
        assert all(len(row) == 3 and row[0] == "CHECK" and row[2] == "1"
                   for row in check_rows), check_rows
        checks = [row[1] for row in check_rows]
        assert len(checks) == len(set(checks)) and set(checks) == required, checks
        assert caller.wait(timeout=5) == 0, caller_log.read_text(errors="replace")[-6000:]

        service.terminate()
        assert service.wait(timeout=3) == -15, service_log.read_text(errors="replace")[-3000:]
        registry.terminate()
        assert registry.wait(timeout=3) == -15, registry_log.read_text(errors="replace")[-3000:]
        stats = wait_reclaimed()
        looper, looper_log = start("disconnect", program, ["looper", socket])
        wait_marker(looper, looper_log, "hwbinder_looper_ready=1")
        time.sleep(0.05)
        daemon.terminate()
        assert daemon.wait(timeout=3) == 0, daemon_log.read_text(errors="replace")[-3000:]
        assert looper.wait(timeout=3) == 0, looper_log.read_text(errors="replace")[-3000:]
        assert "hwbinder_looper_returned=1\n" in looper_log.read_text(errors="replace")
        report.write_text(json.dumps({
            "passed": True, "gate": "P2-private-hwbinder", "completeG2": False,
            "checks": checks, "finalStats": stats, "processExitReclaimed": True,
            "brokerDisconnectNormalExit": True,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"Private Android 10 HwBinder: {len(checks)} checks; resources reclaimed; disconnect normal exit.")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        for handle in logs:
            handle.close()
