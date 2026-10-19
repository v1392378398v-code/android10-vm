#!/usr/bin/env python3
"""Convert a full Android block OTA into independent, sparse raw partitions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

BLOCK = 4096


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_transfer(text):
    lines = text.splitlines()
    if len(lines) < 4 or int(lines[0]) not in (2, 3, 4):
        raise ValueError("Expected a full block OTA transfer list v2-v4")
    if any(int(value) for value in lines[2:4]):
        raise ValueError("Stashed incremental OTA blocks need a base image")
    commands, limit, written = [], 0, 0
    for line in lines[4:]:
        if not line.strip():
            continue
        operation, encoded = line.split()
        if operation not in ("new", "zero", "erase"):
            raise ValueError("Incremental OTA operation: " + operation)
        values = [int(value) for value in encoded.split(",")]
        if values[0] != len(values) - 1 or values[0] % 2:
            raise ValueError("Invalid block range count")
        ranges = list(zip(values[1::2], values[2::2]))
        if not ranges or any(start < 0 or end <= start for start, end in ranges):
            raise ValueError("Invalid block range")
        if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
            raise ValueError("Overlapping block ranges")
        limit = max(limit, *(end for _, end in ranges))
        if operation in ("new", "zero"):
            written += sum(end - start for start, end in ranges)
        commands.append((operation, ranges))
    if written != int(lines[1]) or not limit:
        raise ValueError("Transfer block total mismatch")
    return commands, limit


def write_partition(stream, destination, commands, limit):
    with destination.open("xb") as output:
        output.truncate(limit * BLOCK)
        for operation, ranges in commands:
            for start, end in ranges:
                output.seek(start * BLOCK)
                remaining = (end - start) * BLOCK
                while remaining:
                    size = min(remaining, 1024 * 1024)
                    chunk = stream.read(size) if operation == "new" else bytes(size)
                    if not chunk:
                        raise ValueError("Truncated decompressed OTA data")
                    output.write(chunk)
                    remaining -= len(chunk)
        if stream.read(1):
            raise ValueError("Trailing decompressed OTA data")


def import_ota(source, output, expected_hash=None):
    source = source.resolve(strict=True)
    source_hash = digest(source)
    if expected_hash and expected_hash != source_hash:
        raise ValueError("Source OTA SHA-256 mismatch")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"source": str(source), "sourceSha256": source_hash,
                "sourceBytes": source.stat().st_size, "partitions": {}}
    with zipfile.ZipFile(source) as archive:
        metadata = archive.read("META-INF/com/android/metadata").decode("utf-8")
        (output / "metadata.txt").write_text(metadata, encoding="utf-8")
        manifest["metadata"] = dict(line.split("=", 1) for line in metadata.splitlines() if "=" in line)
        for partition in ("system", "vendor"):
            transfer = archive.read(partition + ".transfer.list").decode("ascii")
            (output / (partition + ".transfer.list")).write_text(transfer, encoding="ascii")
            commands, limit = parse_transfer(transfer)
            compressed = output / (partition + ".new.dat.br")
            with archive.open(compressed.name) as data, compressed.open("xb") as destination:
                shutil.copyfileobj(data, destination, 1024 * 1024)
            raw = output / (partition + ".raw")
            with (output / (partition + "-brotli.log")).open("wb") as log:
                process = subprocess.Popen(["brotli", "-d", "-c", str(compressed)],
                                           stdout=subprocess.PIPE, stderr=log)
                try:
                    write_partition(process.stdout, raw, commands, limit)
                    if process.wait() != 0:
                        raise ValueError("Brotli decompression failed: " + partition)
                finally:
                    process.stdout.close()
                    if process.poll() is None:
                        process.terminate()
                        process.wait()
            manifest["partitions"][partition] = {
                "path": raw.name, "bytes": raw.stat().st_size, "sha256": digest(raw),
                "compressedSha256": digest(compressed), "commands": len(commands)}
            print(json.dumps({"partition": partition, **manifest["partitions"][partition]}), flush=True)
        with archive.open("boot.img") as data, (output / "boot.img").open("xb") as destination:
            shutil.copyfileobj(data, destination, 1024 * 1024)
        manifest["boot"] = {"path": "boot.img", "sha256": digest(output / "boot.img"),
                            "bytes": (output / "boot.img").stat().st_size}
    manifest["sourceUnchanged"] = digest(source) == source_hash
    if not manifest["sourceUnchanged"]:
        raise ValueError("Source OTA changed during import")
    (output / "import.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sha256")
    arguments = parser.parse_args()
    print(json.dumps(import_ota(arguments.source, arguments.output, arguments.sha256), indent=2))
