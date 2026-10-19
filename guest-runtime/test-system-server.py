#!/usr/bin/env python3
"""Launch the real system server and retain the precise desktop boot failure."""
import json
import os
import re
from pathlib import Path
import subprocess
import shutil
import signal
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children, start_properties, start_hardware, inspect_transport
from test_desktop_support import capture_frame, verify_touch, verify_launcher

OUT = ROOT / "artifacts/container/desktop"
SOURCE = ROOT / "artifacts/container/runtime"
GRAPHICS = ROOT / "artifacts/container/graphics/desktop"


def main():
    (OUT / "system-server-report.json").unlink(missing_ok=True)
    for previous in OUT.glob("system-server-application-*.log"):
        previous.unlink()
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    children, handles = [], []
    running, role_logs = {}, {}
    report = {"passed": False, "uid": os.getuid(), "rootRequired": False,
              "stockSystemServer": True, "desktopVerified": False}
    with tempfile.TemporaryDirectory(prefix="ss-", dir=OUT) as temporary:
        built = bool(os.environ.get("A10VM_TEST_BUILT_BINDER"))
        native = {
            "liba10binder.so": SOURCE / "lib/liba10binder.so",
            "binder-broker": SOURCE / "bin/binder-broker",
        } if built else {}
        if os.environ.get("A10VM_TEST_SOURCE_CXX"):
            native["libc++.so"] = SOURCE / "lib/libc++.so"
        runtime = RuntimeInstance(temporary, native)
        report["packagedRuntime"] = not built

        def start(role, command, env):
            log = OUT / ("system-server-" + role + ".log")
            handle = log.open("w", encoding="utf-8")
            if role == "main" and os.environ.get("A10VM_TRACE_SYSTEM_SERVER"):
                calls = os.environ.get("A10VM_TRACE_SYSCALLS", "execve,openat")
                command = [shutil.which("strace"), "-f", "-e", "trace=" + calls, "-o",
                           OUT / "system-server-loader.trace", "-E", "LD_PRELOAD=" + env["LD_PRELOAD"]] + command
                env = {key: value for key, value in env.items() if key != "LD_PRELOAD"}
            elif role == "main" and os.environ.get("A10VM_DEBUG_SYSTEM_SERVER"):
                command = [shutil.which("gdb"), "-q", "-nx", "-batch", "-ex", "set pagination off",
                           "-ex", "set exec-wrapper env LD_PRELOAD=" + env["LD_PRELOAD"],
                           "-ex", "handle SIGPIPE nostop noprint pass", "-ex", "run",
                           "-ex", "thread apply all bt 12", "--args"] + command
                env = {key: value for key, value in env.items() if key != "LD_PRELOAD"}
            elif role in os.environ.get("A10VM_DEBUG_DESKTOP_ROLES", "").split(","):
                command = [shutil.which("gdb"), "-q", "-nx", "-batch", "-ex", "set pagination off",
                           "-ex", "handle SIGPIPE nostop noprint pass", "-ex", "run",
                           "-ex", "thread apply all bt 30", "--args"] + command
            elif role in os.environ.get("A10VM_TRACE_DESKTOP_ROLES", "").split(","):
                command = [shutil.which("strace"), "-f", "-e", "trace=openat,faccessat,newfstatat,getdents64,connect",
                    "-o", OUT / ("system-server-" + role + ".trace"), "-E", "LD_PRELOAD=" + env["LD_PRELOAD"]] + command
                env = {key: value for key, value in env.items() if key != "LD_PRELOAD"}
            child = subprocess.Popen(list(map(str, command)), env=env, stdout=handle,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            children.append(child)
            handles.append(handle)
            running[role], role_logs[role] = child, log
            return child, log

        try:
            environment = start_properties(runtime, start)
            if os.environ.get("A10VM_APP_CANVAS"):
                environment["A10VM_APP_CANVAS"] = os.environ["A10VM_APP_CANVAS"]
            if os.environ.get("A10VM_DEBUG_APP_MALLOC"):
                environment["A10VM_DEBUG_APP_MALLOC"] = os.environ["A10VM_DEBUG_APP_MALLOC"]
            registry_environment = runtime.registry_environment()
            if os.environ.get("A10VM_DEBUG_PENDING"):
                registry_environment["A10VM_DEBUG_PENDING"] = "1"
            if os.environ.get("A10VM_DEBUG_JAVA_THREADS"):
                environment["A10VM_DEBUG_JAVA_THREADS"] = "1"
            environment["A10VM_GPU_SOCKET"] = str(runtime.directory / "gpu.sock")
            capture = OUT / "system-server-frame.ppm"
            capture.unlink(missing_ok=True)
            gpu, gpu_log = start("gpu", [runtime.native("desktop-gpu-host"), environment["A10VM_GPU_SOCKET"], capture],
                {"PATH": "/system/bin", "TMPDIR": temporary})
            wait_marker(gpu, gpu_log, "desktop_gpu_ready=1", 3)
            environment.update(A10VM_GUEST_UID="1000", A10VM_GUEST_GID="1000")
            broker, log = start("broker", [runtime.native("ld-android.so"),
                runtime.native("binder-broker"), runtime.directory / "binder.sock"],
                registry_environment)
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            policy = dict(environment, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) +
                          ":" + environment["LD_PRELOAD"])
            manager, log = start("manager", [runtime.native("ld-android.so"),
                runtime.native("servicemanager")], policy)
            wait_marker(manager, log, "binder_context_ready=1", 3)
            hardware = start_hardware(runtime, start, environment)
            report["hwServiceManagerStarted"] = hardware.poll() is None
            (runtime.rootfs / "data/misc/keystore").mkdir(parents=True, exist_ok=True)
            keymaster, log = start("keymaster", [runtime.native("ld-android.so"),
                runtime.native("image/vendor/bin/hw/android.hardware.keymaster@3.0-service")],
                dict(environment, A10VM_GUEST_UID="9999", A10VM_GUEST_GID="9999"))
            wait_marker(keymaster, log,
                "Registration complete for android.hardware.keymaster@3.0::IKeymasterDevice/default.", 5)
            keystore, log = start("keystore", [runtime.native("ld-android.so"),
                runtime.native("image/system/bin/keystore"), "/data/misc/keystore"],
                dict(environment, A10VM_GUEST_UID="1017", A10VM_GUEST_GID="1017"))
            wait_marker(keystore, log, "with interface name default and seclevel SOFTWARE", 5)
            environment["A10VM_NATIVE_KEYSTORE"] = "1"
            suspend, _ = start("suspend", [runtime.native("ld-android.so"), runtime.native("system-suspend")],
                               environment)
            composer, _ = start("composer", [runtime.native("ld-android.so"), runtime.native("graphics-composer")],
                                environment)
            allocator, _ = start("allocator", [runtime.native("ld-android.so"), runtime.native("graphics-allocator")],
                                 environment)
            start("configstore", [runtime.native("ld-android.so"), runtime.native("graphics-configstore")], environment)
            start("health", [runtime.native("ld-android.so"), runtime.native("health")], environment)
            start("idmap", [runtime.native("ld-android.so"), runtime.native("idmap2d")], environment)
            start("audio-hal", [runtime.native("ld-android.so"), runtime.native("audio-hal")],
                  dict(environment, A10VM_GUEST_UID="1041", A10VM_GUEST_GID="1005"))
            start("audio", [runtime.native("ld-android.so"), runtime.native("audioserver")],
                  dict(environment, A10VM_GUEST_UID="1041", A10VM_GUEST_GID="1005"))
            installer, _ = start("installer", [runtime.native("ld-android.so"), runtime.native("installd")],
                                 dict(environment, A10VM_GUEST_UID="0", A10VM_GUEST_GID="0"))
            compositor, _ = start("compositor", [runtime.native("ld-android.so"), runtime.native("surfaceflinger")],
                                  environment)
            environment["CLASSPATH"] = ":".join([str(runtime.directory / "framework-check.dex"),
                                                 *runtime.inputs["systemServerClassPath"]])
            environment["SYSTEMSERVERCLASSPATH"] = ":".join(runtime.inputs["systemServerClassPath"])
            environment["A10VM_APP_PROCESS"] = str(runtime.native("app_process64"))
            environment["A10VM_LIBRARY_PATH"] = str(runtime.libraries)
            command = [runtime.native("ld-android.so"), runtime.native("app_process64"),
                       "-Xnoimage-dex2oat",
                       "-Djava.library.path=" + str(runtime.libraries), "/system/bin",
                       "io.a10vm.guest.DesktopBoot"]
            server, log = start("main", command, environment)
            deadline = time.monotonic() + float(os.environ.get("A10VM_BOOT_OBSERVE_SECONDS", "12"))
            debugged = set()
            while server.poll() is None and time.monotonic() < deadline:
                for role in ("gpu", "composer", "allocator", "compositor"):
                    if running[role].poll() is not None:
                        raise AssertionError(role + " exited: " + role_logs[role].read_text(errors="replace")[-2500:])
                if os.environ.get("A10VM_DEBUG_APPLICATION_CRASH") and not os.environ.get("A10VM_DEBUG_APPLICATION_AFTER_BOOT"):
                    for pid, name in re.findall(r"desktop_application_launch=(\d+):([^\s]+)", log.read_text(errors="replace")):
                        names = os.environ.get("A10VM_DEBUG_APPLICATION_NAMES",
                            "com.android.systemui,com.android.settings,com.android.launcher3").split(",")
                        if name not in names or pid in debugged:
                            continue
                        debugged.add(pid)
                        debug_script = os.environ.get("A10VM_DEBUG_APPLICATION_SCRIPT")
                        extra = ["-ex", "source " + debug_script] if debug_script else []
                        start("debug-application-" + pid, [shutil.which("gdb"), "-q", "-nx", "-batch", "-p", pid,
                            "-ex", "set pagination off", "-ex", "handle SIGPIPE nostop noprint pass",
                            *extra, "-ex", "continue", "-ex", "info registers", "-ex", "x/16gx $x0",
                            "-ex", "x/8gx $x19", "-ex", "x/20i $pc-32", "-ex", "bt full",
                            "-ex", "thread apply all bt 20", "-ex", "detach"], {"PATH": os.environ["PATH"]})
                time.sleep(0.05)
            text = log.read_text(errors="replace")
            identity = re.search(r"\bdesktop_pid=(\d+)", text)
            server_pid = int(identity.group(1)) if identity else server.pid
            if server.poll() is None and os.environ.get("A10VM_JAVA_HANG"):
                os.kill(server_pid, signal.SIGQUIT)
                for application_log in runtime.directory.glob("application-*.log"):
                    pid = re.search(r"application_pid=(\d+)", application_log.read_text(errors="replace"))
                    if pid:
                        try:
                            os.kill(int(pid.group(1)), signal.SIGQUIT)
                        except ProcessLookupError:
                            pass
                time.sleep(0.3)
            if server.poll() is None and os.environ.get("A10VM_DEBUG_APPLICATIONS"):
                for application_log in runtime.directory.glob("application-*.log"):
                    application = application_log.read_text(errors="replace")
                    pid = re.search(r"application_pid=(\d+)", application)
                    if not pid:
                        continue
                    debug = subprocess.run([shutil.which("gdb"), "-q", "-nx", "-batch", "-p", pid.group(1),
                        "-ex", "set pagination off", "-ex", "thread apply all bt 10", "-ex", "detach"],
                        env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=10)
                    (OUT / ("system-server-" + application_log.stem + "-hang.log")).write_text(
                        debug.stdout + debug.stderr, encoding="utf-8")
            debug_roles = os.environ.get("A10VM_DEBUG_HANG_ROLES", "main" if os.environ.get("A10VM_DEBUG_HANG") else "")
            for role in filter(None, debug_roles.split(",")):
                if running[role].poll() is not None:
                    continue
                debug = subprocess.run([shutil.which("gdb"), "-q", "-nx", "-batch", "-p", str(running[role].pid),
                    "-ex", "set pagination off", "-ex", "thread apply all bt 10", "-ex", "detach"],
                    env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=10)
                (OUT / ("system-server-" + role + "-hang.log")).write_text(debug.stdout + debug.stderr, encoding="utf-8")
            report.update(systemServerExit=server.poll(),
                          systemServerEntered="Entered the Android system server!" in text,
                          errorTail=text[-4500:])
            if server.poll() is not None:
                raise AssertionError("Stock system server exited: " + text[-1500:])
            mappings = (Path("/proc") / str(server_pid) / "maps").read_text().splitlines()
            binder_copies = {name: sum("x" in line.split()[1] and line.endswith(str(runtime.native(name)))
                                     for line in mappings)
                            for name in ("libbinder.so", "libhwbinder.so", "libhidlbase.so", "liba10binder.so", "libandroid_runtime.so", "libutils.so")}
            report["binderLibraryCopies"] = binder_copies
            assert all(count == 1 for count in binder_copies.values()), binder_copies
            report["transports"] = {name: inspect_transport(runtime.directory / (name + ".sock"))
                                    for name in ("binder", "hwbinder")}
            check_command = [runtime.native("ld-android.so"), runtime.native("app_process64"),
                             "-Xnoimage-dex2oat", "/system/bin",
                             "io.a10vm.guest.DesktopCheck", "--dump-window"]
            if os.environ.get("A10VM_DEBUG_COMPOSITION"):
                check_command.append("--dump-surfaceflinger")
            check_environment = dict(environment, CLASSPATH=str(runtime.directory / "framework-check.dex"))
            checker, check_log = start("check", check_command, check_environment)
            wait_marker(checker, check_log, "desktop_services_ready=1", 55)
            assert checker.wait(timeout=2) == 0 and server.poll() is None
            if os.environ.get("A10VM_DESKTOP_SETTLE_SECONDS"):
                time.sleep(float(os.environ["A10VM_DESKTOP_SETTLE_SECONDS"]))
            report["frame"] = capture_frame(gpu, capture)
            window_state = check_log.read_text(errors="replace")
            launcher_windows = [block for block in re.split(r"(?=  Window #)", window_state)
                                if re.match(r"  Window #[^\n]*com.android.launcher3", block)]
            report["launcherDrawn"] = any("mDrawState=HAS_DRAWN" in block and
                                          "mHasSurface=true" in block for block in launcher_windows)
            assert report["launcherDrawn"], "Launcher3 window has not completed drawing"
            report["launcherBeforeTouch"] = verify_launcher(log)
            if os.environ.get("A10VM_DEBUG_APPLICATION_AFTER_BOOT"):
                pid = str(report["launcherBeforeTouch"]["pid"])
                start("debug-application-" + pid, [shutil.which("gdb"), "-q", "-nx", "-batch", "-p", pid,
                    "-ex", "set pagination off", "-ex", "handle SIGPIPE nostop noprint pass",
                    "-ex", "source " + os.environ["A10VM_DEBUG_APPLICATION_SCRIPT"],
                    "-ex", "continue", "-ex", "info registers", "-ex", "x/20i $pc-32",
                    "-ex", "bt full", "-ex", "thread apply all bt 20", "-ex", "detach"],
                    {"PATH": os.environ["PATH"]})
                time.sleep(0.4)
            report["touch"] = verify_touch(runtime, start, check_environment, gpu, capture, OUT)
            report["launcherAfterTouch"] = verify_launcher(log)
            report.update(passed=True, bootCompleted=True, desktopVerified=True)
        except Exception as error:
            report["error"] = str(error)[-1600:]
            if os.environ.get("A10VM_DEBUG_PENDING"):
                report["failureTransports"] = {name: inspect_transport(runtime.directory / (name + ".sock"))
                                               for name in ("binder", "hwbinder")}
            for role in filter(None, os.environ.get("A10VM_DEBUG_FAILURE_ROLES", "").split(",")):
                if role not in running or running[role].poll() is not None:
                    continue
                debug = subprocess.run([shutil.which("gdb"), "-q", "-nx", "-batch", "-p", str(running[role].pid),
                    "-ex", "set pagination off", "-ex", "thread apply all bt 18", "-ex", "detach"],
                    env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=15)
                (OUT / ("system-server-" + role + "-failure.log")).write_text(debug.stdout + debug.stderr, encoding="utf-8")
            if os.environ.get("A10VM_DEBUG_APPLICATION_FAILURE"):
                for application_log in runtime.directory.glob("application-*.log"):
                    application = application_log.read_text(errors="replace")
                    pid = re.search(r"application_pid=(\d+)", application)
                    if pid:
                        try:
                            os.kill(int(pid.group(1)), signal.SIGQUIT)
                        except ProcessLookupError:
                            continue
                        time.sleep(0.3)
                        debug = subprocess.run([shutil.which("gdb"), "-q", "-nx", "-batch", "-p", pid.group(1),
                            "-ex", "set pagination off", "-ex", "thread apply all bt 18", "-ex", "detach"],
                            env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=10)
                        (OUT / ("system-server-" + application_log.stem + "-failure.log")).write_text(
                            debug.stdout + debug.stderr, encoding="utf-8")
        finally:
            if "gpu" in running and running["gpu"].poll() is None:
                running["gpu"].send_signal(signal.SIGUSR1)
                capture_deadline = time.monotonic() + 0.5
                while time.monotonic() < capture_deadline and not capture.is_file():
                    time.sleep(0.02)
            application_logs = sorted(runtime.directory.glob("application-*.log"))
            for application_log in application_logs:
                shutil.copyfile(application_log, OUT / ("system-server-" + application_log.name))
            report["applicationLogs"] = [path.name for path in application_logs]
            report["serviceExits"] = {role: child.poll() for role, child in running.items()}
            report["serviceErrors"] = {role: role_logs[role].read_text(errors="replace")[-2500:]
                                       for role, child in running.items() if child.poll() is not None}
            stop_children(children, handles)
            for child in reversed(children):
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            report["processCleanupPassed"] = all(child.poll() is not None for child in children)
            (OUT / "system-server-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
