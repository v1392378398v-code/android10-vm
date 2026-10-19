#!/usr/bin/env python3
"""Read the fixed ARM64/LP64 companion-library recipes, without host source globs."""
import importlib.util
import json
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "libc_blueprint", pathlib.Path(__file__).resolve().parents[1] / "dynamic/select-libc-sources.py")
blueprint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blueprint)
upstream = pathlib.Path(sys.argv[1]).resolve()
recipes = {
    "math": ("bionic/libm", "libm"),
    "optimized": ("external/arm-optimized-routines", "libarm-optimized-routines"),
    "cxx": ("external/libcxx", "libc++_static"),
    "abi": ("external/libcxxabi", "libc++abi"),
    "unwind": ("external/libunwind_llvm", "libunwind_llvm"),
}
result = {}
for name, (directory, module_name) in recipes.items():
    base = upstream / directory
    parsed = blueprint.Blueprint(base / "Android.bp")
    module = parsed.modules[module_name]
    layers = [parsed.modules[default] for default in module.get("defaults", [])
              if default in parsed.modules]
    layers += [module, module.get("arch", {}).get("arm64", {}),
               module.get("multilib", {}).get("lib64", {}),
               module.get("target", {}).get("android", {})]
    sources, excluded, flags, cppflags, includes = [], set(), [], [], []
    for layer in layers:
        sources += layer.get("srcs", [])
        excluded.update(layer.get("exclude_srcs", []))
        flags += layer.get("cflags", [])
        cppflags += layer.get("cppflags", [])
        includes += layer.get("include_dirs", [])
        includes += [directory + "/" + path for path in layer.get("local_include_dirs", [])]
    selected = []
    for pattern in sources:
        if pattern in excluded:
            continue
        matches = sorted(base.glob(pattern))
        if not matches:
            raise ValueError(f"Missing {module_name} source: {pattern}")
        selected += [path.relative_to(upstream).as_posix() for path in matches]
    result[name] = {"sources": sorted(set(selected)), "cflags": flags, "cppflags": cppflags, "includes": includes,
                    "module": module_name}
print(json.dumps(result, indent=2))
