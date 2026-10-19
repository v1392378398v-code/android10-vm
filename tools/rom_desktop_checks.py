"""Check ROM desktop taps through the existing guest input and window services."""
import re
import shutil
import socket
import struct
import time

from test_desktop_support import capture_frame
from test_framework_support import wait_marker


def parse_tap(value):
    x, y, package = value.split(",", 2)
    x, y = float(x), float(y)
    if not (0 <= x < 1 and 0 <= y < 1 and package):
        raise ValueError("Expected normalized X,Y,PACKAGE with 0 <= X,Y < 1")
    return x, y, package


def verify_taps(runtime, start, environment, gpu, output, frame, taps):
    address = runtime.directory / "rom-input.sock"
    sequence = 0
    checks, latencies = [], []
    capture = output / "desktop.ppm"
    shutil.copyfile(capture, output / "desktop-before-taps.ppm")
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(address))
        listener.listen(1)
        listener.settimeout(5)
        child, log = start("input", [runtime.native("ld-android.so"), runtime.native("app_process64"),
            "-Xnoimage-dex2oat", "/system/bin", "io.a10vm.guest.DesktopInput", address], environment)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(4)
            wait_marker(child, log, "desktop_input_ready=1", 4)
            try:
                for number, (relative_x, relative_y, package) in enumerate(taps, 1):
                    x, y = int(relative_x * frame["width"]), int(relative_y * frame["height"])
                    for action in (0, 1):
                        sequence += 1
                        packet = struct.pack("<6IQ3If", 0x54434832, 1, sequence, action, 0, 1,
                                             time.monotonic_ns(), 0, x, y, 1.0).ljust(192, b"\0")
                        started = time.monotonic()
                        connection.sendall(packet)
                        reply = bytearray()
                        while len(reply) < 12:
                            chunk = connection.recv(12 - len(reply))
                            assert chunk, "Guest input channel closed"
                            reply.extend(chunk)
                        assert struct.unpack("<3I", reply) == (0x4131494e, sequence, 1), "Touch rejected"
                        latencies.append(round((time.monotonic() - started) * 1000, 2))
                        if action == 0:
                            time.sleep(0.08)
                    task, task_log = start("tap-check-" + str(number), [runtime.native("ld-android.so"),
                        runtime.native("app_process64"), "-Xnoimage-dex2oat", "/system/bin",
                        "io.a10vm.guest.DesktopTaskCheck", package], environment)
                    text = wait_marker(task, task_log, "desktop_task_ready=1", 20)
                    assert task.wait(timeout=2) == 0, task_log.read_text(errors="replace")[-2000:]
                    time.sleep(0.5)
                    captured = capture_frame(gpu, capture)
                    name = "tap-" + str(number) + ".ppm"
                    shutil.copyfile(capture, output / name)
                    checks.append({"expectedPackage": package,
                                   "topActivity": re.search(r"^desktop_task_drawn=(.*)$", text, re.M).group(1),
                                   "normalizedCoordinates": [relative_x, relative_y], "coordinates": [x, y],
                                   "windowDrawn": True, "frame": dict(captured, path=name)})
            finally:
                connection.sendall(struct.pack("<6IQ", 0x54434832, 0, sequence, 0, 0, 0, 0).ljust(192, b"\0"))
            assert child.wait(timeout=3) == 0, log.read_text(errors="replace")[-2000:]
    return {"passed": True, "acceptedEvents": sequence, "checks": checks,
            "maxAcknowledgementMs": max(latencies)}
