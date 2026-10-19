#!/usr/bin/env python3
"""Run one command through the installed APK's guest Binder as its ordinary UID."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
SERIAL = None
PACKAGE = "io.a10vm"


def device_argv(command):
    return ["adb", "-s", SERIAL, "exec-out", command] if SERIAL else ["su", "-c", command]


def device(command, timeout=140):
    return subprocess.run(device_argv(command), env=ENV, capture_output=True,
                          timeout=timeout, check=True).stdout.decode(errors="replace")


def native_input(logical, manifest):
    entries = {item["logical"]: item for item in manifest["files"]}
    links = {item["path"].removeprefix("rootfs"): item["logical"]
             for item in manifest.get("nativeLinks", [])}
    path = logical[len("image"):] if logical.startswith("image/") else logical
    if logical not in entries:
        logical = links.get(path, logical)
    item = entries[logical]
    guest = item.get("guestPath") or next((key for key, value in links.items() if value == logical), None)
    return item, guest


def main():
    global SERIAL, PACKAGE
    args = sys.argv[1:]
    while args and args[0] in ("--serial", "--package"):
        option, value, args = args[0], args[1], args[2:]
        if option == "--serial":
            SERIAL = value
        elif value in ("io.a10vm", "io.a10vm.miui"):
            PACKAGE = value
        else:
            raise ValueError("Expected an A10VM package")
    run_as = "run-as " + PACKAGE + " "
    package = device("/system/bin/pm path " + PACKAGE).strip().split("package:", 1)[1]
    native = str(Path(package).parent / "lib/arm64")
    config = device(run_as + "cat files/guest-runtime/ld.config.txt")
    directory = next(path for path in re.findall(r"^dir\.guest = (.+)$", config, re.M)
                     if Path(path).name == "guest-runtime")
    state = str(Path(directory).parent)
    prepared = "rom-prepared/miui12" if PACKAGE == "io.a10vm.miui" else "prepared"
    manifest = json.loads((ROOT / "guest-runtime/build" / prepared / "assets/guest-runtime-inputs.json").read_text())
    names = {entry["logical"]: native + "/" + entry["name"] for entry in manifest["files"]}
    environment = {"PATH": "/system/bin", "TMPDIR": directory, "ANDROID_ROOT": "/system",
        "ANDROID_DATA": "/data", "ANDROID_STORAGE": "/storage", "EXTERNAL_STORAGE": "/storage/emulated/0",
        "ANDROID_RUNTIME_ROOT": "/apex/com.android.runtime", "ANDROID_TZDATA_ROOT": "/apex/com.android.tzdata",
        "A10VM_ROOTFS": directory + "/rootfs", "A10VM_HOST_ROOT": native, "A10VM_STATE_ROOT": state,
        "A10VM_LD_CONFIG": directory + "/ld.config.txt", "A10VM_EXEC_LINKER": names["ld-android.so"],
        "A10VM_PROPERTIES": directory + "/boot-properties", "A10VM_PROPERTY_SOCKET": directory + "/property.sock",
        "A10VM_BINDER_PATH": directory + "/binder.sock", "A10VM_HWBINDER_PATH": directory + "/hwbinder.sock",
        "A10VM_GPU_SOCKET": state + "/native-window/gpu.sock",
        "A10VM_GUEST_UID": "2000", "A10VM_GUEST_GID": "2000", "A10VM_HOST_NETWORK": "1",
        "CLASSPATH": directory + "/framework-check.dex", "BOOTCLASSPATH": ":".join(manifest["bootClassPath"]),
        "LD_PRELOAD": ":".join(names[name] for name in ("liba10vm-property-client.so", "liba10vm-hal-modules.so",
            "liba10vm-guest-devices.so", "liba10vm-binder-devices.so", "liba10vm-guest-log.so", "libandroid_runtime.so",
            "libutils.so", "libbinder.so", "libhwbinder.so", "libhidlbase.so"))}
    if args and args[0] == "--uid":
        environment["A10VM_GUEST_UID"] = environment["A10VM_GUEST_GID"] = str(int(args[1]))
        args = args[2:]
    environment["A10VM_BOOT_JNI"] = ":".join(manifest.get("romBoot", {}).get("bootJni", []))
    if args and args[0] == "--install":
        source = Path(args[1]).resolve()
        target = state + "/guest-imports/test.apk"
        device(run_as + "mkdir -p " + shlex.quote(state + "/guest-imports"))
        if SERIAL:
            staging = "/data/local/tmp/a10vm-guest-import-" + str(os.getpid()) + ".apk"
            try:
                subprocess.run(["adb", "-s", SERIAL, "push", str(source), staging],
                               env=ENV, check=True, timeout=40)
                device(run_as + "cp " + shlex.quote(staging) + " " + shlex.quote(target))
            finally:
                device("rm -f " + shlex.quote(staging))
        else:
            with source.open("rb") as stream:
                subprocess.run(device_argv(run_as + "/system/bin/sh -c " + shlex.quote(
                    "cat > " + shlex.quote(target))), env=ENV, stdin=stream, check=True, timeout=40)
        environment["A10VM_COMMAND_INPUT"] = target
        args = ["package", "install", "-r", "-t", "--user", "0", "-S", str(source.stat().st_size)]
    main_class = "io.a10vm.guest.GuestCommand"
    if args and args[0] == "--main":
        main_class, args = args[1], args[2:]
        if not main_class.startswith("io.a10vm.guest."):
            raise ValueError("Expected guest runtime main class")
    if args and args[0] == "--native":
        item, guest_path = native_input(args[1], manifest)
        if guest_path:
            environment["A10VM_EXEC_ARGV0"] = guest_path
        guest = [names["ld-android.so"], names[item["logical"]], *args[2:]]
    else:
        guest = [names["ld-android.so"], names["app_process64"], "-Xnoimage-dex2oat",
                 "-Djava.library.path=" + directory + "/lib", "/system/bin", main_class, *args]
    # Android installation paths contain '='; env treats those executables as assignments.
    script = "export " + shlex.join([key + "=" + value for key, value in environment.items()])
    log = directory + "/framework-command-" + str(os.getpid()) + ".log"
    script += "\nexec " + shlex.join(guest) + " > " + shlex.quote(log) + " 2>&1"
    if SERIAL:
        command = device_argv(run_as + "/system/bin/sh -c " + shlex.quote(script))
    else:
        identity = device(run_as + "cat files/guest-runtime/framework-server.log")
        uid_match = re.search(r"^desktop_uid=(\d+)$", identity, re.M)
        context_match = re.search(r"^desktop_selinux=(u:r:untrusted_app[^\n]+)$", identity, re.M)
        if uid_match and context_match:
            uid, context = uid_match.group(1), context_match.group(1)
        else:
            # A startup failure can precede the guest identity marker; use the live app domain.
            pid = device("/system/bin/pidof " + PACKAGE).split()[0]
            status = device("/system/bin/cat /proc/" + pid + "/status")
            uid = re.search(r"^Uid:\s+(\d+)", status, re.M).group(1)
            context = device("/system/bin/cat /proc/" + pid + "/attr/current").split("\0", 1)[0].strip()
            if int(uid) < 10000 or not context.startswith("u:r:untrusted_app"):
                raise ValueError("Expected the installed app's ordinary UID and domain")
        # Local root automation retains the production app domain for /proc thread checks.
        command = ["su", "-g", uid, "-G", "3003", "-Z", context, uid, "-c", script]
    result = subprocess.run(command, env=ENV, capture_output=True, timeout=140)
    print(device(run_as + "/system/bin/cat " + shlex.quote(log)))
    if result.stderr:
        print(result.stderr.decode(errors="replace"), file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
