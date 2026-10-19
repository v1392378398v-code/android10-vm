"""Restore image property files and prepare one seed using Android 10 precedence."""
import re

from prepare import extract

SOURCES = (
    "/system/etc/prop.default", "/odm/etc/prop.default", "/vendor/default.prop",
    "/system/build.prop", "/vendor/build.prop", "/odm/etc/build.prop",
    "/odm/build.prop", "/system/product/build.prop", "/system/product_services/build.prop",
)
PRODUCT_ORDER = ("product", "product_services", "odm", "vendor", "system")


def restore(inventory, rootfs):
    files = []
    for source in SOURCES:
        if "Type: regular" not in inventory.query("stat " + source):
            continue
        target = rootfs / source.lstrip("/")
        assert extract(source, target), source
        files.append(source)
    assert "/system/etc/prop.default" in files and "/system/build.prop" in files
    return files


def parse(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Invalid property: " + line)
        result[name] = value
    return result


def merge(rootfs, sources, overrides):
    properties = {}
    for source in sources:
        properties.update(parse((rootfs / source.lstrip("/")).read_text(encoding="utf-8")))
    properties.update(parse(overrides.read_text(encoding="utf-8")))
    order = properties.get("ro.product.property_source_order", ",".join(PRODUCT_ORDER)).split(",")
    if not order or any(item not in PRODUCT_ORDER for item in order):
        order = PRODUCT_ORDER
    for field in ("brand", "device", "manufacturer", "model", "name"):
        name = "ro.product." + field
        if properties.get(name):
            continue
        for partition in order:
            value = properties.get("ro.product." + partition + "." + field)
            if value:
                properties[name] = value
                break
    if not properties.get("ro.build.fingerprint"):
        get = lambda name: properties.get(name) or "unknown"
        properties["ro.build.fingerprint"] = (
            get("ro.product.brand") + "/" + get("ro.product.name") + "/" + get("ro.product.device")
            + ":" + get("ro.build.version.release") + "/" + get("ro.build.id") + "/"
            + get("ro.build.version.incremental") + ":" + get("ro.build.type") + "/" + get("ro.build.tags"))
    return properties
