"""Process startup and cleanup shared by Android 10 integration checks."""
import subprocess
import socket
import struct
import time


def inspect_transport(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
        connection.settimeout(1)
        connection.connect(str(path))
        connection.sendall(struct.pack("<IIIIiIQQ", 0x41313042, 3, 7, 0, 0, 0, 0, 0))
        reply = connection.recv(65536)
    header = struct.unpack("<IIIIiIQQ", reply[:40])
    assert header[:3] == (0x41313042, 3, 8) and header[4] == 0
    values = struct.unpack("<28Q", reply[40:])
    names = ("processes", "threads", "nodes", "handles", "buffers", "calls", "deaths", "queuedFds",
             "transactions", "replies", "oneways", "freed", "disconnected", "pendingReferences",
             "registeredLoopers", "spawns", "largestBufferOwnerPid", "largestBufferOwnerBytes",
             "largestBufferCommand", "largestBufferDataBytes", "largestBufferId", "largestBufferOwnerProcess",
             "largestBufferSenderPid", "largestBufferTransactionCode", "largestBufferFlags",
             "largestBufferOffsetsBytes", "largestBufferCallId", "largestBufferIsReply")
    return dict(zip(names, values))


def wait_marker(child, log, marker, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = log.read_text(errors="replace")
        if marker + "\n" in text:
            return text
        if child.poll() is not None:
            raise AssertionError((child.returncode, log.name, text[-4000:]))
        time.sleep(0.02)
    raise AssertionError(("timeout", log.name, log.read_text(errors="replace")[-4000:]))


def stop_children(children, handles):
    try:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
    finally:
        for handle in handles:
            handle.close()


def start_properties(runtime, start):
    environment = runtime.framework_environment()
    directory = runtime.directory / "boot-properties"
    socket = runtime.directory / "property.sock"
    child, log = start("properties", [runtime.native("ld-android.so"), runtime.native("property-service"),
                       directory, runtime.directory / "guest.prop", socket], runtime.environment)
    wait_marker(child, log, "property_service_ready=1", 3)
    environment.update(A10VM_PROPERTIES=str(directory), A10VM_PROPERTY_SOCKET=str(socket),
                       LD_PRELOAD=str(runtime.native("liba10vm-property-client.so")) + ":" + environment["LD_PRELOAD"])
    return environment


def start_hardware(runtime, start, environment):
    socket = runtime.directory / "hwbinder.sock"
    broker, log = start("hwbroker", [runtime.native("ld-android.so"), runtime.native("binder-broker"), socket],
                        runtime.registry_environment())
    wait_marker(broker, log, "binder_broker_ready=1", 3)
    environment["A10VM_HWBINDER_PATH"] = str(socket)
    policy = dict(environment, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" + environment["LD_PRELOAD"])
    manager, log = start("hwmanager", [runtime.native("ld-android.so"), runtime.native("hwservicemanager")], policy)
    wait_marker(manager, log, "binder_context_ready=1", 3)
    return manager
