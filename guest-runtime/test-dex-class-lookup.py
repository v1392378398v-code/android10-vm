#!/usr/bin/env python3
"""Check unsorted class definitions, concurrent reads and writes against linear lookup."""
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/container/dex-cache"


def fixture(types, classes):
    # Lookup only reads type indices. Keep class definitions in deliberately unsorted order.
    type_offset = 112
    class_offset = type_offset + types * 4
    data = bytearray(class_offset + classes * 32)
    data[:8] = b"dex\n035\0"
    struct.pack_into("<III", data, 32, len(data), 112, 0x12345678)
    struct.pack_into("<II", data, 64, types, type_offset)
    struct.pack_into("<II", data, 96, classes, class_offset)
    for i in range(classes):
        struct.pack_into("<I", data, class_offset + i * 32, ((i * 7919) % classes) * 2)
    if types == 65535:
        struct.pack_into("<I", data, class_offset, 65534)
    return data


def main():
    report = {"passed": False, "uid": os.getuid(), "cases": []}
    with tempfile.TemporaryDirectory(prefix="lookup-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary, {
            "libdexfile.so": OUT / "lib/libdexfile.so",
            "liba10vm-dex-class-lookup-check.so": OUT / "bin/dex-class-lookup-check"})
        environment = dict(runtime.environment, LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
        try:
            for label, types, classes in (("large-unsorted", 8192, 4096), ("small", 32, 16),
                                         ("empty", 8, 0), ("max-index", 65535, 64)):
                archive = runtime.directory / "lookup.apk"
                with zipfile.ZipFile(archive, "w") as bundle:
                    bundle.writestr("classes.dex", fixture(types, classes))
                result = subprocess.run([runtime.native("ld-android.so"),
                    runtime.native("liba10vm-dex-class-lookup-check.so"), archive],
                    env=environment, capture_output=True, text=True, timeout=20)
                text = result.stdout + result.stderr
                row = {"case": label, "exitCode": result.returncode,
                       **{key: int(value) for key, value in re.findall(r"(linear_ns|indexed_ns)=(\d+)", text)}}
                report["cases"].append(row)
                assert result.returncode == 0 and "lookup_correctness_concurrency_mutation=1" in text, text[-2500:]
            report["passed"] = True
        except (AssertionError, subprocess.SubprocessError) as failure:
            report["error"] = str(failure)
    (OUT / "class-lookup-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
