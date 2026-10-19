#!/usr/bin/env python3
"""Build a minimal split APK for installed-app import and real IME verification."""
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts/keyboard-fixture"
ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


def main():
    sdk = Path.home() / "Android/Sdk"
    android = sdk / "platforms/android-35/android.jar"
    source = ROOT / "tools/fixtures/keyboard"
    classes, dex = OUT / "classes", OUT / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(parents=True, exist_ok=True)

    def run(*args):
        subprocess.run(args, env=ENV, check=True, capture_output=True)

    run("javac", "--release", "8", "-cp", str(android), "-d", str(classes), str(source / "EditorActivity.java"))
    run("bash", str(sdk / "build-tools/35.0.0/d8"), "--min-api", "28", "--lib", str(android),
        "--output", str(dex), *map(str, classes.rglob("*.class")))
    for name, manifest in (("base", "AndroidManifest.xml"), ("split", "SplitManifest.xml")):
        unsigned, aligned, signed = (OUT / (name + suffix) for suffix in ("-unsigned.apk", "-aligned.apk", ".apk"))
        run("aapt2", "link", "--manifest", str(source / manifest), "-I", str(android), "-o", str(unsigned))
        if name == "base":
            with zipfile.ZipFile(unsigned, "a") as archive:
                archive.write(dex / "classes.dex", "classes.dex")
        run("zipalign", "-f", "4", str(unsigned), str(aligned))
        keystore = Path.home() / ".config/.android/debug.keystore"
        if not keystore.is_file():
            keystore = Path.home() / ".android/debug.keystore"
        run("apksigner", "sign", "--ks", str(keystore), "--ks-pass", "pass:android", "--out", str(signed), str(aligned))
        print(signed)


if __name__ == "__main__":
    main()
