#!/usr/bin/env python3
"""Check guest maps and optionally run the supplied loader's ART locator unchanged."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance


def main():
    assert os.getuid() >= 10000, "Run using the ordinary Termux UID"
    out = ROOT / "artifacts/xclone-hook"
    out.mkdir(exist_ok=True)
    native = {"proc-maps-check": ROOT / "artifacts/container/runtime/bin/proc-maps-check"}
    initialize = "--initialize" in sys.argv
    report = {"ordinaryUid": os.getuid()}
    if len(sys.argv) > 1:
        sample = Path(sys.argv[1]).resolve()
        symbols = subprocess.check_output(["readelf", "-Ws", str(sample)], text=True)
        match = re.search(r"\s\d+:\s+([0-9a-f]+)\s+\d+\s+FUNC\s+LOCAL\s+DEFAULT\s+\d+\s+_ZL13locate_libartv$",
                          symbols, re.M)
        assert match, "The supplied loader has no locate_libart symbol"
        native["libloader.so"] = sample
        report.update(sampleSha256=hashlib.sha256(sample.read_bytes()).hexdigest(),
                      locatorSymbol="_ZL13locate_libartv", locatorValue=match[1])
    with tempfile.TemporaryDirectory(prefix="maps-", dir=out) as temporary:
        runtime = RuntimeInstance(temporary, native)
        command = [str(runtime.native("ld-android.so")), str(runtime.native("proc-maps-check"))]
        if "libloader.so" in native:
            command += [str(runtime.native("libloader.so")), report["locatorValue"]]
        result = subprocess.run(command, env=runtime.environment, capture_output=True, text=True, timeout=20)
        output = result.stdout + result.stderr
        checks = dict(re.findall(r"^((?:maps_|lsplant_)[a-z_]+)=([01])$", output, re.M))
        report.update(passed=result.returncode == 0 and checks and all(v == "1" for v in checks.values()),
                      exitCode=result.returncode, checks=checks)
        (out / "proc-maps.log").write_text(output, encoding="utf-8")
        (out / "proc-maps-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(output, end="")
        print(json.dumps(report))
        if initialize:
            assert "libloader.so" in native
            dex = runtime.directory / "hook-init.dex"
            shutil.copyfile(out / "test-dex/dex/classes.dex", dex)
            environment = dict(runtime.environment, LD_PRELOAD=str(runtime.native("liba10vm-guest-log.so")))
            result = subprocess.run([str(runtime.native("ld-android.so")), str(runtime.native("dalvikvm64")),
                    "-Xnoimage-dex2oat", "-Djava.library.path=" + str(runtime.libraries),
                    "-Xbootclasspath:/apex/com.android.runtime/javalib/core-oj.jar:/apex/com.android.runtime/javalib/core-libart.jar",
                    "-cp", str(dex), "com.hooker.lsplant.HookMain", str(runtime.native("libloader.so"))], env=environment,
                    capture_output=True, text=True, timeout=20)
            output = result.stdout + result.stderr
            print(output, end="")
            required = {"lsplant_native_capture", "lsplant_initialized", "lsplant_method_hooked",
                        "lsplant_backup_callable", "lsplant_method_restored"}
            checks = dict(re.findall(r"^(lsplant_[a-z_]+)=([01])$", output, re.M))
            report = {"passed": result.returncode == 0 and required <= checks.keys()
                                and all(v == "1" for v in checks.values()),
                      "exitCode": result.returncode, "ordinaryUid": os.getuid(), "checks": checks}
            print(json.dumps(report))
            (out / "hook-init.log").write_text(output, encoding="utf-8")
            (out / "hook-init-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
