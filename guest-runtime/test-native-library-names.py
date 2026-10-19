#!/usr/bin/env python3
"""Exercise library enumeration and optional NPTH with the exact APK runtime inputs."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance


def main():
    out = ROOT / "artifacts/container/framework"
    with tempfile.TemporaryDirectory(prefix="library-names-", dir=out) as temporary:
        runtime = RuntimeInstance(temporary, {
            "library-names-check": ROOT / "artifacts/container/runtime/bin/library-names-check"})
        arguments = []
        if len(sys.argv) > 1:
            plugin = runtime.directory / "libnpth_dl.so"
            shutil.copyfile(sys.argv[1], plugin)
            arguments.append(str(plugin))
        # Also select the private linker section for executables extracted outside nativeLibraryDir.
        program = runtime.directory / "unpacked/library-names-check"
        program.parent.mkdir()
        shutil.copyfile(runtime.native("library-names-check"), program)
        result = subprocess.run([str(runtime.native("ld-android.so")), str(program), *arguments],
                env=runtime.environment, text=True, capture_output=True, timeout=20)
        output = result.stdout + result.stderr
        (out / "native-library-names.log").write_text(output, encoding="utf-8")
        passed = result.returncode == 0 and "native_library_names_complete=1\n" in output
        if arguments:
            passed &= "npth_art_load_complete=1\n" in output
            passed &= "interstellar_art_symbols_complete=1\n" in output
        print(output, end="")
        print(json.dumps({"passed": passed, "npthChecked": bool(arguments), "ordinaryUid": True}))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
