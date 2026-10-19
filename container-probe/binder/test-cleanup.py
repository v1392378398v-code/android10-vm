#!/usr/bin/env python3
"""Check broker cleanup with the private Android 10 linker and allocator."""
from pathlib import Path
import argparse
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "artifacts/container/runtime"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reclaim-benchmark", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="broker-cleanup-", dir=RUNTIME / "binder") as temporary:
        directory = Path(temporary)
        config = directory / "ld.config.txt"
        config.write_text(f"dir.test = {RUNTIME / 'bin'}\n[test]\n"
                          "namespace.default.isolated = true\n"
                          f"namespace.default.search.paths = {RUNTIME / 'lib'}\n"
                          f"namespace.default.permitted.paths = {RUNTIME}\n", encoding="utf-8")
        env = {"PATH": "/system/bin", "TMPDIR": temporary, "A10VM_LD_CONFIG": str(config)}
        output = []
        programs = ("broker-cleanup-test", "broker-dispatch-test")
        if args.reclaim_benchmark:
            programs += ("broker-reclaim-benchmark",)
        for name in programs:
            result = subprocess.run([str(RUNTIME / "bin/source-linker64"), str(RUNTIME / "bin" / name)],
                                    env=env, capture_output=True, text=True, timeout=10)
            text = result.stdout + result.stderr
            output.append(text)
            print(text, end="")
            assert result.returncode == 0 and "\t0\n" not in text, (name, result.returncode, text)
        (RUNTIME / "binder/cleanup-check.log").write_text("".join(output), encoding="utf-8")


if __name__ == "__main__":
    main()
