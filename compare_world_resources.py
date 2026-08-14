#!/usr/bin/env python3
"""Read-only comparison/census for Sacred World trigger/resource archives."""
from __future__ import annotations

import hashlib
import re
import struct
import sys
from pathlib import Path

PAK_HDR = 0x20
PAK_IDX = 12
ASCII = re.compile(rb"[ -~]{4,}")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def read_pak(path: Path) -> tuple[bytes, list[tuple[int, int, int]], int]:
    with path.open('rb') as f:
        header = f.read(PAK_HDR)
        f.seek(4)
        raw_n = f.read(4)
        if len(raw_n) != 4:
            raise ValueError('missing entry count')
        n = struct.unpack('<I', raw_n)[0]
        f.seek(PAK_HDR)
        raw = f.read(n * PAK_IDX)
        if len(raw) != n * PAK_IDX:
            raise ValueError(f'truncated index: {len(raw)} != {n * PAK_IDX}')
        entries = [struct.unpack_from('<III', raw, i * PAK_IDX) for i in range(n)]
        return header, entries, f.seek(0, 2)

def census(path: Path, max_strings: int = 2000) -> None:
    header, entries, length = read_pak(path)
    kinds: dict[int, int] = {}
    sizes: dict[int, int] = {}
    strings: list[tuple[int, str]] = []
    coord_hits: list[tuple[int, int, int, int]] = []
    with path.open('rb') as f:
        for i, (kind, offset, size) in enumerate(entries):
            kinds[kind] = kinds.get(kind, 0) + 1
            sizes[size] = sizes.get(size, 0) + 1
            if size > 64 * 1024 * 1024:
                continue
            f.seek(offset)
            blob = f.read(size)
            for m in ASCII.finditer(blob):
                text = m.group().decode('ascii', 'replace')
                if any(word in text.lower() for word in ('door', 'ladder', 'stair', 'teleport', 'inside', 'outside', 'trigger', 'floor')):
                    if len(strings) < max_strings:
                        strings.append((i, text))
            # Look for little-endian signed coordinate-like pairs in the first 512 bytes.
            for off in range(0, max(0, min(len(blob) - 8, 512)), 4):
                x, y = struct.unpack_from('<ii', blob, off)
                if -1000000 < x < 1000000 and -1000000 < y < 1000000 and (x or y):
                    if len(coord_hits) < 40:
                        coord_hits.append((i, off, x, y))
    print(f'path\t{path}')
    print(f'size\t{length}')
    print(f'sha256\t{sha256(path)}')
    print(f'header\t{header[:16].hex()}')
    print(f'entries\t{len(entries)}')
    print(f'kinds\t{sorted(kinds.items())}')
    print(f'unique_sizes\t{len(sizes)}\ttop\t{sorted(sizes.items(), key=lambda x: (-x[1], x[0]))[:12]}')
    print(f'keyword_strings\t{len(strings)}')
    for i, text in strings:
        print(f'string\tentry={i}\t{text}')
    print(f'coordinate_samples\t{len(coord_hits)}')
    for i, off, x, y in coord_hits[:20]:
        print(f'coord\tentry={i}\toff={off:#x}\tx={x}\ty={y}')
    print()

def main() -> int:
    if len(sys.argv) < 2:
        print(f'usage: {sys.argv[0]} ARCHIVE [ARCHIVE ...]', file=sys.stderr)
        return 2
    for raw in sys.argv[1:]:
        path = Path(raw).resolve()
        if not path.is_file():
            print(f'missing\t{path}')
            continue
        try:
            census(path)
        except Exception as exc:
            print(f'error\t{path}\t{exc}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
