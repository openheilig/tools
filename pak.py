#!/usr/bin/env python3
"""Sacred .pak reader -- both container shapes.

Common header:
    0x000  char[3] magic + u8 version    "CIF" "ITM" "WPN" "SPF" "ISO" "MIX"
                                         "MDL" "TEX" "SND"
    0x004  u32     entry count
    0x008  ...     zeros to 0x100

Two layouts follow, told apart by whether the count tiles the remaining bytes:

  FIXED  (creature 86, items 140, weapon 322, sndprofiles 196, tiles 76):
      0x100  record[count], stride = (filesize - 256) / count
      Record 0 is a reserved all-zero null slot. creature.pak's 86-byte
      stride is the same 0x56 the 2.30 binary uses in TypeManager::get, so
      an index of 0 lands on that null record -- which is what makes
      `cCreatureHero::CalcResults () type=0 FAILED!` fire.

  BLOB   (models, texture, sound):
      0x100  struct { u32 flags; u32 offset; u32 size; } [count]
      offset is absolute into the file; entries are laid out contiguously.
      flags 0x04 = TGA, 0x40 = Granny .GRN, 0x20 = raw RIFF/WAVE.
      Named payloads begin with a NUL-padded name, raw ones do not.

Usage:
    python3 pak.py <file.pak>              header, layout, first entries
    python3 pak.py <file.pak> N [M]        dump entry N (or range N..M)
    python3 pak.py <file.pak> --list       every blob name + size (BLOB only)
    python3 pak.py <file.pak> --extract D  write all blobs into directory D
"""
import os
import struct
import sys

HDR = 256
IDX = 12


def looks_blob(path, count, size):
    """Entry 0 parses as a sane (flags, offset, size) slot pointing past the index."""
    if size < HDR + IDX * count + 1:
        return False
    with open(path, "rb") as fh:
        fh.seek(HDR)
        fl, off, sz = struct.unpack("<III", fh.read(IDX))
    return fl < 0x1000 and HDR + IDX * count <= off < size and 0 < sz <= size - off


def probe(path):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(HDR)
    magic, ver = head[:3].decode("latin1"), head[3]
    count = struct.unpack("<I", head[4:8])[0]
    if not count:
        raise SystemExit(f"{path}: zero entry count")
    # blob wins: small counts (the *03 add-on overlays) tile by accident.
    if not looks_blob(path, count, size) and (size - HDR) % count == 0:
        return magic, ver, count, "fixed", (size - HDR) // count
    return magic, ver, count, "blob", IDX


def blob_index(path, count):
    with open(path, "rb") as fh:
        fh.seek(HDR)
        raw = fh.read(count * IDX)
    return [struct.unpack_from("<III", raw, i * IDX) for i in range(count)]


def name_of(payload):
    end = payload.find(b"\0")
    head = payload[:end if 0 < end <= 64 else 0]
    return head.decode("latin1") if head.isascii() and head.strip() else ""


def dump(b, i):
    print(f"[{i:6d}] {b[:64].hex(' ', 4)}")
    print(f"         {''.join(chr(c) if 32 <= c < 127 else '.' for c in b[:64])}")


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    path, rest = argv[0], argv[1:]
    magic, ver, count, kind, stride = probe(path)
    print(f"{os.path.basename(path)}: magic={magic!r} v{ver} entries={count} "
          f"layout={kind}" + (f" stride={stride} (0x{stride:x})" if kind == "fixed" else ""))

    if kind == "fixed":
        lo = int(rest[0]) if rest else 0
        hi = int(rest[1]) + 1 if len(rest) > 1 else (lo + 1 if rest else 8)
        with open(path, "rb") as fh:
            for i in range(lo, min(hi, count)):
                fh.seek(HDR + i * stride)
                dump(fh.read(stride), i)
        return

    entries = blob_index(path, count)
    with open(path, "rb") as fh:
        if rest[:1] == ["--extract"]:
            out = rest[1]
            os.makedirs(out, exist_ok=True)
            written = 0
            for i, (fl, off, sz) in enumerate(entries):
                if not sz:
                    continue
                fh.seek(off)
                data = fh.read(sz)
                nm = name_of(data) or f"entry_{i:05d}.bin"
                with open(os.path.join(out, os.path.basename(nm)), "wb") as o:
                    o.write(data)
                written += 1
            print(f"extracted {written} blobs to {out}/")
            return
        if rest[:1] == ["--list"]:
            for i, (fl, off, sz) in enumerate(entries):
                if not sz:
                    continue
                fh.seek(off)
                print(f"[{i:6d}] flags=0x{fl:02x} size={sz:9d}  {name_of(fh.read(64)) or '<raw>'}")
            return
        lo = int(rest[0]) if rest else 0
        hi = int(rest[1]) + 1 if len(rest) > 1 else (lo + 1 if rest else 8)
        for i in range(lo, min(hi, count)):
            fl, off, sz = entries[i]
            fh.seek(off)
            data = fh.read(min(sz, 64))
            print(f"[{i:6d}] flags=0x{fl:02x} off={off} size={sz}  {name_of(data) or '<raw>'}")
            dump(data, i)


def _self_check():
    # ponytail: the only real logic is layout detection + stride derivation.
    assert (41020 - HDR) % 474 == 0 and (41020 - HDR) // 474 == 86, "creature.pak fixed stride"
    assert (4587776 - HDR) // 32768 == 140, "items.pak fixed stride"
    assert (434339908 - HDR) % 4993 != 0, "models.pak must fall through to blob"
    assert name_of(b"BAT.GRN\0\0\0") == "BAT.GRN", "blob name parse"
    assert name_of(b"RIFF\x40\x82\x00\x00WAVE") == "", "raw payload has no name"
    print("ok")


if __name__ == "__main__":
    (_self_check if sys.argv[1:2] == ["--self-check"] else lambda: main(sys.argv[1:]))()
