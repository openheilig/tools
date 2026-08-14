#!/usr/bin/env python3
"""save_patch.py -- patch the hero position in a Sacred save (game01.pak).

    save_patch.py IN.pak OUT.pak X Y

X/Y are PPOS units (the `sys fps` overlay's PPOS[x,y,z]).  The save stores
the hero's world position in section 0xA0's head record as fixed-point u32s
at +44 (x) and +48 (y), scale ~= 53.6741 wp per PPOS unit (measured 06-02,
two anchors: PPOS (3215,2554) <-> wp (172561,137088) and PPOS (3209,2562)
<-> wp (172244,137495) across the save-A -> save-B diff).  +42 carries a u16
(wp0, 2579->2653 on a 10-cell walk -- terrain-height candidate) that this
tool reports but does NOT patch; the engine is observed to accept the load
with it stale (see findings row).

Container: "AMS\x1b" header, 12-byte section table at 0x100 (type, offset,
size), compressed sections start with 0xBAADC0DE + csz + 24 bytes of payload
header then zlib data (same shape as community/unpack-tools pax, see
pax_diff.py).  Only 0xA0 is touched; every later section's offset is shifted
and the table rewritten.  No file-level checksum exists in the container
(verified: hand-rebuilt pak loads and plays).

ponytail: patching position is the sanctioned 06-02 transport (no ptrace,
no /proc/pid/mem -- the save is a file, the engine itself re-reads it).
"""
import struct
import sys
import zlib

TABLE, ENTRY, COMPRESSED, PAYLOAD = 0x100, 12, 0xBAADC0DE, 0x20
SCALE = 53.667  # wp units per PPOS unit; interval intersection [53.6653, 53.6712]
                # from two measured anchors (06-02): PPOS (3215,2554) <-> wp
                # (172561,137088), PPOS (3209,2562) <-> wp (172244,137495)

HERO_SEC = 0xA0
OFF_Z, OFF_X, OFF_Y = 42, 44, 48


def read_pak(path):
    d = open(path, "rb").read()
    n = int.from_bytes(d[4:8], "little")
    secs = []
    for i in range(n):
        e = TABLE + i * ENTRY
        t = int.from_bytes(d[e:e + 4], "little")
        off = int.from_bytes(d[e + 4:e + 8], "little")
        usz = int.from_bytes(d[e + 8:e + 12], "little")
        if t == 0:
            continue
        if int.from_bytes(d[off:off + 4], "little") == COMPRESSED:
            csz = int.from_bytes(d[off + 4:off + 8], "little")
            secs.append([i, t, True, bytearray(zlib.decompress(d[off + PAYLOAD:off + PAYLOAD + csz]))])
        else:
            secs.append([i, t, False, bytearray(d[off:off + usz])])
    return d[:TABLE], n, secs


def write_pak(path, head, table_slots, secs):
    out = bytearray()
    out += head
    table_size = table_slots * ENTRY
    off = TABLE + table_size
    table = bytearray(table_size)
    blobs = bytearray()
    for slot, t, was_compressed, payload in secs:
        if not payload:
            # empty section: engine keys on usz==0; keep the offset away from
            # any compressed-section magic so naive readers don't misparse it
            struct.pack_into("<III", table, slot * ENTRY, t, 0, 0)
            continue
        if was_compressed:
            comp = zlib.compress(payload, 9)
            blob = struct.pack("<II", COMPRESSED, len(comp)) + b"\0" * (PAYLOAD - 8) + comp
        else:
            blob = bytes(payload)
        struct.pack_into("<III", table, slot * ENTRY, t, off, len(payload))
        blobs += blob
        off += len(blob)
    out += table
    out += blobs
    with open(path, "wb") as fh:
        fh.write(out)


def main(argv):
    if len(argv) != 5:
        raise SystemExit(__doc__)
    src, dst, x, y = argv[1], argv[2], int(argv[3]), int(argv[4])
    head, table_slots, secs = read_pak(src)
    for slot, t, was_compressed, payload in secs:
        if t != HERO_SEC:
            continue
        old_z = struct.unpack_from("<H", payload, OFF_Z)[0]
        old_x = struct.unpack_from("<I", payload, OFF_X)[0]
        old_y = struct.unpack_from("<I", payload, OFF_Y)[0]
        new_x, new_y = round(x * SCALE), round(y * SCALE)
        struct.pack_into("<I", payload, OFF_X, new_x)
        struct.pack_into("<I", payload, OFF_Y, new_y)
        print(f"section 0x{t:02X}: wp ({old_x},{old_y}) -> ({new_x},{new_y}) "
              f"[PPOS ~({old_x/SCALE:.1f},{old_y/SCALE:.1f}) -> ({x},{y})] "
              f"wp0={old_z} left as-is")
        break
    else:
        raise SystemExit(f"no section 0x{HERO_SEC:02X} in {src}")
    write_pak(dst, head, table_slots, secs)
    print(f"wrote {dst}")


if __name__ == "__main__":
    main(sys.argv)
