#!/usr/bin/env python3
"""Select the fixed Android/vendor Binder recipe and its support-library closure."""
import importlib.util
import json
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "libc_blueprint", pathlib.Path(__file__).resolve().parents[1] / "runtime/dynamic/select-libc-sources.py")
blueprint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blueprint)
upstream = pathlib.Path(sys.argv[1]).resolve()
recipes = {
    "log": ("system/core/liblog", "liblog"),
    "base": ("system/core/base", "libbase"),
    "utils": ("system/core/libutils", "libutils"),
    "binderthreadstate": ("frameworks/native/libs/binderthreadstate", "libbinderthreadstate"),
    "binder": ("frameworks/native/libs/binder", "libbinder"),
}
result = {}
for name, (directory, module_name) in recipes.items():
    base = upstream / directory
    parsed = blueprint.Blueprint(base / "Android.bp")
    module = parsed.modules[module_name]
    layers = [parsed.modules[default] for default in module.get("defaults", [])
              if default in parsed.modules]
    layers += [module, module.get("target", {}).get("android", {}),
               module.get("target", {}).get("linux", {}),
               module.get("target", {}).get("vendor", {})]
    sources, excluded = [], set()
    for layer in layers:
        sources += layer.get("srcs", [])
        excluded.update(layer.get("exclude_srcs", []))
    selected = []
    for source in sources:
        if source in excluded:
            continue
        if not (base / source).is_file():
            raise ValueError(f"Missing {module_name} source: {source}")
        selected.append(directory + "/" + source)
    result[name] = {"sources": sorted(set(selected)), "module": module_name}

# Only these libcutils implementations are needed by the Binder/RefBase closure.
cutils = ["native_handle.cpp", "properties.cpp", "strdup16to8.cpp", "strdup8to16.cpp", "threads.cpp", "trace-host.cpp",
          "arch-arm64/android_memset.S"]
result["cutils"] = {"sources": ["system/core/libcutils/" + path for path in cutils],
                    "module": "libcutils", "selection": "binder-support-closure"}
print(json.dumps(result, indent=2))
