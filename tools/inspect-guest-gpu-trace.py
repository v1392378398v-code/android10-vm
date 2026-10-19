#!/usr/bin/env python3
"""Summarize a paired GLES trace and extract uploaded RGBA images."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=1200)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    names = {}
    for header in ("generated/gl2_opcodes.h", "desktop/generated/renderControl_opcodes.h"):
        source = (ROOT / "artifacts/container/graphics" / header).read_text()
        names.update({int(number): name for name, number in re.findall(r"#define OP_(\w+)\s+(\d+)", source)})
    counts, states, commands = Counter(), {}, []
    with args.trace.open("rb") as source:
        source.read(80)
        for number in range(args.limit):
            header = source.read(8)
            if not header:
                break
            opcode, size = struct.unpack("<II", header)
            if size < 8 or size > 128 * 1024 * 1024:
                raise ValueError("Invalid trace packet size")
            body = source.read(size - 8)
            if len(body) != size - 8:
                break
            name = names.get(opcode, str(opcode))
            counts[name] += 1
            item = {"index": number + 1, "command": name}
            if name in ("glViewport", "glScissor", "glTexImage2D", "glTexSubImage2D", "glPixelStorei"):
                length = {"glViewport": 4, "glScissor": 4, "glPixelStorei": 2,
                          "glTexImage2D": 9, "glTexSubImage2D": 9}[name]
                values = struct.unpack("<" + "I" * length, body[:length * 4])
                if values != states.get(name):
                    states[name] = values
                    item["values"] = values
                    commands.append(item)
                if name == "glTexSubImage2D" and values[6:8] == (0x1908, 0x1401) and counts[name] in (1, 3, 10, 30):
                    width, height = values[4:6]
                    if values[8] == width * height * 4:
                        image = Image.frombytes("RGBA", (width, height), body[36:36 + values[8]])
                        image.save(args.output / ("upload-" + str(counts[name]) + ".png"))
            elif name == "glShaderString":
                length = struct.unpack_from("<I", body, 4)[0]
                item["source"] = body[8:8 + length].decode(errors="replace").rstrip("\0")
                commands.append(item)
            elif name == "glVertexAttribPointerData" and number < 340:
                index, size, gl_type = struct.unpack_from("<III", body)
                normalized = body[12]
                stride, length = struct.unpack_from("<II", body, 13)
                item.update(index=index, size=size, type=gl_type, normalized=normalized,
                            stride=stride, length=length)
                if gl_type == 0x1406:
                    item["values"] = struct.unpack("<" + "f" * (length // 4), body[21:21 + length])
                commands.append(item)
    report = {"counts": counts, "commands": commands}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"counts": counts, "commands": len(commands)}, indent=2))


if __name__ == "__main__":
    main()
