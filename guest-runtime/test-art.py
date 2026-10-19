#!/usr/bin/env python3
"""Run and verify packaged Android 10 ART under the ordinary Termux UID."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/container/art"


def verified(log, runtime, nonce):
    values = dict(re.findall(r"^(art_\w+)=(.*)$", log, re.M))
    mappings = set(re.findall(r"^ART_MAP\t(.*)$", log, re.M))
    allowed = {str(runtime.native(name)) for name in runtime.names}
    required = {str(runtime.native(name)) for name in ("ld-android.so", "dalvikvm64", "libart.so", "libc.so", "libjavacore.so")}
    return (values.get("art_uid") == str(os.getuid()) and values.get("art_euid") == str(os.getuid())
            and values.get("art_nonce") == nonce and values.get("art_cap_eff") == "0000000000000000"
            and re.fullmatch(r"u:r:untrusted_app(?:_\d+)?:s0(?::.*)?", values.get("art_selinux", "")) is not None
            and all(values.get(name) == "1" for name in (
                "art_thread", "art_file_roundtrip", "art_directory_roundtrip", "art_runtime_ready"))
            and required <= mappings <= allowed)


def main():
    assert os.getuid() >= 10000, "Run as an ordinary app UID"
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "uid": os.getuid(), "apkRunVerified": False, "desktopVerified": False}
    with tempfile.TemporaryDirectory(prefix="art-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary)
        environment = dict(runtime.environment, LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
        started = time.monotonic()
        result = subprocess.run(runtime.art_command("a10vm-art-local"), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        log = result.stdout.decode("utf-8", errors="replace")
        (OUT / "art-local.log").write_text(log, encoding="utf-8")
        report.update(exitCode=result.returncode, elapsedMs=round((time.monotonic() - started) * 1000, 2))
        negative = {
            "wrongUid": log.replace("art_uid=" + str(os.getuid()), "art_uid=0"),
            "wrongEuid": log.replace("art_euid=" + str(os.getuid()), "art_euid=0"),
            "capabilities": log.replace("art_cap_eff=0000000000000000", "art_cap_eff=0000000000000001"),
            "hostLibc": log.replace("ART_MAP\t" + str(runtime.native("libc.so")), "ART_MAP\t/system/lib64/libc.so"),
            "missingArt": log.replace("ART_MAP\t" + str(runtime.native("libart.so")), "MISSING_ART"),
        }
        report["validatorNegatives"] = {name: candidate != log and not verified(candidate, runtime, "a10vm-art-local")
                                       for name, candidate in negative.items()}
        file = runtime.rootfs / "data/local/tmp/runtime-check.txt"
        report["fileRoundTrip"] = file.is_file() and file.read_text() == "a10vm-art-local"
        report["executableMappings"] = len(set(re.findall(r"^ART_MAP\t(.*)$", log, re.M)))
        report["passed"] = (result.returncode == 0 and verified(log, runtime, "a10vm-art-local")
                             and report["fileRoundTrip"] and all(report["validatorNegatives"].values()))
    report["logSha256"] = hashlib.sha256(log.encode()).hexdigest()
    (OUT / "art-local-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        print(log[-10000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
