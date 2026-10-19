"""Inventory system APKs and their ARM64 libraries directly from the source image."""
import posixpath
import re
import stat
import subprocess


class SystemPackages:
    def __init__(self, debugfs, image):
        self.debugfs = str(debugfs)
        self.image = str(image)

    def query(self, command):
        return subprocess.check_output([self.debugfs, "-R", command, self.image],
                                       text=True, stderr=subprocess.DEVNULL)

    def walk(self, directory):
        for row in self.query("ls -p " + directory).splitlines():
            fields = row.split("/")
            if len(fields) < 6 or fields[5] in (".", "..", "oat", "arm", "x86", "x86_64"):
                continue
            path = directory + "/" + fields[5]
            mode = int(fields[2], 8)
            if stat.S_ISDIR(mode):
                yield from self.walk(path)
            else:
                yield path, mode

    def resolve(self, path, mode):
        if not stat.S_ISLNK(mode):
            return path
        match = re.search(r'Fast link dest: "([^"]+)"', self.query("stat " + path))
        if not match:
            raise RuntimeError("Unreadable package library link: " + path)
        target = match.group(1)
        resolved = posixpath.normpath(target if target.startswith("/") else posixpath.dirname(path) + "/" + target)
        if resolved.startswith("/product/"):
            resolved = "/system" + resolved
        return resolved

    def inventory(self):
        packages, libraries, links = {}, {}, []
        for directory in ("/system/app", "/system/priv-app", "/system/product/app",
                          "/system/product/priv-app", "/vendor/app", "/vendor/priv-app",
                          "/system/system_ext/app", "/system/system_ext/priv-app"):
            for path, mode in self.walk(directory):
                if path.endswith(".apk"):
                    packages[path.removeprefix("/")] = path
                elif path.endswith(".so"):
                    source = self.resolve(path, mode)
                    name = posixpath.basename(source)
                    if name in libraries and libraries[name] != source:
                        raise RuntimeError("Conflicting system app library: " + name)
                    libraries[name] = source
                    links.append({"path": path, "target": "/system/lib64/" + name})
        return packages, libraries, links
