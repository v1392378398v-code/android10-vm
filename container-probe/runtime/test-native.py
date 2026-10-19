#!/usr/bin/env python3
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
output = root / "artifacts/container/runtime"
binary = output / "bin/bootstrap-probe"
seed_binary = root / "artifacts/container/properties/bin/property-probe"
common = {
    "bootstrap_init_order", "bootstrap_key_create", "bootstrap_thread_create",
    "bootstrap_thread_join", "bootstrap_tls_errno_isolation", "bootstrap_thread_destructors",
    "bootstrap_key_delete", "bootstrap_identity_files", "bootstrap_stdio_buffered",
}

elf = subprocess.check_output(["llvm-readelf", "-hlWd", str(binary)], text=True)
assert "AArch64" in elf and "EXEC" in elf
assert "INTERP" not in elf and "NEEDED" not in elf
tls = next(line.split() for line in elf.splitlines() if line.strip().startswith("TLS "))
assert int(tls[-1], 16) >= 64, tls
undefined = subprocess.check_output(["llvm-nm", "-u", str(binary)], text=True)
assert not any(" U " in line for line in undefined.splitlines()), undefined

cases = []
with tempfile.TemporaryDirectory(prefix="bootstrap-", dir=output) as temporary:
    directory = pathlib.Path(temporary)
    seed = directory / "instance"
    seeded = subprocess.run([str(seed_binary), "run", str(seed), "bootstrap-seed",
                             "/system/bin/linker64"], capture_output=True, text=True, timeout=10)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    incomplete = seed / "incomplete"
    incomplete.mkdir()
    shutil.copyfile(seed / "property_info", incomplete / "property_info")
    for mode in ("reader", "missing", "relative", "incomplete"):
        environment = dict(os.environ)
        for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "A10VM_PROPERTIES"):
            environment.pop(name, None)
        if mode == "reader":
            environment["A10VM_PROPERTIES"] = str(seed)
        elif mode == "relative":
            environment["A10VM_PROPERTIES"] = "relative"
        elif mode == "incomplete":
            environment["A10VM_PROPERTIES"] = str(incomplete)
        result = subprocess.run([str(binary), mode, "bootstrap-local"], env=environment,
                                capture_output=True, text=True, timeout=10)
        text = result.stdout
        (output / f"local-{mode}.log").write_text(text + result.stderr, encoding="utf-8")
        assert result.returncode == 0, (mode, result.returncode, text, result.stderr)
        checks = {line.split("\t")[1] for line in text.splitlines()
                  if line.startswith("CHECK\t") and line.endswith("\t1")}
        required = common | ({"bootstrap_preinit_sdk29", "bootstrap_constructor_sdk29",
                              "bootstrap_property_reinit_errno"} if mode == "reader" else
                             {"bootstrap_no_host_property_fallback", "bootstrap_uninitialized_wait"})
        assert required <= checks and "\t0\n" not in text, (mode, required - checks)
        assert "bootstrap_complete=1\nfini_complete=1\nstdio_flush_complete=1\n" in text
        assert "thread_rounds=2\nkey_destructors=2\ncpp_destructors=2\n" in text
        expected_sdk = "29" if mode == "reader" else ""
        for stage in ("preinit", "constructor", "main"):
            assert f"{stage}_sdk={expected_sdk}\n" in text
        maps = [line[4:].split(None, 5) for line in text.splitlines() if line.startswith("MAP\t")]
        executable_paths = {str(pathlib.Path(entry[5]).resolve()) for entry in maps
                            if len(entry) == 6 and "x" in entry[1] and entry[5].startswith("/")}
        assert executable_paths == {str(binary.resolve())}, executable_paths
        assert not any("/dev/__properties__" in line for line in text.splitlines())
        data_maps = [entry for entry in maps if len(entry) == 6 and entry[5].startswith("/")
                     and pathlib.Path(entry[5]).resolve() != binary.resolve()]
        if mode == "reader":
            property_maps = [entry for entry in maps if len(entry) == 6 and
                             pathlib.Path(entry[5]).resolve().parent == seed.resolve()]
            assert len(property_maps) == 3 and all(entry[1] == "r--s" for entry in property_maps)
            assert data_maps == property_maps, data_maps
        else:
            assert not data_maps, data_maps
        cases.append({"mode": mode, "passed": True, "checks": len(checks),
                      "elfMappings": sorted(executable_paths), "sdk": expected_sdk,
                      "threadRounds": 2, "exitFlushVerified": True})

(output / "local-report.json").write_text(json.dumps({
    "passed": True, "staticBionicBootstrap": True, "noInterpreter": True,
    "noNeededLibraries": True, "strongUndefinedSymbols": 0,
    "dynamicRuntimeIntegrated": False, "cases": cases,
}, indent=2) + "\n", encoding="utf-8")
print("Static Bionic bootstrap: four cases passed; real TLS/pthread/exit; no host ELF mappings.")
