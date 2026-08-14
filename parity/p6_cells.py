#!/usr/bin/env python3
"""p6_cells.py -- dump region cell classes (world coords) around a point.

Usage: p6_cells.py CX CY [RADIUS_SECTORS]

Prints, for every region whose grid covers the RADIUS_SECTORS neighbourhood
around the sector holding cell (CX,CY): the region's anchor/size, then one
line per non-EMPTY cell class of interest (WALL=1, FLOOR=2, DOOR=9, STEP=10)
as `class CLS at WX,WY` lines, plus an ASCII map of the classes in a
+/-16-cell window around (CX,CY) so the door/step geometry can be read
against a capture.

Built for plan 06-02's pixel-to-cell calibration: the retail fire frame
shows the player near a building's door; this tool says which world cells
the door and its steps are, through verify_ref.py's INDEPENDENT region
parser (never a translation of godot-port/sacred.gd).
"""

import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_ref  # noqa: E402

CLASS_CHARS = {0: ".", 1: "#", 2: " ", 9: "D", 0xA: "s"}


def sector_stream(wf, by_key, gx, gy):
    e = by_key.get(gy * 100 + gx)
    if e is None:
        return b""
    off, csz, dsz = e
    wf.seek(off)
    stream = zlib.decompress(wf.read(csz))
    if len(stream) != dsz:
        raise SystemExit(f"p6_cells: sector {gx},{gy} decompressed short")
    return stream


def main():
    cx0, cy0 = int(sys.argv[1]), int(sys.argv[2])
    rad = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    gs, ge = cx0 // 64, cy0 // 64
    with open(f"{verify_ref.GAME}/world/sectors.keyx", "rb") as kf, \
            open(f"{verify_ref.GAME}/world/sectors.wldx", "rb") as wf:
        kf.seek(4)
        n, gw, gh = struct.unpack("<III", kf.read(12))
        kf.seek(verify_ref.KEY_HDR)
        keys = kf.read(n * verify_ref.KEY_REC)
        by_key = {}
        for i in range(n):
            b = i * verify_ref.KEY_REC
            by_key[struct.unpack_from("<I", keys, b + 32)[0]] = struct.unpack_from(
                "<III", keys, b + 236)[:2] + (struct.unpack_from("<I", keys, b + 264)[0],)

        # class_at for the ASCII window: first region covering a cell wins,
        # in ascending sector-key then table order -- mirroring Walkable.
        window = {}
        counts = {}
        for gy in range(ge - rad, ge + rad + 1):
            for gx in range(gs - rad, gs + rad + 1):
                stream = sector_stream(wf, by_key, gx, gy)
                for (ax, ay, w, h, grid) in verify_ref.region_list(stream, gx, gy):
                    print(f"region\tanchor={ax},{ay}\tsize={w}x{h}\tsector={gx},{gy}")
                    for ly in range(h):
                        for lx in range(w):
                            cls = verify_ref.region_cell_class(grid, w, h, lx, ly)
                            if cls == 0:
                                continue
                            wx, wy = ax + lx, ay + ly
                            counts[cls] = counts.get(cls, 0) + 1
                            if abs(wx - cx0) <= 16 and abs(wy - cy0) <= 16 \
                                    and (wx, wy) not in window:
                                window[(wx, wy)] = cls
        print("class_counts\t" + "\t".join(
            f"{c}={counts[c]}" for c in sorted(counts)))
        print(f"map_window\tcentre={cx0},{cy0}\t+/-16 cells\t"
              f"('#'=wall ' '=floor 'D'=door 's'=step '.'=no-region/empty)")
        for wy in range(cy0 - 16, cy0 + 17):
            row = []
            for wx in range(cx0 - 16, cx0 + 17):
                row.append(CLASS_CHARS.get(window.get((wx, wy), 0), "?"))
            print(f"{wy:5d} " + "".join(row))


if __name__ == "__main__":
    main()
