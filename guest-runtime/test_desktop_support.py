"""Verify the composed guest frame instead of accepting a boot property alone."""
import hashlib
import os
import re
import signal
import socket
import struct
import time
from test_framework_support import wait_marker


def verify_launcher(log):
    launches = re.findall(r"desktop_application_launch=(\d+):com\.android\.launcher3\b",
                          log.read_text(errors="replace"))
    assert len(launches) == 1, "Launcher exited or restarted: " + str(launches)
    pid = int(launches[0])
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        raise AssertionError("Launcher process exited: " + str(pid)) from None
    return {"pid": pid, "launchCount": len(launches), "alive": True}


def capture_frame(gpu, path):
    path.unlink(missing_ok=True)
    gpu.send_signal(signal.SIGUSR1)
    deadline = time.monotonic() + 2
    while not path.is_file():
        if gpu.poll() is not None or time.monotonic() >= deadline:
            raise AssertionError("Guest compositor did not submit a frame")
        time.sleep(0.02)
    with path.open("rb") as image:
        assert image.readline() == b"P6\n", "Guest frame format"
        width, height = map(int, image.readline().split())
        assert image.readline() == b"255\n", "Guest frame depth"
        pixels = image.read()
    assert len(pixels) == width * height * 3, "Guest frame is truncated"
    nonblack = sum(any(pixels[offset:offset + 3]) for offset in range(0, len(pixels), 3))
    assert nonblack > width * height // 20, "Guest desktop frame is black"
    return {"width": width, "height": height, "nonblackPixels": nonblack,
            "sha256": hashlib.sha256(pixels).hexdigest()}


def verify_touch(runtime, start, environment, gpu, capture, output):
    address = runtime.directory / "desktop-input.sock"
    sequence = 0
    latencies = []
    mode = capture_frame(gpu, capture)
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(address))
        listener.listen(1)
        listener.settimeout(5)
        child, log = start("input", [runtime.native("ld-android.so"), runtime.native("app_process64"),
            "-Xnoimage-dex2oat", "/system/bin",
            "io.a10vm.guest.DesktopInput", address], environment)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(4)
            wait_marker(child, log, "desktop_input_ready=1", 4)

            def event(action, x, y):
                nonlocal sequence
                sequence += 1
                packet = struct.pack("<6IQ3If", 0x54434832, 1, sequence, action, 0, 1,
                                     time.monotonic_ns(), 0, int(x * mode["width"] / 360),
                                     int(y * mode["height"] / 640), 1.0)
                started = time.monotonic()
                connection.sendall(packet.ljust(192, b"\0"))
                reply = bytearray()
                while len(reply) < 12:
                    chunk = connection.recv(12 - len(reply))
                    assert chunk, "Guest input channel closed"
                    reply.extend(chunk)
                assert struct.unpack("<3I", reply) == (0x4131494e, sequence, 1), "Touch rejected"
                latencies.append(round((time.monotonic() - started) * 1000, 2))

            def pixels():
                capture_frame(gpu, capture)
                with capture.open("rb") as image:
                    for _ in range(3):
                        image.readline()
                    return image.read()

            before = pixels()
            event(0, 180, 550)
            for step in range(1, 13):
                time.sleep(0.025)
                event(2, 180, 550 - step * 35)
            event(1, 180, 130)
            time.sleep(1.5)
            drawer = pixels()
            (output / "system-server-drawer.ppm").write_bytes(capture.read_bytes())
            region = slice(300 * 1080 * 3, 1500 * 1080 * 3)
            channels = region.stop - region.start
            changed = sum(a != b for a, b in zip(before[region], drawer[region]))
            assert changed > channels // 5, "Upward touch did not open the Launcher app drawer"
            event(0, 55, 128)
            event(1, 55, 128)
            task, task_log = start("settings-check", [runtime.native("ld-android.so"),
                runtime.native("app_process64"), "-Xnoimage-dex2oat",
                "/system/bin", "io.a10vm.guest.DesktopTaskCheck", "com.android.settings"], environment)
            wait_marker(task, task_log, "desktop_task_ready=1", 20)
            assert task.wait(timeout=2) == 0, task_log.read_text(errors="replace")[-1000:]
            time.sleep(1)
            settings = pixels()
            (output / "system-server-settings.ppm").write_bytes(capture.read_bytes())
            settings_changed = sum(a != b for a, b in zip(drawer[region], settings[region]))
            assert settings_changed > channels // 10, "Settings window did not replace the app drawer"
            event(0, 180, 615)
            event(1, 180, 615)
            task, task_log = start("home-check", [runtime.native("ld-android.so"),
                runtime.native("app_process64"), "-Xnoimage-dex2oat",
                "/system/bin", "io.a10vm.guest.DesktopTaskCheck", "com.android.launcher3"], environment)
            wait_marker(task, task_log, "desktop_task_ready=1", 20)
            assert task.wait(timeout=2) == 0, task_log.read_text(errors="replace")[-1000:]
            time.sleep(1.5)
            home = pixels()
            (output / "system-server-home.ppm").write_bytes(capture.read_bytes())
            returned = sum(a != b for a, b in zip(settings[region], home[region]))
            assert returned > channels // 5, "HOME touch did not return from Settings to Launcher"
            connection.sendall(struct.pack("<6IQ", 0x54434832, 0, sequence, 0, 0, 0, 0).ljust(192, b"\0"))
            assert child.wait(timeout=3) == 0, log.read_text(errors="replace")[-1500:]
    return {"acceptedEvents": sequence, "drawerChangedChannels": changed,
            "settingsChangedChannels": settings_changed, "settingsDrawn": True,
            "homeChangedChannels": returned, "maxAcknowledgementMs": max(latencies)}
