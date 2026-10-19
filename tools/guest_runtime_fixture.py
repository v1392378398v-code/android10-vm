"""Prepare the exact packaged runtime set for ordinary-UID integration checks."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PREPARED = ROOT / "guest-runtime/build/prepared"
LIB = PREPARED / "jniLibs/arm64-v8a"


class RuntimeInstance:
    def __init__(self, directory, extra_native=None, prepared=PREPARED):
        self.directory = Path(directory)
        prepared = Path(prepared)
        native_source = prepared / "jniLibs/arm64-v8a"
        self.inputs = json.loads((prepared / "assets/guest-runtime-inputs.json").read_text())
        self.names = {item["logical"]: item["name"] for item in self.inputs["files"]}
        self.native_directory = self.directory / "native"
        self.native_directory.mkdir(parents=True)
        self.rootfs = self.directory / "rootfs"
        self.libraries = self.directory / "lib"
        self.libraries.mkdir(parents=True)
        for item in self.inputs["files"] + self.inputs["data"]:
            source = native_source / item["name"] if "logical" in item else prepared / "assets" / item["name"]
            assert source.stat().st_size == item["bytes"] and hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]
            if "logical" not in item:
                target = self.directory / item.get("installPath", item["name"].removeprefix("guest-runtime/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if "mode" in item:
                    target.chmod(item["mode"])
            else:
                destination = self.native_directory / item["name"]
                shutil.copyfile(source, destination)
                destination.chmod(0o755)
                library = item.get("libraryName", item["logical"] if item["logical"].endswith(".so") else "")
                if library:
                    link = self.libraries / library
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(destination)
        for name, source in (extra_native or {}).items():
            self.names[name] = name
            destination = self.native_directory / name
            shutil.copyfile(source, destination)
            destination.chmod(0o755)
            if name.endswith(".so"):
                link = self.libraries / name
                link.unlink(missing_ok=True)
                link.symlink_to(destination)
        for name in self.inputs["initialDirectories"]:
            (self.rootfs / name).mkdir(parents=True, exist_ok=True)
        for item in self.inputs["files"]:
            logical = item["logical"]
            library = item.get("libraryName", logical if logical.endswith(".so") else "")
            if library:
                link = self.rootfs / "system/lib64" / library
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(self.native(logical))
        for item in self.inputs["files"]:
            if "guestPath" in item:
                link = self.rootfs / item["guestPath"].removeprefix("/")
                link.parent.mkdir(parents=True, exist_ok=True)
                link.unlink(missing_ok=True)
                link.symlink_to(self.native(item["logical"]))
        for item in self.inputs.get("links", []):
            link = self.directory / item["path"]
            link.parent.mkdir(parents=True, exist_ok=True)
            link.hardlink_to(self.directory / item["target"])
        for item in self.inputs.get("symlinks", []):
            link = self.directory / item["path"]
            link.parent.mkdir(parents=True, exist_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(item["target"])
        for item in self.inputs.get("nativeLinks", []):
            link = self.directory / item["path"]
            link.parent.mkdir(parents=True, exist_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(self.native(item["logical"]))
        aliases = {"apex/com.android.runtime": "/system/apex/com.android.runtime.debug",
                   "product": "/system/product", "etc": "/system/etc", "data/data": "/data/user/0"}
        for name in ("com.android.conscrypt", "com.android.media", "com.android.media.swcodec", "com.android.resolv", "com.android.tzdata"):
            aliases["apex/" + name] = "/system/apex/" + name
        aliases.update(self.inputs.get("rootfsAliases", {}))
        for path, target in aliases.items():
            link = self.rootfs / path
            link.unlink(missing_ok=True)
            link.symlink_to(target)
        (self.directory / "sock").mkdir()
        (self.rootfs / "dev/socket").symlink_to(self.directory / "sock")
        config = self.directory / "ld.config.txt"
        namespaces = ["runtime", "conscrypt", "media", "swcodec"]
        if "romBoot" in self.inputs:
            namespaces.extend(("vndk", "sphal"))
        configuration = (f"dir.guest = {self.native_directory}\ndir.guest = {self.directory}\n"
                         f"[guest]\nadditional.namespaces = {','.join(namespaces)}\n")
        configuration += (
            f"namespace.default.isolated = true\nnamespace.default.search.paths = {self.libraries}\n"
            f"namespace.default.permitted.paths = {self.native_directory}:{self.directory}\n")
        for name in namespaces:
            configuration += (f"namespace.{name}.visible = true\nnamespace.{name}.isolated = true\n"
                f"namespace.{name}.search.paths = {self.libraries}\n"
                f"namespace.{name}.permitted.paths = {self.native_directory}:{self.directory}\n"
                f"namespace.{name}.links = default\nnamespace.{name}.link.default.allow_all_shared_libs = true\n")
        config.write_text(configuration, encoding="utf-8")
        self.environment = {"PATH": "/system/bin", "TMPDIR": str(self.directory),
            "ANDROID_ROOT": "/system", "ANDROID_DATA": "/data", "ANDROID_RUNTIME_ROOT": "/apex/com.android.runtime",
            "ANDROID_STORAGE": "/storage", "EXTERNAL_STORAGE": "/storage/emulated/0", "ASEC_MOUNTPOINT": "/mnt/asec",
            "ANDROID_TZDATA_ROOT": "/apex/com.android.tzdata", "A10VM_ROOTFS": str(self.rootfs),
            "A10VM_HOST_ROOT": str(self.native_directory), "A10VM_STATE_ROOT": str(self.directory.parent),
            "A10VM_PROPERTIES": str(self.directory / "properties"), "A10VM_LD_CONFIG": str(config),
            "A10VM_EXEC_LINKER": str(self.native("ld-android.so"))}
        seed = subprocess.run([str(self.native("seed-properties")), self.environment["A10VM_PROPERTIES"],
                               str(self.directory / "guest.prop")], env={"PATH": "/system/bin"},
                              capture_output=True, text=True, timeout=5)
        assert seed.returncode == 0 and "seed_sdk=29\n" in seed.stdout, seed.stdout + seed.stderr

    def framework_environment(self):
        return dict(self.environment, A10VM_BINDER_PATH=str(self.directory / "binder.sock"),
                    LD_PRELOAD=str(self.native("liba10vm-hal-modules.so")) + ":" +
                               str(self.native("liba10vm-guest-devices.so")) + ":" +
                               str(self.native("liba10vm-binder-devices.so")) + ":" +
                               str(self.native("liba10vm-guest-log.so")) + ":" +
                               str(self.native("libandroid_runtime.so")) + ":" +
                               str(self.native("libutils.so")) + ":" +
                               str(self.native("libbinder.so")) + ":" +
                               str(self.native("libhwbinder.so")) + ":" +
                               str(self.native("libhidlbase.so")),
                    CLASSPATH=str(self.directory / "framework-check.dex"),
                    BOOTCLASSPATH=":".join(self.inputs["bootClassPath"]))

    def registry_environment(self):
        directory = self.directory / "registry-lib"
        directory.mkdir(exist_ok=True)
        for soname, logical in self.inputs["registryLibraries"].items():
            link = directory / soname
            link.unlink(missing_ok=True)
            link.symlink_to(self.native(logical))
        config = self.directory / "registry.config.txt"
        config.write_text(f"dir.registry = {self.native_directory}\n[registry]\n"
            f"namespace.default.isolated = true\nnamespace.default.search.paths = {directory}\n"
            f"namespace.default.permitted.paths = {self.native_directory}:{self.directory}\n", encoding="utf-8")
        return dict(self.environment, A10VM_LD_CONFIG=str(config),
                    A10VM_BINDER_PATH=str(self.directory / "binder.sock"))

    def framework_command(self, role, nonce):
        return [str(self.native("ld-android.so")), str(self.native("app_process64")),
                "-Xnoimage-dex2oat", "/system/bin",
                "io.a10vm.guest.Framework" + role, nonce]

    def native(self, logical):
        return (self.native_directory / self.names[logical]).resolve()

    def art_command(self, nonce):
        return [str(self.native("ld-android.so")), str(self.native("dalvikvm64")),
                "-Xnoimage-dex2oat", "-Xbootclasspath:/apex/com.android.runtime/javalib/core-oj.jar:"
                "/apex/com.android.runtime/javalib/core-libart.jar", "-Djava.library.path=" + str(self.libraries),
                "-cp", str(self.directory / "runtime-check.dex"), "io.a10vm.guest.RuntimeCheck", nonce]
