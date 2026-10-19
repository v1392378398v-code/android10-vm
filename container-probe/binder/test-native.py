#!/usr/bin/env python3
"""Exercise Android 10 Binder API in separate processes with the private source runtime."""
import json
import os
import pathlib
import subprocess
import tempfile
import time

root = pathlib.Path(__file__).resolve().parents[2]
runtime = root / "artifacts/container/runtime"
output = runtime / "binder"
linker = runtime / "bin/source-linker64"
program = runtime / "bin/binder-probe"
broker = runtime / "bin/binder-broker"
output.mkdir(parents=True, exist_ok=True)
report = output / "local-report.json"
report.unlink(missing_ok=True)
names = ("libc.so", "libdl.so", "libm.so", "libc++.so", "libunwind.so", "liblog.so",
         "libbase.so", "libcutils.so", "libutils.so", "libbinderthreadstate.so",
         "liba10binder.so", "libbinder.so")


def wait_marker(child, log, marker, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = log.read_text(errors="replace")
        if marker in text:
            return text
        if child.poll() is not None:
            text = log.read_text(errors="replace")
            if marker in text:
                return text
            raise AssertionError((child.returncode, log.name, text[-6000:]))
        time.sleep(0.02)
    raise AssertionError(("timeout", log.name, log.read_text(errors="replace")[-6000:]))


with tempfile.TemporaryDirectory(prefix="a10b-", dir=os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")) as temporary:
    directory = pathlib.Path(temporary)
    seed = directory / "properties"
    env = {"PATH": "/system/bin", "TMPDIR": str(directory)}
    seeded = subprocess.run([
        str(root / "artifacts/container/properties/bin/property-probe"), "run", str(seed),
        "binder-seed", "/system/bin/linker64",
    ], env=env, capture_output=True, text=True, timeout=15)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    for name in names:
        (directory / name).symlink_to(runtime / "lib" / name)
    config = directory / "ld.config.txt"
    config.write_text(f"dir.probe = {program.parent}\n[probe]\nnamespace.default.isolated = true\n"
                      f"namespace.default.search.paths = {directory}\n"
                      f"namespace.default.permitted.paths = {runtime}\n", encoding="utf-8")
    env.update(A10VM_PROPERTIES=str(seed), A10VM_LD_CONFIG=str(config))
    path = directory / "binder.sock"
    env["A10VM_BINDER_PATH"] = str(path)
    children = []
    logs = []

    def start(label, binary, args, extra=None):
        log = output / f"local-{label}.log"
        handle = log.open("w", encoding="utf-8")
        child = subprocess.Popen([str(linker), str(binary), *map(str, args)],
                                 env=dict(env, **(extra or {})), stdout=handle, stderr=subprocess.STDOUT)
        children.append(child)
        logs.append(handle)
        return child, log

    def inspect():
        result = subprocess.run([str(linker), str(program), "inspect", str(path)],
                                env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode == 0, result.stdout + result.stderr
        line = next(line for line in result.stdout.splitlines() if line.startswith("STATS\t"))
        values = list(map(int, line.split("\t")[1:]))
        inspect.owner = values[16:18]
        return values[:16]

    def wait_stats(predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            stats = inspect()
            if predicate(stats):
                return stats
            time.sleep(0.02)
        raise AssertionError(("resource timeout", stats))

    try:
        exiting, exiting_log = start("buffer-exit", program, ["buffer-exit", path])
        assert exiting.wait(timeout=3) == 0, exiting_log.read_text()
        assert "binder_exit_buffers_alive=1\n" in exiting_log.read_text(), exiting_log.read_text()
        daemon, daemon_log = start("broker", broker, [path])
        wait_marker(daemon, daemon_log, "binder_broker_ready=1")
        context, context_log = start("registry", program, ["registry", path])
        wait_marker(context, context_log, "binder_registry_ready=1")
        server, server_log = start("service", program, ["service", path])
        wait_marker(server, server_log, "binder_service_ready=1")
        caller, caller_log = start("client", program, ["client", path], {"A10VM_SERVICE_PID": str(server.pid)})
        text = wait_marker(caller, caller_log, "binder_client_complete=", 15)
        assert caller.wait(timeout=5) == 0, caller_log.read_text(errors="replace")[-6000:]
        assert "binder_client_complete=1\n" in text and "\t0\n" not in text, text
        assert "binder_client_returned=1\n" in caller_log.read_text(errors="replace")
        assert server.wait(timeout=3) == 0, server_log.read_text(errors="replace")[-6000:]
        wait_stats(lambda stats: stats[4] == 0)
        context.terminate()
        context.wait(timeout=3)
        stats = wait_stats(lambda value: value[:8] == [0] * 8 and value[13:15] == [0, 0])
        # A separate ordinary looper must exit normally when its broker goes away.
        looper, looper_log = start("disconnect", program, ["looper", path])
        wait_marker(looper, looper_log, "binder_looper_ready=1")
        time.sleep(0.05)
        daemon.terminate()
        assert daemon.wait(timeout=3) == 0, daemon_log.read_text()
        assert looper.wait(timeout=3) == 0, looper_log.read_text(errors="replace")[-6000:]
        assert "binder_looper_returned=1\n" in looper_log.read_text(errors="replace")
        checks = [line.split("\t")[1] for line in text.splitlines() if line.startswith("CHECK\t")]
        assert len(checks) == len(set(checks)), checks
        report.write_text(json.dumps({
            "passed": True, "gate": "G2-private-binder", "completeG2": False,
            "checks": checks, "finalStats": stats, "brokerDisconnectNormalExit": True,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"Private Android 10 Binder: {len(checks)} checks; resources reclaimed; disconnect normal exit.")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        for handle in logs:
            handle.close()
