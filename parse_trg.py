#!/usr/bin/env python3
"""Parse the observed Sacred TRG v1 resource without changing source media."""
from __future__ import annotations

import hashlib
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"TRG\x01"
TRG_HEADER_SIZE = 0x100
TRG_EXTENSION_SIZE = 0x0c
RECORD_SIZE = 16
ASCII = re.compile(rb"[ -~]{4,}")

@dataclass(frozen=True, slots=True)
class TrgRecord:
    index: int
    words: tuple[int, int, int, int]


def parse(path: Path) -> tuple[bytes, tuple[TrgRecord, ...], int, tuple[int, int, int]]:
    data = path.read_bytes()
    if len(data) < TRG_HEADER_SIZE + TRG_EXTENSION_SIZE or data[:4] != MAGIC:
        raise ValueError(f"not TRG v1: {path}")
    count = struct.unpack_from("<I", data, 4)[0]
    extension = struct.unpack_from("<III", data, TRG_HEADER_SIZE)
    table_start = TRG_HEADER_SIZE + TRG_EXTENSION_SIZE
    table_end = table_start + count * RECORD_SIZE
    if table_end > len(data):
        raise ValueError(f"record table exceeds file: {table_end:#x} > {len(data):#x}")
    records = tuple(
        TrgRecord(i, struct.unpack_from("<IIII", data, table_start + i * RECORD_SIZE))
        for i in range(count)
    )
    return data, records, table_start, extension


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path) -> None:
    data, records, table_start, extension = parse(path)
    table_end = table_start + len(records) * RECORD_SIZE
    nonzero = [record for record in records if any(record.words)]
    print(f"path\t{path}")
    print(f"sha256\t{digest(path)}")
    print(f"size\t{len(data)}")
    print(f"count\t{len(records)}")
    print(f"header\tstart=0x0\tsize=0x{TRG_HEADER_SIZE:x}")
    print(f"extension\tstart=0x{TRG_HEADER_SIZE:x}\tsize=0x{TRG_EXTENSION_SIZE:x}\tvalues={extension}")
    print(f"records\tstart=0x{table_start:x}\tend=0x{table_end:x}\tsize={table_end-table_start}\tnonzero={len(nonzero)}")
    print(f"trailing\tbytes={len(data)-table_end}")
    for record in nonzero:
        words = ",".join(f"0x{word:x}" for word in record.words)
        print(f"record\tindex={record.index}\twords={words}")
    print()


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} TRG [TRG ...]", file=sys.stderr)
        return 2
    for raw in sys.argv[1:]:
        try:
            dump(Path(raw).resolve())
        except (OSError, ValueError, struct.error) as exc:
            print(f"error\t{raw}\t{exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
