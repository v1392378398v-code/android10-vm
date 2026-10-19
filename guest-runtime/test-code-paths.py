#!/usr/bin/env python3
"""Exercise delivered ApplicationInfo paths with an unmediated native openat."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker


def main():
    assert os.getuid() >= 10000, "Run using the ordinary Termux UID"
    out = ROOT / "artifacts/xclone-hook"
    stem = "code-paths-before" if "--baseline" in sys.argv else "code-paths"
    with tempfile.TemporaryDirectory(prefix="code-paths-", dir=out) as temporary:
        native = {name: ROOT / "artifacts/container/runtime/bin" / name
                  for name in ("raw-apk-check", "apk-namespace-check")}
        runtime = RuntimeInstance(temporary, native)
        shutil.copyfile(ROOT / "artifacts/container/framework/dex/classes.dex",
                        runtime.directory / "framework-check.dex")
        environment = runtime.framework_environment()
        environment.update(A10VM_HWBINDER_PATH=str(runtime.directory / "binder.sock"),
            LD_PRELOAD=str(runtime.native("liba10vm-binder-devices.so")) + ":" +
                       str(runtime.native("liba10vm-guest-log.so")))
        command = [str(runtime.native("ld-android.so")), str(runtime.native("app_process64")),
                   "-Xnoimage-dex2oat", "-Djava.library.path=" + str(runtime.libraries),
                   "/system/bin", "io.a10vm.guest.ApplicationCodePathsCheck", str(runtime.native("raw-apk-check"))]
        broker_log = out / (stem + "-binder.log")
        with broker_log.open("w", encoding="utf-8") as stream:
            broker = subprocess.Popen([str(runtime.native("ld-android.so")),
                str(runtime.native("binder-broker")), str(runtime.directory / "binder.sock")],
                env=runtime.registry_environment(), stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_marker(broker, broker_log, "binder_broker_ready=1", 3)
                result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=20)
                output = result.stdout + result.stderr
            finally:
                broker.terminate()
                broker.wait(timeout=3)
        apk = runtime.rootfs / "data/app/namespace-check/base.apk"
        apk.parent.mkdir(parents=True)
        info = zipfile.ZipInfo("lib/arm64-v8a/liba10vm-namespace-test.so")
        padding = (-(30 + len(info.filename) + 4)) % 4096
        info.extra = struct.pack("<HH", 0xA10E, padding) + bytes(padding)
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(info, (ROOT / "artifacts/container/runtime/lib/liba10vm-namespace-test.so").read_bytes())
        namespace = subprocess.run([str(runtime.native("ld-android.so")),
            str(runtime.native("apk-namespace-check")), str(apk) + "!/" + info.filename],
            env=runtime.environment, capture_output=True, text=True, timeout=5)
        output += namespace.stdout + namespace.stderr
    report = {"passed": result.returncode == namespace.returncode == 0 and "code_paths_complete=1\n" in output
                      and "apk_namespace_contents=1\n" in output,
              "ordinaryUid": os.getuid(), "rootRequired": False, "exitCode": result.returncode,
              "namespaceExitCode": namespace.returncode,
              "directSvc": True}
    (out / (stem + ".log")).write_text(output, encoding="utf-8")
    (out / (stem + "-report.json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(output[-2200:])
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
