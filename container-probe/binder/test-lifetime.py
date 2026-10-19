#!/usr/bin/env python3
"""Keep a real reply buffer after its sender exits, then inspect the broker."""
import multiprocessing
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "artifacts/container/runtime"
WIRE_VERSION = int(re.search(r"constexpr uint32_t kVersion = (\d+);",
                             (ROOT / "container-probe/binder/native/Wire.h").read_text()).group(1))
HEADER = struct.Struct("<6I2Q")
TRANSACTION = struct.Struct("<2Q2IiI4Q")


def send(channel, kind, command=0, token=0, arg=0, data=b""):
    channel.sendall(HEADER.pack(0x41313042, WIRE_VERSION, kind, command, 0, 0, token, arg) + data)


def receive(channel):
    packet = channel.recv(256 * 1024)
    assert len(packet) >= HEADER.size, "Broker closed the reply channel"
    fields = HEADER.unpack_from(packet)
    assert fields[:2] == (0x41313042, WIRE_VERSION) and fields[4] == 0, fields
    return fields, packet[HEADER.size:]


def connect(path):
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    channel.settimeout(3)
    channel.connect(str(path))
    return channel


def attach(path):
    control = connect(path)
    send(control, 1)
    hello, _ = receive(control)
    thread = connect(path)
    send(thread, 1, token=hello[6], arg=os.getpid())
    receive(thread)
    return control, thread


def command(channel, code, data=b"", token=0):
    send(channel, 2, code, token=token, data=data)
    ack, _ = receive(channel)
    assert ack[2] == 8, ack


def read(channel):
    send(channel, 3, arg=256)
    return receive(channel)


def sender(path, ready):
    control, thread = attach(path)
    send(thread, 4)
    receive(thread)
    command(thread, 0x630C)  # BC_ENTER_LOOPER
    ready.send(True)
    event, _ = read(thread)
    assert event[3] == 0x80407202, event  # BR_TRANSACTION
    reply = TRANSACTION.pack(0, 0, 0, 0, 0, 0, 8, 0, 0, 0) + b"reply123"
    command(thread, 0x40406301, reply)  # BC_REPLY
    thread.close()
    control.close()


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    with tempfile.TemporaryDirectory(prefix="a10life-", dir=os.environ.get("TMPDIR")) as temporary:
        directory = Path(temporary)
        config = directory / "ld.config.txt"
        config.write_text(f"dir.probe = {RUNTIME}/bin\n[probe]\n"
                          "namespace.default.isolated = true\n"
                          f"namespace.default.search.paths = {RUNTIME}/lib\n"
                          f"namespace.default.permitted.paths = {RUNTIME}\n", encoding="utf-8")
        path = directory / "binder.sock"
        log_path = ROOT / "artifacts/container/runtime/binder/lifetime-broker.log"
        with log_path.open("w", encoding="utf-8") as log:
            broker = subprocess.Popen([str(RUNTIME / "bin/source-linker64"),
                                       str(RUNTIME / "bin/binder-broker"), str(path)],
                                      env={"PATH": "/system/bin", "A10VM_LD_CONFIG": str(config)},
                                      stdout=log, stderr=subprocess.STDOUT)
            child = None
            try:
                deadline = time.monotonic() + 3
                while not path.exists():
                    assert broker.poll() is None and time.monotonic() < deadline, log_path.read_text()
                    time.sleep(0.01)
                parent, ready = multiprocessing.Pipe()
                child = multiprocessing.Process(target=sender, args=(path, ready))
                child.start()
                assert parent.poll(3) and parent.recv(), "Reply sender did not register"
                control, thread = attach(path)
                request = TRANSACTION.pack(0, 0, 1, 0x10, 0, 0, 0, 0, 0, 0)
                command(thread, 0x40406300, request)  # BC_TRANSACTION
                for _ in range(2):
                    event, data = read(thread)
                    if event[3] == 0x80407203:  # BR_REPLY
                        assert data[TRANSACTION.size:] == b"reply123", data
                        break
                else:
                    raise AssertionError("Reply was not delivered")
                child.join(3)
                assert child.exitcode == 0, child.exitcode
                time.sleep(0.05)
                with connect(path) as observer:
                    send(observer, 7)
                    stats, data = receive(observer)
                    assert stats[2] == 8 and len(data) == 28 * 8, stats
                    values = struct.unpack("<28Q", data)
                    assert values[4] == 1 and values[22] == 0, values
                command(thread, 0x40086303, token=event[6])  # BC_FREE_BUFFER
                thread.close()
                control.close()
                broker.terminate()
                assert broker.wait(3) == 0, log_path.read_text()
                print("Binder sender exit: retained reply inspected and freed; broker normal exit.")
            finally:
                if child is not None and child.is_alive():
                    child.kill()
                    child.join(3)
                if broker.poll() is None:
                    broker.kill()
                broker.wait(3)


if __name__ == "__main__":
    main()
