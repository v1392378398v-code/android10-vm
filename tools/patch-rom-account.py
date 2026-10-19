#!/usr/bin/env python3
"""Adapt MIUI's FindDevice login gate to the ROM credential SDK capability."""
import argparse
from copy import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ADAPTER = "com/xiaomi/account/finddevice/b.smali"
APPLICATION = "com/xiaomi/finddevice/Application.smali"
SDK = "Lcom/xiaomi/security/devicecredential/SecurityDeviceCredentialManager;->isThisDeviceSupported()Z"
METHOD = re.compile(r"^\.method public a\(\)Z\n.*?^\.end method$", re.M | re.S)


def adapt(text):
    methods = list(METHOD.finditer(text))
    if len(methods) != 1:
        raise ValueError("Expected one MIUI FindDevice capability method")
    method = methods[0]
    body = method.group()
    if SDK in body:
        raise ValueError("The source already has a credential capability gate")
    if "Lcom/xiaomi/account/e/L;->a()Z" not in body or "Lcom/xiaomi/accountsdk/account/i;->a:Z" not in body:
        raise ValueError("Unexpected MIUI FindDevice capability conditions")
    success = "    const/4 v0, 0x1"
    if body.count(success) != 1:
        raise ValueError("Expected one supported FindDevice branch")
    replacement = "    invoke-static {}, " + SDK + "\n\n    move-result v0"
    return text[:method.start()] + body.replace(success, replacement, 1) + text[method.end():]


def preserve_credential_service(text):
    pattern = re.compile(r"^\.method private publishServices\(\)V\n.*?^\.end method$", re.M | re.S)
    methods = list(pattern.finditer(text))
    if len(methods) != 1:
        raise ValueError("Expected one FindDevice service publisher")
    method = methods[0]
    body = method.group()
    if 'const-string v0, "miui.sedc"' not in body or "PriviledgedProc;->addService" not in body:
        raise ValueError("Unexpected FindDevice credential service registration")
    declaration = "    .locals 2\n"
    if body.count(declaration) != 1 or "a10vm_publish_credential" in body:
        raise ValueError("Unexpected FindDevice publisher registers or an already adapted source")
    guard = '''
    const-string v0, "miui.sedc"
    invoke-static {v0}, Landroid/os/ServiceManager;->checkService(Ljava/lang/String;)Landroid/os/IBinder;
    move-result-object v0
    if-eqz v0, :a10vm_publish_credential
    invoke-interface {v0}, Landroid/os/IBinder;->pingBinder()Z
    move-result v0
    if-eqz v0, :a10vm_publish_credential
    return-void

    :a10vm_publish_credential
'''
    return text[:method.start()] + body.replace(declaration, declaration + guard, 1) + text[method.end():]


def patch(source, destination, kind="account"):
    source, destination = source.resolve(strict=True), destination.resolve()
    if source == destination:
        raise ValueError("Keep the original system APK separate")
    with tempfile.TemporaryDirectory(prefix="a10vm-account-") as temporary:
        work = Path(temporary) / "decoded"
        subprocess.run(["apktool", "d", "-r", "-o", str(work), str(source)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        target = ADAPTER if kind == "account" else APPLICATION
        adapters = list(work.glob("smali*/" + target))
        if len(adapters) != 1:
            raise ValueError("Expected one MIUI account FindDevice adapter")
        adapter = adapters[0]
        original = adapter.read_text(encoding="utf-8")
        transform = adapt if kind == "account" else preserve_credential_service
        adapter.write_text(transform(original), encoding="utf-8")
        built = Path(temporary) / "account.apk"
        subprocess.run(["apktool", "b", "--copy-original", "-o", str(built), str(work)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        tree = adapter.relative_to(work).parts[0]
        dex_name = "classes" + tree.removeprefix("smali").removeprefix("_classes") + ".dex"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as base, zipfile.ZipFile(built) as compiled:
            if not any(name.startswith("META-INF/") and name.endswith((".RSA", ".DSA", ".EC")) for name in base.namelist()):
                raise ValueError("Expected the original preinstalled APK certificate")
            if dex_name not in base.namelist():
                raise ValueError("Expected the adapter's original DEX entry")
            replacement = compiled.read(dex_name)
            if replacement == base.read(dex_name):
                raise AssertionError("Account DEX did not change")
            with zipfile.ZipFile(destination, "w") as output:
                for item in base.infolist():
                    output.writestr(copy(item), replacement if item.filename == dex_name else base.read(item.filename))
            with zipfile.ZipFile(destination) as output:
                if base.namelist() != output.namelist():
                    raise AssertionError("Unexpected system APK entries")
                if any(base.read(name) != output.read(name) for name in base.namelist() if name != dex_name):
                    raise AssertionError("Unexpected non-target system APK changes")
        return {"kind": kind, "source": str(source), "derived": str(destination), "dex": dex_name,
                "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "capabilityApi": SDK if kind == "account" else "android.os.ServiceManager.checkService / IBinder.pingBinder",
                "originalConditionsPreserved": True,
                "existingCredentialEndpointPreserved": kind == "finddevice",
                "nonTargetEntriesPreserved": True, "preinstalledCertificatePreserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--kind", choices=("account", "finddevice"), default="account")
    args = parser.parse_args()
    try:
        print(json.dumps(patch(args.source, args.destination, args.kind), indent=2))
    except subprocess.CalledProcessError as failure:
        raise RuntimeError(failure.stdout.decode(errors="replace")) from failure


if __name__ == "__main__":
    main()
