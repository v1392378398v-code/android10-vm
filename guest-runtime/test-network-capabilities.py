#!/usr/bin/env python3
"""Check host VPN relay ownership without booting the desktop."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker


def main():
    out = ROOT / "artifacts/container/framework"
    with tempfile.TemporaryDirectory(prefix="net-caps-", dir=out) as temporary:
        runtime = RuntimeInstance(temporary)
        shutil.copyfile(out / "dex/classes.dex", runtime.directory / "framework-check.dex")
        log = out / "network-capabilities-broker.log"
        with log.open("w", encoding="utf-8") as stream:
            broker = subprocess.Popen([str(runtime.native("ld-android.so")), str(runtime.native("binder-broker")),
                    str(runtime.directory / "binder.sock")], env=runtime.registry_environment(),
                    stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_marker(broker, log, "binder_broker_ready=1", 3)
                result = subprocess.run([str(runtime.native("ld-android.so")), str(runtime.native("app_process64")),
                        "-Xnoimage-dex2oat", "/system/bin", "io.a10vm.guest.NetworkCheck", "--capabilities"],
                        env=runtime.framework_environment(), capture_output=True, text=True, timeout=15)
            finally:
                broker.terminate()
                broker.wait(timeout=3)
        text = result.stdout + result.stderr
        (out / "network-capabilities.log").write_text(text, encoding="utf-8")
        passed = result.returncode == 0 and "network_capabilities_complete=1\n" in text
        print("network_capabilities_passed=" + str(int(passed)) + " uid=" + str(os.getuid()))
        if not passed:
            print(text[-1400:])
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
