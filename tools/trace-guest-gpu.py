#!/usr/bin/env python3
"""Temporarily record the installed guest's GPU wire stream without changing packets."""
import argparse
import os
from pathlib import Path
import select
import socket
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--max-bytes", type=int, default=24 * 1024 * 1024,
                        help="Maximum bytes retained per direction and connection")
    args = parser.parse_args()
    path = Path("/data/data/io.a10vm/files/native-window/gpu.sock")
    real = path.with_name("gpu-trace-backend.sock")
    output = path.parent / "gpu-trace"
    uid = path.stat().st_uid
    output.mkdir(exist_ok=True)
    os.chown(output, uid, uid)
    if real.exists():
        raise RuntimeError("An earlier GPU trace is still installed")
    path.rename(real)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        os.chown(path, uid, uid)
        os.chmod(path, 0o600)
        listener.listen(16)
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
        deadline = time.monotonic() + args.seconds
        threads = []

        def record(client, number):
            with client, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as backend:
                backend.connect(str(real))
                streams = {client: backend, backend: client}
                with (output / (str(number) + "-client.bin")).open("wb") as sent, \
                        (output / (str(number) + "-server.bin")).open("wb") as received:
                    sizes = {client: 0, backend: 0}
                    while time.monotonic() < deadline:
                        for source in select.select(list(streams), [], [], .25)[0]:
                            data = source.recv(65536)
                            if not data:
                                return
                            remaining = max(0, args.max_bytes - sizes[source])
                            (sent if source is client else received).write(data[:remaining])
                            sizes[source] += len(data)
                            streams[source].sendall(data)

        print("gpu_trace_ready=1", flush=True)
        while time.monotonic() < deadline:
            if not select.select([listener], [], [], .25)[0]:
                continue
            client, _ = listener.accept()
            thread = threading.Thread(target=record, args=(client, len(threads)), daemon=True)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
        print("gpu_trace_connections=" + str(len(threads)), flush=True)
    finally:
        listener.close()
        path.unlink(missing_ok=True)
        real.rename(path)


if __name__ == "__main__":
    main()
