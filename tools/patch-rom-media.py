#!/usr/bin/env python3
"""Guard the ROM NuPlayer renderer during reset before playback has started."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile

SYMBOL = "_ZN7android8NuPlayer14closeAudioSinkEv"


def branch(source, target):
    distance = target - source
    if distance % 4 or not -(1 << 27) <= distance < (1 << 27):
        raise ValueError("ARM64 branch target is out of range")
    return 0x14000000 | ((distance // 4) & 0x3ffffff)


def patch(source, destination):
    source, destination = source.resolve(strict=True), destination.resolve()
    if source == destination:
        raise ValueError("Keep the original ROM library separate")
    data = source.read_bytes()
    with source.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 64 or not elf.little_endian or elf['e_machine'] != 'EM_AARCH64':
            raise ValueError("Expected a little-endian ARM64 ELF")
        symbols = elf.get_section_by_name('.dynsym').get_symbol_by_name(SYMBOL)
        if not symbols or len(symbols) != 1:
            raise ValueError("Expected one exported NuPlayer closeAudioSink")
        symbol = symbols[0]
        address = symbol['st_value']
        segments = list(elf.iter_segments())
        index, segment = next((i, p) for i, p in enumerate(segments)
                              if p['p_type'] == 'PT_LOAD' and p['p_flags'] & 1 and
                              p['p_vaddr'] <= address < p['p_vaddr'] + p['p_filesz'])
        offset = segment['p_offset'] + address - segment['p_vaddr']
        load, = struct.unpack_from('<I', data, offset)
        if symbol['st_size'] < 8 or load & 0xffc003ff != 0xf9400000:
            raise ValueError("Expected an initial LDR X0, [X0, renderer offset]")
        if segment['p_filesz'] != segment['p_memsz']:
            raise ValueError("Executable segment has an uninitialized tail")
        guard_offset = (segment['p_offset'] + segment['p_filesz'] + 3) & ~3
        guard_address = segment['p_vaddr'] + guard_offset - segment['p_offset']
        for part in segments:
            if part['p_type'] == 'PT_LOAD' and part['p_offset'] >= guard_offset:
                if guard_offset + 16 > part['p_offset'] or guard_address + 16 > part['p_vaddr']:
                    raise ValueError("No executable padding for the renderer guard")
        if data[guard_offset:guard_offset + 16] != bytes(16):
            raise ValueError("Expected unused zero padding after executable segment")
        result = bytearray(data)
        struct.pack_into('<I', result, offset, branch(address, guard_address))
        # Load the renderer, return for null, otherwise run the original CFI checked body.
        struct.pack_into('<IIII', result, guard_offset, load, 0xb4000040,
                         branch(guard_address + 8, address + 4), 0xd65f03c0)
        header = elf['e_phoff'] + index * elf['e_phentsize']
        size = guard_offset + 16 - segment['p_offset']
        struct.pack_into('<QQ', result, header + 32, size, size)
    changed = {i for i, (before, after) in enumerate(zip(data, result)) if before != after}
    allowed = set(range(offset, offset + 4)) | set(range(guard_offset, guard_offset + 16)) | \
        set(range(header + 32, header + 48))
    if not changed <= allowed:
        raise AssertionError("Unexpected ROM library modification")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result)
    with destination.open('rb') as stream:
        verified = ELFFile(stream)
        assert verified.get_segment(index)['p_filesz'] == size
        assert verified.get_section_by_name('.dynsym').get_symbol_by_name(SYMBOL)[0]['st_value'] == address
    return {"source": str(source), "derived": str(destination), "symbol": SYMBOL,
            "sourceSha256": hashlib.sha256(data).hexdigest(), "sha256": hashlib.sha256(result).hexdigest(),
            "entryOffset": hex(offset), "guardOffset": hex(guard_offset), "changedBytes": len(changed),
            "rendererFieldOffset": hex(((load >> 10) & 0xfff) * 8), "cfiBodyPreserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(patch(args.source, args.destination), indent=2))


if __name__ == '__main__':
    main()
