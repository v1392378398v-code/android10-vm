#!/usr/bin/env python3
"""Extract stock framework ABI and boot classpath without mounting the image."""
import json
import re
import shutil

from prepare import APEX, IMAGE, REPORT, ROOT, SOURCE, digest, extract, needed

OUT = ROOT / "artifacts/container/framework"


def main():
    report = json.loads(REPORT.read_text())
    assert report["inputsVerified"] and report["sourceUnchanged"] and report["declaredGuestSdk"] == 29
    assert digest(IMAGE) == report["sourceSha256"], "Guest image hash mismatch"
    entries = []

    def record(source, path, logical=None):
        entry = {"source": source, "path": str(path.relative_to(ROOT)),
                 "sha256": digest(path), "bytes": path.stat().st_size}
        if logical:
            entry["name"] = logical
        entries.append(entry)

    programs = []
    for name in ("app_process64", "servicemanager", "hwservicemanager"):
        path = OUT / "bin" / name
        assert extract("/system/bin/" + name, path)
        path.chmod(0o755)
        record("/system/bin/" + name, path, name)
        programs.append(path)
    supplied = {name: SOURCE / ("bin/source-linker64" if name == "ld-android.so" else "lib/" + name)
                for name in ("ld-android.so", "libc.so", "libdl.so", "libm.so", "libunwind.so")}
    supplied["liba10binder.so"] = SOURCE / "lib/liba10binder.so"
    supplied["liba10vm-binder-devices.so"] = OUT / "lib/liba10vm-binder-devices.so"
    supplied["liba10vm-manager-policy.so"] = OUT / "lib/liba10vm-manager-policy.so"
    supplied["liba10vm-property-client.so"] = OUT / "lib/liba10vm-property-client.so"
    supplied["liba10vm-guest-devices.so"] = OUT / "lib/liba10vm-guest-devices.so"
    supplied["liba10vm-guest-log.so"] = ROOT / "artifacts/container/art/lib/liba10vm-guest-log.so"
    public = OUT / "rootfs/system/etc/public.libraries.txt"
    assert extract("/system/etc/public.libraries.txt", public)
    public_names = [line.split()[0] for line in public.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    pending = [name for program in programs for name in needed(program)] + ["liba10vm-binder-devices.so", "liba10vm-manager-policy.so", "liba10vm-property-client.so", "liba10vm-guest-log.so", "liba10vm-guest-devices.so",
                                   "libjavacore.so", "libjavacrypto.so", "libopenjdk.so", "libopenjdkjvm.so"] + public_names
    seen = set()
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.+@-]+", name), name
        target = OUT / "lib" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name in supplied:
            source_path = supplied[name]
            if source_path != target:
                shutil.copyfile(source_path, target)
            source = str(source_path.relative_to(ROOT))
        else:
            directories = ("/system/lib64",) if name == "libc++.so" else (
                APEX + "/lib64", "/system/lib64", "/system/lib64/vndk-29",
                "/system/lib64/vndk-sp-29", "/system/apex/com.android.conscrypt/lib64")
            for directory in directories:
                source = directory + "/" + name
                if extract(source, target):
                    break
            else:
                raise RuntimeError("Missing framework dependency: " + name)
        seen.add(name)
        record(source, target, name)
        pending.extend(needed(target))

    environ = OUT / "rootfs/init.environ.rc"
    assert extract("/init.environ.rc", environ)
    boot = re.search(r"^\s+export BOOTCLASSPATH (.+)$", environ.read_text(), re.M).group(1).split(":")
    aliases = {"/apex/com.android.runtime": APEX,
               "/apex/com.android.conscrypt": "/system/apex/com.android.conscrypt",
               "/apex/com.android.media": "/system/apex/com.android.media"}
    data = list(boot) + [APEX + "/etc/icu/icudt63l.dat", "/system/etc/public.libraries.txt",
                         "/system/etc/preloaded-classes", "/system/etc/selinux/plat_service_contexts",
                         "/system/etc/selinux/plat_hwservice_contexts"]
    for guest in data:
        source = guest
        for alias, directory in aliases.items():
            if guest.startswith(alias + "/"):
                source = directory + guest[len(alias):]
                break
        target = OUT / "rootfs" / source.removeprefix("/")
        assert extract(source, target), source
        record(source, target)
    record(str((SOURCE / "bin/binder-broker").relative_to(ROOT)), SOURCE / "bin/binder-broker", "binder-broker")
    record(str((OUT / "bin/binder-registry").relative_to(ROOT)), OUT / "bin/binder-registry", "binder-registry")
    record(str((OUT / "bin/property-service").relative_to(ROOT)), OUT / "bin/property-service", "property-service")
    registry = {}
    stock = {entry["name"]: entry for entry in entries if "name" in entry}
    for name in ("libc.so", "libdl.so", "libm.so", "libc++.so", "libunwind.so", "ld-android.so",
                 "liblog.so", "libbase.so", "libcutils.so", "libutils.so", "libbinderthreadstate.so",
                 "liba10binder.so", "libbinder.so"):
        source = SOURCE / ("bin/source-linker64" if name == "ld-android.so" else "lib/" + name)
        logical = name if stock[name]["sha256"] == digest(source) else "registry/" + name
        if logical != name:
            record(str(source.relative_to(ROOT)), source, logical)
        registry[name] = logical
    manifest = {"guestSdk": 29, "rootRequired": False, "stockFramework": True,
                "sourceImageSha256": report["sourceSha256"], "bootClassPath": boot,
                "registryLibraries": registry, "files": entries}
    (OUT / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(entries), "bytes": sum(e["bytes"] for e in entries),
                      "manifest": str(OUT / "inputs.json")}, indent=2))


if __name__ == "__main__":
    main()
