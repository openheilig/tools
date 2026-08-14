#!/usr/bin/env python3
"""Composite exported cells into a PPM -- validates the pipeline without Godot.

  ./preview_terrain.py --at 128,64 --n 10 | magick - preview.png
"""
import argparse, array, json, os, sys

HW, HH = 128, 64  # ponytail: matches the art at 1 cell = 128x64 px; textures hold a
                  # finer diamond lattice, so neighbours overlap ~2x. Revisit if a
                  # tile's detail ever needs to line up per-cell.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(os.path.dirname(__file__), "../../godot-port/data"))
    ap.add_argument("--at", default="128,64", help="cell x,y in the exported grid")
    ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args()

    m = json.load(open(f"{a.data}/manifest.json"))
    T, C = m["tile"], m["cols"]
    cells = array.array("i")
    cells.frombytes(open(f"{a.data}/cells.bin", "rb").read())
    tex = open(f"{a.data}/tex.bin", "rb").read()
    S = T * T * 4
    x0, y0 = (int(v) for v in a.at.split(","))
    N = a.n
    W, H = N * 2 * HW + 2 * T, N * 2 * HH + 2 * T
    buf = bytearray(b"\x20" * (W * H * 3))

    def blit(layer, px, py):
        o = layer * S
        for y in range(T):
            ty = py + y
            if not 0 <= ty < H:
                continue
            row = o + y * T * 4
            for x in range(T):
                tx = px + x
                if not 0 <= tx < W or tex[row + x * 4 + 3] < 128:
                    continue
                d = (ty * W + tx) * 3
                buf[d:d + 3] = tex[row + x * 4:row + x * 4 + 3]

    # painter's order along the iso depth axis
    for cx, cy in sorted(((x, y) for y in range(N) for x in range(N)), key=sum):
        layer = cells[(y0 + cy) * C + x0 + cx]
        if layer >= 0:
            blit(layer, (cx - cy) * HW + W // 2 - T // 2, (cx + cy) * HH + T // 2)

    sys.stdout.buffer.write(b"P6\n%d %d\n255\n" % (W, H) + bytes(buf))


if __name__ == "__main__":
    main()
