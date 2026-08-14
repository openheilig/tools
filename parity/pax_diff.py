#!/usr/bin/env python3
"""Census one PAX section type across the eight-hero corpus (TSV row 533).

    ./pax_diff.py C8

Dumps nothing to disk and forms no verdict -- it prints sizes, the shared
prefix/suffix length, and a byte-level agreement map so the *shape* of the
section is visible before anyone guesses at field meanings.
"""
import sys, zlib, pathlib

# absolute(), not resolve() -- see patch_1002.py; the symlink must survive.
DIR = pathlib.Path(__file__).absolute().parents[2] / "community/unpack-tools/Chars"
TABLE, ENTRY, COMPRESSED, PAYLOAD = 0x100, 12, 0xBAADC0DE, 0x20


def sections(path):
    d = path.read_bytes()
    n = int.from_bytes(d[4:8], "little")
    out = {}
    for i in range(n):
        e = TABLE + i * ENTRY
        t = int.from_bytes(d[e:e + 4], "little")
        if t == 0:
            continue
        off = int.from_bytes(d[e + 4:e + 8], "little")
        usz = int.from_bytes(d[e + 8:e + 12], "little")
        if int.from_bytes(d[off:off + 4], "little") == COMPRESSED:
            csz = int.from_bytes(d[off + 4:off + 8], "little")
            out[t] = zlib.decompress(d[off + PAYLOAD:off + PAYLOAD + csz])
        else:
            out[t] = d[off:off + (64 if t == 0xC4 else usz)]
    return out


def main():
    want = int(sys.argv[1], 16)
    blobs = []
    for i in range(8):
        p = DIR / f"Hero{i:02d}.pax"
        s = sections(p)
        if want not in s:
            print(f"Hero{i:02d}\tno 0x{want:X}")
            continue
        blobs.append((f"Hero{i:02d}", s[want]))

    print(f"section 0x{want:X}")
    for name, b in blobs:
        print(f"  {name}\t{len(b)}")

    lo = min(len(b) for _, b in blobs)
    hi = max(len(b) for _, b in blobs)
    ref = blobs[0][1]

    pre = 0
    while pre < lo and all(b[pre] == ref[pre] for _, b in blobs):
        pre += 1
    suf = 0
    while suf < lo - pre and all(b[-1 - suf] == ref[-1 - suf] for _, b in blobs):
        suf += 1
    print(f"  sizes {lo}..{hi}  common_prefix={pre} (0x{pre:X})  common_suffix={suf}")

    # agreement over the overlapping head: how many bytes are identical in all 8
    same = sum(1 for i in range(lo) if all(b[i] == ref[i] for _, b in blobs))
    print(f"  head overlap={lo}  identical_bytes={same} ({100.0 * same / lo:.1f}%)")

    # where do the differences live? 1KB buckets over the overlap
    print("  differing bytes per 1KB bucket (head overlap only):")
    row = []
    for k in range(0, lo, 1024):
        d = sum(1 for i in range(k, min(k + 1024, lo))
                if not all(b[i] == ref[i] for _, b in blobs))
        row.append(f"{k // 1024}:{d}")
    for k in range(0, len(row), 8):
        print("    " + " ".join(row[k:k + 8]))

    print(f"  first 64 bytes of {blobs[0][0]}:")
    for k in range(0, 64, 16):
        print("    %04X  %s  |%s|" % (
            k, " ".join(f"{c:02X}" for c in ref[k:k + 16]),
            "".join(chr(c) if 32 <= c < 127 else "." for c in ref[k:k + 16])))


main()
