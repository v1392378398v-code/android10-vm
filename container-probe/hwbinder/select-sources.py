#!/usr/bin/env python3
"""Select the fixed Android 10 libhwbinder source closure."""
import importlib.util
import json
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "libc_blueprint", pathlib.Path(__file__).resolve().parents[1] / "runtime/dynamic/select-libc-sources.py")
blueprint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blueprint)
upstream = pathlib.Path(sys.argv[1]).resolve()
base = upstream / "system/libhwbinder"
parsed = blueprint.Blueprint(base / "Android.bp")
module = parsed.modules["libhwbinder_defaults"]
sources = []
for source in module.get("srcs", []):
    if not (base / source).is_file():
        raise ValueError(f"Missing libhwbinder source: {source}")
    sources.append(f"system/libhwbinder/{source}")
print(json.dumps({"sources": sorted(set(sources)), "module": "libhwbinder_defaults"}, indent=2))
