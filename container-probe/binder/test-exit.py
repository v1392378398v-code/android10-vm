#!/usr/bin/env python3
"""Reproduce a CLI's late Binder cleanup after the buffer store was initialized."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "artifacts/container/runtime"


def main():
    assert os.getuid() >= 10000
    with tempfile.TemporaryDirectory(prefix="binder-exit-", dir=os.environ.get("TMPDIR")) as directory:
        config = Path(directory) / "ld.config.txt"
        config.write_text(f"dir.probe = {RUNTIME}/bin\n[probe]\nnamespace.default.isolated = true\n"
                          f"namespace.default.search.paths = {RUNTIME}/lib\n"
                          f"namespace.default.permitted.paths = {RUNTIME}\n", encoding="utf-8")
        result = subprocess.run([str(RUNTIME / "bin/source-linker64"), str(RUNTIME / "bin/binder-probe"),
                                 "buffer-exit", directory + "/unused.sock"],
                                env={"PATH": "/system/bin", "A10VM_LD_CONFIG": str(config)},
                                capture_output=True, text=True, timeout=3)
        log = result.stdout + result.stderr
        (RUNTIME / "binder/exit.log").write_text(log, encoding="utf-8")
        print(log, end="")
        assert result.returncode == 0 and "binder_exit_buffers_alive=1\n" in log, result.returncode


if __name__ == "__main__":
    main()
