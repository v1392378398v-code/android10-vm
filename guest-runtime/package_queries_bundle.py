"""Stage the package-query delegate and remove obsolete native reply hooks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent


def stage_package_queries(prepared):
    manifest = prepared / "assets/guest-runtime-inputs.json"
    inputs = json.loads(manifest.read_text(encoding="utf-8"))
    logical = "liba10vm-package-queries.so"
    inputs["files"] = [item for item in inputs["files"] if item["logical"] != logical]
    (prepared / "jniLibs/arm64-v8a" / logical).unlink(missing_ok=True)
    inputs.pop("packageQueryReplies", None)
    inputs["packageQueryClientReplies"] = True
    inputs["nativeLinks"] = [item for item in inputs.get("nativeLinks", []) if item["logical"] != logical]
    name = "guest-runtime/framework-check.dex"
    target = prepared / "assets" / name
    shutil.copyfile(ROOT / "artifacts/container/framework/dex/classes.dex", target)
    with target.open("rb") as stream:
        item = next(item for item in inputs["data"] if item["name"] == name)
        item.update(bytes=target.stat().st_size, sha256=hashlib.file_digest(stream, "sha256").hexdigest())
    manifest.write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    return inputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    args = parser.parse_args()
    result = stage_package_queries(args.prepared)
    print(json.dumps({"packageQueryClientReplies": result["packageQueryClientReplies"], "rootRequired": False}))
