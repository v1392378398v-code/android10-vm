#!/usr/bin/env python3
"""Verify ROM credential changes stay in the guest while the host has zero caps."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts/container/rom-services"
RUNTIME = ROOT / "artifacts/container/runtime"

if os.getuid() < 10000:
    raise SystemExit("Run under the ordinary Termux UID")
with tempfile.TemporaryDirectory(prefix="check-", dir=OUT) as temporary:
    directory = Path(temporary)
    (directory / "rootfs").mkdir()
    config = directory / "ld.config.txt"
    config.write_text(f"dir.guest = {OUT}\n[guest]\nnamespace.default.isolated = true\n"
                      f"namespace.default.search.paths = {RUNTIME / 'lib'}\n"
                      f"namespace.default.permitted.paths = {ROOT / 'artifacts/container'}\n", encoding="utf-8")
    env = {"PATH": "/system/bin", "TMPDIR": str(directory), "A10VM_ROOTFS": str(directory / "rootfs"),
           "A10VM_HOST_ROOT": str(ROOT / "artifacts/container"),
           "A10VM_GUEST_UID": "0", "A10VM_GUEST_GID": "0", "A10VM_LD_CONFIG": str(config),
           "LD_PRELOAD": str(OUT / "liba10vm-rom-service-identity.so")}
    result = subprocess.run([RUNTIME / "bin/source-linker64", OUT / "identity-check"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
    report = {"passed": result.returncode == 0 and "rom_service_identity_ready=1\n" in result.stdout,
              "uid": os.getuid(), "exitCode": result.returncode, "evidence": result.stdout}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
