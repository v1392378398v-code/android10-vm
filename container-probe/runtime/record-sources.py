#!/usr/bin/env python3
import hashlib
import pathlib
import shlex
import sys

upstream = pathlib.Path(sys.argv[1]).resolve()
derived = upstream.parent / "derived"
manifest = pathlib.Path(sys.argv[2])
inputs = set()
for name in sys.argv[3:]:
    dependency = pathlib.Path(name + ".d").read_text(encoding="utf-8")
    for token in shlex.split(dependency.replace("\\\n", " ").split(":", 1)[1]):
        path = pathlib.Path(token).resolve()
        if path.is_relative_to(derived):
            path = upstream / path.relative_to(derived)
        if path.is_relative_to(upstream):
            inputs.add(path.relative_to(upstream).as_posix())
assert inputs, "No upstream compiler inputs found"
manifest.write_text("".join(
    hashlib.sha256((upstream / name).read_bytes()).hexdigest() + "  " + name + "\n"
    for name in sorted(inputs)
), encoding="utf-8")
print(f"Recorded {len(inputs)} upstream compiler inputs: {manifest}")
