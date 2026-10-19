#!/usr/bin/env python3
"""Run an isolated ARM64 ROM trial using ordinary UID and existing host bridges."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from guest_runtime_fixture import RuntimeInstance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "guest-runtime"))
from test_framework_support import start_properties, start_hardware, wait_marker, stop_children, inspect_transport
from test_desktop_support import capture_frame
from rom_desktop_checks import parse_tap, verify_taps


def run_trial(prepared, output, phase, seconds, boot_jni="", bootstrap=None, dump_stacks=False, tap_checks=(),
              keep_runtime=False, keep_diagnostics=False):
    if os.getuid() < 10000:
        raise ValueError("Run the ROM trial under the ordinary Termux app UID")
    output = output.resolve()
    prepared = prepared.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    report = {"phase": phase, "uid": os.getuid(), "rootRequired": False, "passed": False,
              "prepared": str(prepared.resolve()), "desktopVerified": False}
    children, handles = [], []
    identities = {}
    directory = None

    def start(role, command, environment):
        log = output / (role + ".log")
        handle = log.open("w", encoding="utf-8")
        process = subprocess.Popen(list(map(str, command)), env=environment, cwd=runtime.rootfs, stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        children.append(process)
        handles.append(handle)
        try:
            status = (Path("/proc") / str(process.pid) / "status").read_text()
            identities[role] = {
                "uid": re.search(r"^Uid:\s+(\d+)", status, re.M).group(1),
                "capEff": re.search(r"^CapEff:\s+(\w+)", status, re.M).group(1),
                "selinux": (Path("/proc") / str(process.pid) / "attr/current").read_text().rstrip("\0\n")}
        except FileNotFoundError:
            pass
        return process, log

    def native(role, logical, environment, *arguments):
        return start(role, [runtime.native("ld-android.so"), runtime.native(logical), *arguments], environment)

    try:
        directory = Path(tempfile.mkdtemp(prefix="rom-", dir=ROOT / "artifacts"))
        (output / "runtime").symlink_to(directory)
        report["runtimeDirectory"] = str(directory)
        runtime = RuntimeInstance(directory, prepared=prepared)
        report["sourceImageSha256"] = runtime.inputs["sourceImageSha256"]
        unavailable = {"android.hardware.gnss", "vendor.qti.gnss"}
        for name, bridge in (("android.hardware.sensors", "sensors.sock"), ("android.hardware.vibrator", "vibrator.sock")):
            if not (Path(runtime.environment["A10VM_STATE_ROOT"]) / bridge).exists():
                unavailable.add(name)
        removed = set()
        for manifest in (runtime.rootfs / "vendor/etc/vintf").rglob("*.xml"):
            tree = ET.parse(manifest)
            changed = False
            for hal in list(tree.getroot()):
                name = hal.findtext("name", "")
                if name in unavailable:
                    tree.getroot().remove(hal)
                    removed.add(name)
                    changed = True
            if changed:
                tree.write(manifest, encoding="utf-8", xml_declaration=True)
        report["unavailableHostHals"] = sorted(removed)
        (output / "runtime-inputs.json").write_text(json.dumps(runtime.inputs, indent=2) + "\n", encoding="utf-8")
        if phase == "art":
            env = dict(runtime.environment, LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
            process, log = start("art", runtime.art_command("rom-art-trial"), env)
            process.wait(timeout=seconds)
            text = log.read_text(errors="replace")
            report.update(exitCode=process.returncode,
                          passed=process.returncode == 0 and "art_runtime_ready=1" in text,
                          evidence=text[-4500:])
        else:
            env = start_properties(runtime, start)
            env.update(A10VM_APP_PROCESS=str(runtime.native("app_process64")),
                       A10VM_LIBRARY_PATH=str(runtime.libraries))
            profile = runtime.inputs.get("romBoot", {})
            if profile.get("webviewPackage"):
                env["A10VM_WEBVIEW_PACKAGE"] = profile["webviewPackage"]
            if profile.get("hardwareApplications"):
                env["A10VM_HARDWARE_APPLICATIONS"] = json.dumps(profile["hardwareApplications"])
            if phase == "desktop":
                env.update(A10VM_GUEST_UID="1000", A10VM_GUEST_GID="1000")
            broker, log = native("broker", "binder-broker", runtime.registry_environment(), runtime.directory / "binder.sock")
            wait_marker(broker, log, "binder_broker_ready=1", 3)
            policy = dict(env, LD_PRELOAD=str(runtime.native("liba10vm-manager-policy.so")) + ":" + env["LD_PRELOAD"])
            manager, log = native("manager", "servicemanager", policy)
            wait_marker(manager, log, "binder_context_ready=1", 5)
            if phase in ("framework", "hardware"):
                start_hardware(runtime, start, env)
                if phase == "hardware":
                    if not bootstrap:
                        raise ValueError("Hardware trial requires the ROM bootstrap DEX")
                    native("health", "health", env)
                    env["CLASSPATH"] = ":".join([str(bootstrap.resolve(strict=True)), env["CLASSPATH"],
                                                *runtime.inputs["systemServerClassPath"]])
                    client, client_log = native("hardware-check", "app_process64", env, "-Xnoimage-dex2oat",
                                               "/system/bin", "io.a10vm.guest.RomHardwareCheck")
                    text = wait_marker(client, client_log, "rom_hardware_ready=1", seconds)
                    report.update(passed=client.wait(timeout=3) == 0, evidence=text[-4000:])
                    return report
                process, log = start("framework", runtime.framework_command("Server", "rom-framework-trial"), env)
                wait_marker(process, log, "framework_service_registered=rom-framework-trial", seconds)
                client, client_log = start("client", runtime.framework_command("Client", "rom-framework-trial"), env)
                text = wait_marker(client, client_log, "framework_complete=1", seconds)
                report.update(passed=client.wait(timeout=3) == 0, transactions=64, evidence=text[-4000:])
            else:
                env["A10VM_GPU_SOCKET"] = str(runtime.directory / "gpu.sock")
                gpu, log = start("gpu", [runtime.native("desktop-gpu-host"), env["A10VM_GPU_SOCKET"],
                                         output / "desktop.ppm"], {"PATH": "/system/bin", "TMPDIR": str(output)})
                wait_marker(gpu, log, "desktop_gpu_ready=1", 5)
                start_hardware(runtime, start, env)
                for role, logical in (("suspend", "system-suspend"), ("composer", "graphics-composer"),
                                      ("allocator", "graphics-allocator"), ("configstore", "graphics-configstore"),
                                      ("health", "health"), ("idmap", "idmap2d"), ("installer", "installd"),
                                      ("audio-hal", "audio-hal"), ("audio", "audioserver"),
                                      ("compositor", "surfaceflinger")):
                    role_env = dict(env, A10VM_GUEST_UID="0", A10VM_GUEST_GID="0") if role == "installer" else \
                        dict(env, A10VM_GUEST_UID="1041", A10VM_GUEST_GID="1005") if role in ("audio", "audio-hal") else env
                    native(role, logical, role_env)
                for role in ("media-extractor", "media-metrics", "media-drm", "drm", "media-omx", "media-codec", "media"):
                    native(role, role, dict(env, A10VM_GUEST_UID="1013", A10VM_GUEST_GID="1005"))
                report["romServicesStarted"] = []
                if "rom/system/xbin/shelld" in runtime.names:
                    native("rom-shelld", "rom/system/xbin/shelld", dict(env, A10VM_GUEST_UID="0", A10VM_GUEST_GID="0",
                           LD_PRELOAD=str(runtime.native("liba10vm-rom-service-identity.so")) + ":" + env["LD_PRELOAD"]))
                    report["romServicesStarted"].append("shelld")
                if "rom/system/bin/fdpp" in runtime.names:
                    native("rom-fdpp", "rom/system/bin/fdpp", dict(env, A10VM_GUEST_UID="0", A10VM_GUEST_GID="1000",
                           LD_PRELOAD=str(runtime.native("liba10vm-rom-service-identity.so")) + ":" + env["LD_PRELOAD"]),
                           "daemon")
                    report["romServicesStarted"].append("fdpp")
                env["CLASSPATH"] = ":".join([str(runtime.directory / "framework-check.dex"), *runtime.inputs["systemServerClassPath"]])
                if bootstrap:
                    env["CLASSPATH"] = str(bootstrap.resolve(strict=True)) + ":" + env["CLASSPATH"]
                    env["A10VM_BOOT_JNI"] = boot_jni
                env["SYSTEMSERVERCLASSPATH"] = ":".join(runtime.inputs["systemServerClassPath"])
                process, log = native("system-server", "app_process64", env, "-Xnoimage-dex2oat",
                                     "-Da10vm.bootSetupTimeoutMs=" + str(int((seconds + 10) * 1000)),
                                     "-Djava.library.path=" + str(runtime.libraries), "/system/bin",
                                     "io.a10vm.guest.RomBootstrap" if bootstrap else "io.a10vm.guest.DesktopBoot")
                checker = None
                if bootstrap:
                    checker, check_log = native("desktop-check", "app_process64", env, "-Xnoimage-dex2oat",
                                               "/system/bin", "io.a10vm.guest.RomDesktopCheck", str(int(seconds * 1000)))
                deadline = time.monotonic() + seconds
                while process.poll() is None and time.monotonic() < deadline:
                    text = log.read_text(errors="replace")
                    if checker and checker.poll() is not None:
                        break
                    time.sleep(0.2)
                if dump_stacks and process.poll() is None:
                    os.kill(process.pid, signal.SIGQUIT)
                    time.sleep(0.5)
                    report["transport"] = {name: inspect_transport(runtime.directory / socket)
                                           for name, socket in (("binder", "binder.sock"), ("hwbinder", "hwbinder.sock"))}
                text = log.read_text(errors="replace")
                report.update(systemServerEntered="Entered the Android system server!" in text,
                              systemServerAlive=process.poll() is None, exitCode=process.poll(), evidence=text[-6500:])
                check = check_log.read_text(errors="replace") if checker else ""
                report["bootCompleted"] = "rom_boot_completed=1\n" in check
                report["userUnlocked"] = "rom_user_unlocked=true\n" in check
                report["homePackage"] = re.findall(r"^rom_home_package=(.*)$", check, re.M)
                if checker and checker.poll() not in (None, 0):
                    raise AssertionError("ROM desktop check failed: " + check[-4000:])
                if "rom_desktop_ready=1\n" in check and process.poll() is None:
                    home = re.escape(report["homePackage"][0])
                    windows = [block for block in re.split(r"(?=  Window #)", check)
                               if re.match(r"  Window #[^\n]*" + home, block)]
                    drawn = any("mDrawState=HAS_DRAWN" in block and "mHasSurface=true" in block for block in windows)
                    report["homeWindowDrawn"] = drawn
                    report["frame"] = capture_frame(gpu, output / "desktop.ppm")
                    report.update(passed=drawn, desktopVerified=drawn)
                    if drawn and tap_checks:
                        report["touch"] = verify_taps(runtime, start, env, gpu, output, report["frame"], tap_checks)
                report["frameWritten"] = (output / "desktop.ppm").is_file()
    except Exception as error:
        report.update(passed=False, error=str(error)[-5000:])
    finally:
        report["frameWritten"] = (output / "desktop.ppm").is_file()
        report["processes"] = {Path(handle.name).stem: child.poll() for child, handle in zip(children, handles)}
        report["identities"] = identities
        stop_children(children, handles)
        if directory is not None and not keep_runtime:
            shutil.rmtree(directory)
            (output / "runtime").unlink(missing_ok=True)
        report["runtimeRetained"] = directory is not None and keep_runtime
        if not keep_diagnostics:
            for pattern in ("*.log", "*.ppm"):
                for path in output.glob(pattern):
                    path.unlink()
        report["diagnosticsRetained"] = keep_diagnostics
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("art", "framework", "hardware", "desktop"), default="art")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--boot-jni", default="")
    parser.add_argument("--bootstrap", type=Path)
    parser.add_argument("--dump-stacks", action="store_true")
    parser.add_argument("--keep-runtime", action="store_true", help="Retain the trial rootfs for debugging")
    parser.add_argument("--keep-diagnostics", action="store_true", help="Retain trial logs and frame captures")
    parser.add_argument("--tap-check", type=parse_tap, action="append", default=[], metavar="X,Y,PACKAGE",
                        help="Tap at normalized frame coordinates and verify the foreground package; repeatable")
    args = parser.parse_args()
    result = run_trial(args.prepared, args.output, args.phase, args.seconds, args.boot_jni, args.bootstrap,
                       args.dump_stacks, args.tap_check, args.keep_runtime, args.keep_diagnostics)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
