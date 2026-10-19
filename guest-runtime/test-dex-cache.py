#!/usr/bin/env python3
"""Exercise the real Android 10 ZIP DEX loader and persistent cache as an ordinary UID."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/container/dex-cache"


def main():
    assert os.getuid() >= 10000
    report = {"passed": False, "uid": os.getuid(), "cases": []}
    with tempfile.TemporaryDirectory(prefix="check-", dir=OUT) as temporary:
        library = ROOT / "artifacts/container/art/lib/libdexfile.so" if "--stock" in sys.argv else OUT / "lib/libdexfile.so"
        runtime = RuntimeInstance(temporary, {"libdexfile.so": library,
            "liba10vm-dex-cache-check.so": OUT / "bin/dex-cache-check"})
        cache = runtime.directory / "code_cache/a10vm-dex-v1"
        env = dict(runtime.environment, A10VM_DEX_CACHE=str(cache),
            LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
        dex = (runtime.directory / "framework-check.dex").read_bytes()
        archive = runtime.directory / "input.apk"

        def write_archive(compression=zipfile.ZIP_DEFLATED, payload=dex):
            with zipfile.ZipFile(archive, "w", compression=compression) as bundle:
                for name in ("classes.dex", "classes2.dex"):
                    bundle.writestr(name, payload)

        def load(name, hit=False, verify=True, ok=True, location=None):
            command = [str(runtime.native("ld-android.so")),
                str(runtime.native("liba10vm-dex-cache-check.so")), str(archive),
                "--verify" if verify else "--skip-verify"]
            if location:
                command.append(location)
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
            log = result.stdout + result.stderr
            (OUT / (name + ".log")).write_text(log, encoding="utf-8")
            if ok:
                assert result.returncode == 0, log[-3000:]
                assert "dex_count=2\n" in log, log
                rows = re.findall(r"dex_bytes=(\d+):(\d+) location=(.+?) checksum=(\d+) readonly=(\d+)", log)
                assert len(rows) == 2 and all(int(n) == len(dex) and int(crc) == zlib.crc32(dex)
                    and int(checksum) == zlib.crc32(dex) and readonly == "1"
                    for n, crc, _, checksum, readonly in rows), log
                mappings = int(re.search(r"dex_cache_mappings=(\d+)", log).group(1))
                assert (mappings >= 2) if hit else mappings == 0, log
                if location:
                    assert rows[0][2] == location and rows[1][2] == location + "!classes2.dex", log
            else:
                assert result.returncode != 0 and "dex_load_error=" in log, log
            report["cases"].append(name)

        try:
            write_archive()
            load("compressed-miss")
            assert len(list(cache.glob("*.adex"))) == 2, "Verified DEX cache was not published"
            load("compressed-hit", hit=True)
            load("fd-alias-hit", hit=True, location="/alias/not-the-source.apk")
            for path in cache.glob("*.adex"):
                with path.open("r+b") as stream:
                    stream.seek(-1, 2)
                    byte = stream.read(1)
                    stream.seek(-1, 2)
                    stream.write(bytes([byte[0] ^ 0xff]))
            load("corrupt-cache-fallback")
            load("repaired-cache-hit", hit=True)
            for path in cache.glob("*.adex"):
                path.write_bytes(b"truncated")
            load("truncated-cache-fallback")
            load("truncated-repaired-hit", hit=True)
            write_archive()
            load("apk-update-miss")
            load("apk-update-hit", hit=True)
            for path in cache.glob("*.adex"):
                path.unlink()
            load("unchecked-not-published", verify=False)
            assert not list(cache.glob("*.adex")), "Unchecked DEX was cached"
            damaged = bytearray(dex)
            damaged[-1] ^= 0xff
            write_archive(payload=damaged)
            load("invalid-dex-rejected", ok=False)
            assert not list(cache.glob("*.adex")), "Invalid DEX was cached"
            write_archive(zipfile.ZIP_STORED)
            load("stored-miss")
            load("stored-hit", hit=True)
            for path in cache.glob("*.adex"):
                path.unlink()
            cache.rmdir()
            cache.write_bytes(b"cache directory unavailable")
            write_archive()
            load("unavailable-cache-fallback")
            report["passed"] = True
        except (AssertionError, OSError, subprocess.SubprocessError) as error:
            report["error"] = str(error)
    (OUT / "test-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
