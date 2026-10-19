#!/usr/bin/env python3
"""Measure real broker round trips while unrelated connections remain idle."""
import argparse
import errno
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "artifacts/container/runtime"
HEADER = struct.Struct("<IIIIiIQQ")
REQUEST = HEADER.pack(0x41313042, 3, 6, 0, 0, 0, 0, 0)


def cpu_ticks(pid):
    fields = Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])


def measure(directory, environment, idle_count, rounds, registered=False):
    path = directory / ("broker-%d.sock" % idle_count)
    peers = []
    with (directory / ("broker-%d.log" % idle_count)).open("w") as log:
        daemon = subprocess.Popen([str(RUNTIME / "bin/source-linker64"),
                                   str(RUNTIME / "bin/binder-broker"), str(path)],
                                  env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 5
            while not path.exists():
                if daemon.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError("Broker did not start")
                time.sleep(.01)
            for index in range(idle_count + 1):
                peer = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                peer.settimeout(3)
                peer.connect(str(path))
                peers.append(peer)
                if registered and index < idle_count:
                    peer.sendall(HEADER.pack(0x41313042, 3, 1, 0, 0, 0, 0, 0))
                    reply = HEADER.unpack(peer.recv(HEADER.size))
                    assert reply[2] == 8 and reply[4] == 0 and reply[6] != 0, reply
                    thread = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                    thread.settimeout(3)
                    thread.connect(str(path))
                    peers.append(thread)
                    thread.sendall(HEADER.pack(0x41313042, 3, 1, 0, 0, 0,
                                              reply[6], threading.get_native_id()))
                    assert HEADER.unpack(thread.recv(HEADER.size))[4] == 0
                    thread.sendall(HEADER.pack(0x41313042, 3, 2, 0x630c, 0, 0, 0, 0))
                    assert HEADER.unpack(thread.recv(HEADER.size))[4] == 0
                    thread.sendall(HEADER.pack(0x41313042, 3, 3, 0, 0, 0, 0, 256))
                    continue
                peer.sendall(REQUEST)
                reply = HEADER.unpack(peer.recv(HEADER.size))
                assert reply[:3] == (0x41313042, 3, 8) and reply[4] == errno.EPROTO, reply
            active = peers[-1]
            before = cpu_ticks(daemon.pid)
            started = time.monotonic()
            for _ in range(rounds):
                active.sendall(REQUEST)
                reply = HEADER.unpack(active.recv(HEADER.size))
                assert reply[:3] == (0x41313042, 3, 8) and reply[4] == errno.EPROTO, reply
            elapsed = time.monotonic() - started
            seconds = (cpu_ticks(daemon.pid) - before) / os.sysconf("SC_CLK_TCK")
            # Closing idle descriptors must leave the active peer usable.
            for peer in peers[:-1]:
                peer.close()
            active.sendall(REQUEST)
            assert HEADER.unpack(active.recv(HEADER.size))[4] == errno.EPROTO
            # Fill the response socket, then drain it. Writable interest must
            # disappear once the output queue empties, so the broker sleeps.
            for _ in range(1024):
                active.sendall(REQUEST)
            for _ in range(1024):
                assert HEADER.unpack(active.recv(HEADER.size))[4] == errno.EPROTO
            idle_before = cpu_ticks(daemon.pid)
            time.sleep(.15)
            idle_ticks = cpu_ticks(daemon.pid) - idle_before
            assert idle_ticks < 5, ("Broker spins after draining backpressure", idle_ticks)
            return {"idleConnections": idle_count, "rounds": rounds,
                    "registeredIdleProcesses": idle_count if registered else 0,
                    "elapsedSeconds": round(elapsed, 6), "brokerCpuSeconds": round(seconds, 3),
                    "roundTripsPerSecond": round(rounds / elapsed), "activePeerSurvivedClose": True,
                    "backpressureDrained": True, "idleCpuTicks": idle_ticks}
        finally:
            for peer in peers:
                peer.close()
            daemon.terminate()
            try:
                assert daemon.wait(timeout=3) == 0
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idle", type=int, default=768)
    parser.add_argument("--rounds", type=int, default=3000)
    parser.add_argument("--registered", action="store_true",
                        help="Register idle Binder contexts and park their looper reads")
    args = parser.parse_args()
    assert 1 <= args.idle <= 768 and 1 <= args.rounds <= 10000
    with tempfile.TemporaryDirectory(prefix="a10bi-", dir=os.environ.get("TMPDIR")) as temporary:
        directory = Path(temporary)
        for source in (RUNTIME / "lib").glob("*.so"):
            (directory / source.name).symlink_to(source)
        seed = directory / "properties"
        environment = {"PATH": "/system/bin", "TMPDIR": str(directory)}
        subprocess.run([str(ROOT / "artifacts/container/properties/bin/property-probe"), "run",
                        str(seed), "broker-idle", "/system/bin/linker64"], env=environment,
                       capture_output=True, check=True, timeout=15)
        config = directory / "ld.config.txt"
        config.write_text("dir.probe = %s\n[probe]\nnamespace.default.isolated = true\n"
                          "namespace.default.search.paths = %s\nnamespace.default.permitted.paths = %s\n"
                          % (RUNTIME / "bin", directory, RUNTIME), encoding="utf-8")
        environment.update(A10VM_PROPERTIES=str(seed), A10VM_LD_CONFIG=str(config))
        report = {"rootRequired": False, "samples": [measure(directory, environment, count, args.rounds, args.registered)
                  for count in (0, args.idle)],
                  "limitation": "Broker round trips with idle sockets; excludes app rendering and ART"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
