#!/usr/bin/env python3
"""Recover the balance.bin field map (key name -> file offset) from Sacred.exe.

balance.bin carries no index and no string table: the key NAMES live in the exe
(a NUL-padded string pool at VA 0x95b790..0x95ca78), the VALUES live in the
file, and only hardcoded offsets bind them (RESEARCH §13.6).

The bridge is the exe's TEXT-config parser.  It is one contiguous routine of
~62-byte blocks, one per key, shaped:

    push offset "ProzAW"      <- the only reference to that string in the image
    push esi
    call <token compare>
    test eax,eax / jz next
    push 0x3d ('=')           <- it parses "Key=value" lines
    push eax
    call strchr
    ...
    fstp [0xad4690]           <- ... and stores into a GLOBAL

Those globals are the in-memory image of balance.bin, so
    file_offset = global_VA - BASE
with BASE fixed by any known key.  Verified against six independently measured
anchors (skilllearn1=780, ProzAW/HP/Dmg/Res/Exp = 1812/1836/1860/1884/1908).

ponytail: byte-pattern scan, no disassembler.  A real decoder would be correct
on every block; this one resolves 354/379 and names the 25 it misses, which is
enough to read the file.  Reach for capstone only if those 25 start mattering.
"""
import json
import struct
import sys

EXE = "windows-disc/eng/extracted/app/Sacred.exe"
BIN = "install/bin/balance.bin"
POOL_VA, POOL_END, IMAGE_BASE = 0x95B790, 0x95CA78, 0x400000
BASE = 0xAD448C  # global VA of balance.bin offset 0; pinned by skilllearn1

# store-to-global forms, longest prefix first so 0xa3 can't shadow 0x89 0x0d
DIRECT = [b"\xd9\x1d", b"\x89\x0d", b"\x89\x15", b"\x88\x15", b"\x89\x35",
          b"\x89\x3d", b"\xa3", b"\xa2"]
# fallback: array keys load the base into a register / push it instead
REG = [b"\xb8", b"\xb9", b"\xba", b"\xbb", b"\xbd", b"\xbe", b"\xbf", b"\x68"]

# List keys whose parser blocks use indexed stores, so no fixed opcode prefix
# matches.  Recovered by scanning the whole block for in-range immediates and
# keeping ONLY those the Linux ELF votes for at its own base (0x8b8941c).
# That vote also refuted a tempting 12-byte-stride reading of 4900..4972.
EXTRA = {"PriceBoni:": 544, "PriceSlot:": 588, "PriceAwVw:": 620, "DAEM": 804,
         "inventory": 1444, "rare": 2528, "RarePositiveList": 4900}


def key_pool(exe):
    """The 379 balance key names, as (VA, name)."""
    d = exe[POOL_VA - IMAGE_BASE:POOL_END - IMAGE_BASE]
    out, i = [], 0
    while i < len(d):
        if d[i] == 0:
            i += 1
            continue
        z = d.find(b"\0", i)
        out.append((POOL_VA + i, d[i:z].decode("latin1")))
        i = z
    return out


def scan(exe, forms, at, span=110):
    for p in range(at, at + span):
        for pre in forms:
            if exe[p:p + len(pre)] == pre:
                t = struct.unpack_from("<I", exe, p + len(pre))[0]
                if BASE <= t < BASE + 24328:
                    return t - BASE
    return None


def build(exe):
    names = dict(key_pool(exe))
    out = {}
    for off in range(len(exe) - 4):
        va = struct.unpack_from("<I", exe, off)[0]
        n = names.get(va)
        if n is None or n in out:
            continue
        o = scan(exe, DIRECT, off + 4) or scan(exe, REG, off + 4)
        if o is not None:
            out[n] = o
    out.update(EXTRA)
    return out, [n for n in names.values() if n not in out]


def kind(dw):
    """int vs float, by which reading is plausible. Ambiguous -> 'int'."""
    f = struct.unpack("<f", struct.pack("<I", dw))[0]
    if 0x38000000 < dw < 0x50000000 and abs(f) > 1e-5:
        return "f32"
    return "i32"


def main():
    exe = open(EXE, "rb").read()
    dat = open(BIN, "rb").read()
    m, miss = build(exe)

    anchors = {"skilllearn1": 780, "ProzAW": 1812, "ProzHP": 1836,
               "ProzDmg": 1860, "ProzRes": 1884, "ProzExp": 1908}
    bad = [k for k, v in anchors.items() if m.get(k) != v]
    if bad:
        sys.exit("ANCHOR MISMATCH: %s -- map is wrong, do not use" % bad)

    rows = []
    for n, o in sorted(m.items(), key=lambda kv: kv[1]):
        dw = struct.unpack_from("<I", dat, o)[0]
        t = kind(dw)
        v = round(struct.unpack("<f", struct.pack("<I", dw))[0], 6) if t == "f32" \
            else struct.unpack("<i", struct.pack("<I", dw))[0]
        rows.append((n, o, t, v, dw))

    print("key\toffset\ttype\tvalue\traw")
    for n, o, t, v, dw in rows:
        print("%s\t%d\t%s\t%s\t0x%08x" % (n, o, t, v, dw))
    print("# %d/%d keys mapped; anchors 6/6 OK" % (len(m), len(m) + len(miss)),
          file=sys.stderr)
    print("# unmapped (%d): %s" % (len(miss), " ".join(miss)), file=sys.stderr)
    json.dump(m, open("analysis/balance-keymap.json", "w"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
