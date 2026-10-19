#!/usr/bin/env python3
"""Replay QQ's unmodified native GIF decoder in both linker environments."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from guest_runtime_fixture import RuntimeInstance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "guest-runtime"))
from test_framework_support import wait_marker
ENV = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
SHIMS = ("liba10vm-property-client.so", "liba10vm-hal-modules.so", "liba10vm-guest-devices.so",
         "liba10vm-binder-devices.so", "liba10vm-guest-log.so")


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    out = ROOT / "artifacts/clear-data/qq-gif"
    for name in ("classes", "dex"):
        (out / name).mkdir(parents=True, exist_ok=True)
    sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk")))
    android = sdk / "platforms/android-35/android.jar"
    sources = [ROOT / "tools/fixtures/qq-gif/DecodeMain.java",
               ROOT / "tools/fixtures/clear-data/GifInfoHandle.java"]
    subprocess.run(["javac", "--release", "8", "-cp", str(android), "-d", str(out / "classes"),
                    *map(str, sources)], env=ENV, check=True)
    subprocess.run(["bash", str(sdk / "build-tools/35.0.0/d8"), "--min-api", "29", "--lib", str(android),
                    "--output", str(out / "dex"), *map(str, (out / "classes").rglob("*.class"))],
                   env=ENV, check=True)
    report = {"passed": False, "rootRequired": False, "uid": os.getuid()}
    with tempfile.TemporaryDirectory(prefix="gif-", dir=ROOT / "artifacts") as temporary:
        runtime = RuntimeInstance(temporary)
        shutil.copyfile(out / "dex/classes.dex", runtime.directory / "gif.dex")
        library = ROOT / "artifacts/app-compat/qq-native/libgiflibra.so"
        (runtime.libraries / "libgiflibra.so").symlink_to(library)
        environment = runtime.framework_environment()
        environment.update(CLASSPATH=str(runtime.directory / "gif.dex"), A10VM_GUEST_UID="2000",
                           A10VM_GUEST_GID="2000")
        broker_log = out / "broker.log"
        with broker_log.open("w", encoding="utf-8") as stream:
            broker = subprocess.Popen([str(runtime.native("ld-android.so")), str(runtime.native("binder-broker")),
                str(runtime.directory / "binder.sock")], env=runtime.registry_environment(),
                stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_marker(broker, broker_log, "binder_broker_ready=1", 3)
                for variant in ("inherited", "shims"):
                    child_environment = dict(environment)
                    if variant == "shims":
                        child_environment["LD_PRELOAD"] = ":".join(
                            path for path in environment["LD_PRELOAD"].split(":") if path.endswith(SHIMS))
                    started = time.monotonic()
                    result = subprocess.run([str(runtime.native("ld-android.so")), str(runtime.native("app_process64")),
                        "-Xnoimage-dex2oat", "-Djava.library.path=" + str(runtime.libraries), "/system/bin",
                        "io.a10vm.fixture.gif.DecodeMain"], env=child_environment, capture_output=True, timeout=12)
                    log = (result.stdout + result.stderr).decode(errors="replace")
                    (out / (variant + ".log")).write_text(log, encoding="utf-8")
                    report[variant] = {"exitCode": result.returncode, "complete": "gif_decode_complete=1\n" in log,
                                       "elapsedSeconds": round(time.monotonic() - started, 3)}
                    print(json.dumps({variant: report[variant]}), flush=True)
            finally:
                broker.terminate()
                broker.wait(timeout=3)
        report["passed"] = report["shims"]["complete"] and report["shims"]["exitCode"] == 0
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
