#!/usr/bin/env python3
"""Extract the Android 10 ART dependency closure from the audited image."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
IMAGE = ROOT / "artifacts/guest/android10-display-v4.raw"
REPORT = ROOT / "artifacts/container/gate-0-repeatable/report.json"
DEBUGFS = ROOT / ".tools/fs/data/data/com.termux/files/usr/bin/debugfs"
OUT = ROOT / "artifacts/container/art"
APEX = "/system/apex/com.android.runtime.debug"
SOURCE = ROOT / "artifacts/container/runtime"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def needed(path):
    output = subprocess.check_output(["readelf", "-d", str(path)], text=True)
    return re.findall(r"\(NEEDED\).*?\[(.*?)\]", output)


def extract(path, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    result = subprocess.run([str(DEBUGFS), "-R", f'dump {path} "{destination}"', str(IMAGE)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode or not destination.is_file() or not destination.stat().st_size:
        destination.unlink(missing_ok=True)
        return False
    return True


def main():
    report = json.loads(REPORT.read_text())
    assert report["inputsVerified"] and report["sourceUnchanged"] and report["declaredGuestSdk"] == 29
    assert digest(IMAGE) == report["sourceSha256"], "Guest image hash mismatch"
    libraries, rootfs = OUT / "lib", OUT / "rootfs"
    libraries.mkdir(parents=True, exist_ok=True)
    program = OUT / "bin/dalvikvm64"
    assert extract(APEX + "/bin/dalvikvm64", program)
    program.chmod(0o755)
    entries = [{"name": "dalvikvm64", "source": APEX + "/bin/dalvikvm64", "path": str(program.relative_to(ROOT))}]
    supplied = {name: SOURCE / ("bin/source-linker64" if name == "ld-android.so" else "lib/" + name)
                for name in ("ld-android.so", "libc.so", "libdl.so", "libm.so", "libunwind.so")}
    pending = needed(program) + ["libart.so", "libart-compiler.so", "libartpalette-system.so", "libjavacore.so",
                                 "libopenjdk.so", "libopenjdkjvm.so"]
    seen = set()
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.+-]+", name), name
        target = libraries / name
        if name in supplied:
            shutil.copyfile(supplied[name], target)
            source = str(supplied[name].relative_to(ROOT))
        else:
            directories = ("/system/lib64",) if name == "libc++.so" else (APEX + "/lib64", "/system/lib64")
            for directory in directories:
                source = directory + "/" + name
                if extract(source, target):
                    break
            else:
                raise RuntimeError("Missing ART dependency: " + name)
        seen.add(name)
        entries.append({"name": name, "source": source, "path": str(target.relative_to(ROOT))})
        pending.extend(needed(target))
    data = [APEX + "/javalib/" + name for name in ("core-oj.jar", "core-libart.jar")]
    data += [APEX + "/etc/icu/icudt63l.dat"]
    for source in data:
        target = rootfs / source.removeprefix("/")
        assert extract(source, target), source
        entries.append({"name": target.name, "source": source, "path": str(target.relative_to(ROOT))})
    for entry in entries:
        path = ROOT / entry["path"]
        entry.update(sha256=digest(path), bytes=path.stat().st_size)
    manifest = {"guestSdk": 29, "sourceImageSha256": report["sourceSha256"], "files": entries}
    (OUT / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(entries), "bytes": sum(e["bytes"] for e in entries),
                      "manifest": str(OUT / "inputs.json")}, indent=2))


if __name__ == "__main__":
    main()
