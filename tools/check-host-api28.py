#!/usr/bin/env python3
"""Check strong host ELF imports against the public Android 9 NDK stubs."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


def output(*args):
    return subprocess.check_output(args, env=ENV, text=True)


def symbols(path, imported):
    entries = []
    for line in output("readelf", "--dyn-syms", "--wide", str(path)).splitlines():
        fields = line.split()
        if len(fields) < 8 or not fields[0].endswith(":"):
            continue
        if (fields[6] == "UND") == imported and (not imported or fields[4] != "WEAK"):
            entries.append(fields[7].split("@")[0])
    return set(entries)


def main():
    ndk = Path(os.environ.get("ANDROID_NDK_HOME", Path.home() / "Android/Sdk/ndk/29.0.13113456"))
    stubs = ndk / "toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/28"
    report = {"passed": True, "hostMinSdk": 28, "files": []}
    for path in (ROOT / "native-display/build/prepared/jniLibs/arm64-v8a/liba10vm-desktop-window.so",
                 ROOT / "artifacts/container/graphics/bin/codec-client"):
        needed = re.findall(r"\(NEEDED\).*\[(.+)\]", output("readelf", "-d", str(path)))
        available = set().union(*(symbols(stubs / library, False) for library in needed))
        missing = sorted(symbols(path, True) - available)
        note = output("readelf", "-n", str(path))
        api28 = "description data: 1c 00 00 00" in note
        passed = api28 and not missing
        report["files"].append({"path": str(path.relative_to(ROOT)), "androidNote28": api28,
                                "strongImports": len(symbols(path, True)), "missing": missing, "passed": passed})
        report["passed"] &= passed
    target = ROOT / "artifacts/device-compat/host-api28-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
