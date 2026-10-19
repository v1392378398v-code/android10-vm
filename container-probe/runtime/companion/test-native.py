#!/usr/bin/env python3
"""Validate the complete private companion stack and its observable C++/math contracts."""
import json
import pathlib
import re
import subprocess
import tempfile
from collections import Counter

root = pathlib.Path(__file__).resolve().parents[3]
runtime = root / "artifacts/container/runtime"
output = runtime / "companion"
program = runtime / "bin/companion-probe"
linker = runtime / "bin/source-linker64"
late = runtime / "lib/liba10vm-late-test.so"
libraries = {name: runtime / "lib" / name for name in (
    "libc.so", "libdl.so", "libm.so", "libunwind.so", "libc++.so", "liba10vm-exceptions.so")}
allowed = {str(path.resolve()) for path in (program, linker, *libraries.values())}
required = set((root / "container-probe/runtime/companion/checks.txt").read_text().splitlines())
elfs = []
for path in (program, late, *libraries.values()):
    elf = subprocess.check_output(["llvm-readelf", "-hlWd", str(path)], text=True)
    assert "AArch64" in elf and "DYN" in elf, path
    assert "RUNPATH" not in elf and "RPATH" not in elf, path
    needed = set(re.findall(r"Shared library: \[(.*?)\]", elf))
    assert needed <= set(libraries) | {"ld-android.so"}, (path, needed)
    assert ".eh_frame_hdr" in subprocess.check_output(["llvm-readelf", "-SW", str(path)], text=True), path
    elfs.append({"name": path.name, "needed": sorted(needed)})
exports = subprocess.check_output(["llvm-nm", "-D", "--defined-only", str(libraries["libm.so"])], text=True)
for symbol in ("sin", "sinf", "sqrt", "log", "powl", "nextafterl", "csqrtl", "fesetround"):
    assert re.search(r"\b" + symbol + r"(?:@@?\w+)?$", exports, re.M), symbol

with tempfile.TemporaryDirectory(prefix="companion-", dir=output) as temporary:
    directory = pathlib.Path(temporary)
    seed = directory / "instance"
    environment = {"PATH": "/system/bin", "TMPDIR": str(directory)}
    seeded = subprocess.run([
        str(root / "artifacts/container/properties/bin/property-probe"), "run", str(seed),
        "companion-seed", "/system/bin/linker64",
    ], env=environment, capture_output=True, text=True, timeout=15)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr

    def configuration(name, missing=None):
        location = directory / name
        location.mkdir()
        for library_name, path in libraries.items():
            if library_name != missing:
                (location / library_name).symlink_to(path)
        config = location / "ld.config.txt"
        config.write_text(f"dir.probe = {program.parent}\n[probe]\n"
                          "namespace.default.isolated = true\n"
                          f"namespace.default.search.paths = {location}\n"
                          f"namespace.default.permitted.paths = {runtime}\n", encoding="utf-8")
        return config

    complete = configuration("complete")

    def run(label, mode, config):
        result = subprocess.run([str(linker), str(program), mode, "companion-local", str(late)],
                                env=dict(environment, A10VM_PROPERTIES=str(seed), A10VM_LD_CONFIG=str(config)),
                                capture_output=True, text=True, timeout=15)
        text = result.stdout + result.stderr
        (output / f"local-{label}.log").write_text(text, encoding="utf-8")
        return result, text

    cases = []
    for round_number in range(2):
        result, text = run(f"normal-{round_number}", "normal", complete)
        assert result.returncode == 0, (result.returncode, text)
        checks = {line.split("\t")[1] for line in text.splitlines()
                  if line.startswith("CHECK\t") and line.endswith("\t1")}
        assert checks == required and "\t0\n" not in text, (required - checks, text)
        for marker in ("main_sdk=29\n", "math_long_double_bits=113\n",
                       "cxx_workers=4\ncxx_tls_destructors=4\n", "exception_late_rounds=2\n",
                       "companion_complete=1\ncompanion_fini_complete=1\n"):
            assert marker in text, (marker, text)
        assert text.count("late_module_fini=1\n") == 2, text
        for key, library in (("source_libc", "libc.so"), ("source_libm", "libm.so"),
                             ("source_cxx", "libc++.so"), ("source_unwind", "libunwind.so")):
            path = re.search(r"^" + key + r"=(.+)$", text, re.M).group(1)
            assert pathlib.Path(path).resolve() == libraries[library].resolve(), (key, path)
        maps = [line[4:].split(None, 5) for line in text.splitlines() if line.startswith("MAP\t")]
        mapped_elfs = {str(pathlib.Path(entry[5]).resolve()) for entry in maps
                       if len(entry) == 6 and "x" in entry[1] and entry[5].startswith("/")}
        assert mapped_elfs == allowed, mapped_elfs
        other = [entry for entry in maps if len(entry) == 6 and entry[5].startswith("/")
                 and str(pathlib.Path(entry[5]).resolve()) not in allowed]
        assert len(other) == 6 and all(entry[1] == "r--s" and int(entry[2], 16) == 0 and
                                      pathlib.Path(entry[5]).resolve().parent == seed for entry in other), other
        assert Counter(pathlib.Path(entry[5]).name for entry in other) == {
            "property_info": 2, "properties_serial": 2, "a10vm_private_prop": 2}, other
        assert "/dev/__properties__" not in text
        cases.append({"passed": True, "checks": len(checks), "executableMappings": sorted(mapped_elfs),
                      "readonlyPropertyMaps": len(other)})
    termination = []
    for mode in ("uncaught", "noexcept"):
        result, text = run(mode, mode, complete)
        assert result.returncode == 86 and "terminate_handler_called=1\n" in text, (mode, text)
        assert "companion_complete=" not in text
        termination.append({"mode": mode, "passed": True, "exitCode": result.returncode})
    rejected = []
    for missing in ("libm.so", "libc++.so", "libunwind.so"):
        result, text = run("missing-" + missing, "normal", configuration("missing-" + missing, missing))
        assert result.returncode != 0 and missing in text and "not found" in text, (missing, text)
        assert "companion_mode=" not in text
        rejected.append({"missing": missing, "passed": True, "exitCode": result.returncode})

(output / "local-report.json").write_text(json.dumps({
    "passed": True, "gate": "P2-source-companion-runtime", "completeG1": False,
    "librariesFromSource": True, "aarch64LlvmUnwindAdaptation": True,
    "binary128SincoslCorrection": True,
    "elfs": elfs, "runs": cases, "termination": termination, "rejected": rejected,
}, indent=2) + "\n", encoding="utf-8")
print("Companion runtime: math/binary128/C++/cross-DSO unwinding passed twice; termination and missing libraries verified.")
