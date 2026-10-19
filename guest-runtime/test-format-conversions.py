#!/usr/bin/env python3
"""Check actual guest YUV conversion bytes with guard pages at buffer boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance

OUT = ROOT / "artifacts/container/graphics/desktop"


def main():
    assert os.getuid() >= 10000
    with tempfile.TemporaryDirectory(prefix="format-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary, {
            "libOpenglSystemCommon.so": OUT / "lib/libOpenglSystemCommon.so",
            "format-conversions-check": OUT / "bin/format-conversions-check",
        })
        result = subprocess.run([runtime.native("ld-android.so"), runtime.native("format-conversions-check")],
                                env=runtime.environment, capture_output=True, text=True, timeout=10)
        log = result.stdout + result.stderr
        (OUT / "format-conversions.log").write_text(log, encoding="utf-8")
        cases = log.count("format_conversion_case=")
        passed = result.returncode == 0 and cases == 18 and "desktop_format_conversions=1\n" in log
        report = {"passed": passed, "uid": os.getuid(), "rootRequired": False,
                  "exitCode": result.returncode, "cases": cases, "guardPages": True}
        (OUT / "format-conversions-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(log, end="")
        print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
