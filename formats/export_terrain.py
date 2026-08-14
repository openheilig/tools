#!/usr/bin/env python3
"""Export one region of the Sacred world for the Godot terrain viewer.

Personal-use interoperability work on legally-owned media. Output stays local.

  ./export_terrain.py --center 50,50 --radius 1 --out ../../godot-port/data

Writes:
  cells.bin     int32 layer index per cell, row-major, -1 = empty
  tex.bin       layers * 256*256*4 bytes RGBA8
  manifest.json grid size, layer count, tile size
"""
import argparse, json, os, struct, zlib, array

HDR, IDX = 256, 12
SECT, TILE = 64, 256          # cells per sector edge, texture edge


def blob_index(buf):
    n = struct.unpack_from("<I", buf, 4)[0]
    return [struct.unpack_from("<III", buf, HDR + i * IDX) for i in range(n)]


def decode_tex(buf, off, size):
    """texture.pak payload -> (w, h, RGBA8 bytes). 80-byte header, zlib ARGB4444."""
    w, h = struct.unpack_from("<HH", buf, off + 32)
    rt = buf[off + 36]
    raw = zlib.decompressobj().decompress(buf[off + 80:off + 80 + size])
    assert rt == 4 and len(raw) == w * h * 2, (rt, len(raw), w * h * 2)
    px = array.array("H")
    px.frombytes(raw)
    out = bytearray(w * h * 4)
    for i, p in enumerate(px):
        out[i * 4 + 0] = ((p >> 8) & 0xF) * 17   # r
        out[i * 4 + 1] = ((p >> 4) & 0xF) * 17   # g
        out[i * 4 + 2] = (p & 0xF) * 17          # b
        out[i * 4 + 3] = ((p >> 12) & 0xF) * 17  # a
    return w, h, bytes(out)


def sectors(wldx, wanted):
    """Yield (gx, gy, WldxEntry blob) for wanted {(gx,gy)}; streams are sequential."""
    pos, left = HDR, set(wanted)
    while pos < len(wldx) - 2 and left:
        if wldx[pos:pos + 2] != b"\x78\x9c":
            pos += 1
            continue
        z = zlib.decompressobj()
        chunk = wldx[pos:pos + 400000]
        try:
            d = z.decompress(chunk)
        except zlib.error:
            pos += 1
            continue
        pos += len(chunk) - len(z.unused_data)
        name = d[:32].split(b"\x00")[0].decode("latin1").strip()
        try:
            gx, gy = (int(v) for v in name.split()[1].split(","))
        except (IndexError, ValueError):
            continue
        if (gx, gy) in left:
            left.discard((gx, gy))
            yield gx, gy, d[32:32 + SECT * SECT * 32]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--center", default="50,50")
    ap.add_argument("--radius", type=int, default=1)
    ap.add_argument("--game", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../install")))
    ap.add_argument("--out", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../godot-port/data")))
    a = ap.parse_args()

    cx, cy = (int(v) for v in a.center.split(","))
    gxs = range(cx - a.radius, cx + a.radius + 1)
    gys = range(cy - a.radius, cy + a.radius + 1)
    wanted = {(x, y) for x in gxs for y in gys}

    tiles = open(f"{a.game}/pak/tiles.pak", "rb").read()
    texpak = open(f"{a.game}/pak/texture.pak", "rb").read()
    wldx = open(f"{a.game}/world/sectors.wldx", "rb").read()
    tix, xix = blob_index(tiles), blob_index(texpak)

    cols, rows = len(gxs) * SECT, len(gys) * SECT
    cells = array.array("i", [-1]) * (cols * rows)
    layer_of, blobs = {}, []

    for gx, gy, blob in sectors(wldx, wanted):
        ox, oy = (gx - min(gxs)) * SECT, (gy - min(gys)) * SECT
        for i in range(SECT * SECT):
            tid = struct.unpack_from("<I", blob, i * 32)[0]
            if tid >= len(tix):
                continue
            _, toff, _ = tix[tid]
            texid = struct.unpack_from("<I", tiles, toff + 0x20)[0]
            # ponytail: orientation (tiles.pak +0x24, 0..17) ignored -- add UV rotation when it looks wrong
            if texid not in layer_of:
                if texid >= len(xix):
                    continue
                _, xoff, xsz = xix[texid]
                w, h, rgba = decode_tex(texpak, xoff, xsz)
                assert (w, h) == (TILE, TILE), (texid, w, h)
                layer_of[texid] = len(blobs)
                blobs.append(rgba)
            cells[(oy + i // SECT) * cols + ox + i % SECT] = layer_of[texid]

    os.makedirs(a.out, exist_ok=True)
    open(f"{a.out}/cells.bin", "wb").write(cells.tobytes())
    with open(f"{a.out}/tex.bin", "wb") as f:
        for b in blobs:
            f.write(b)
    json.dump({"cols": cols, "rows": rows, "layers": len(blobs), "tile": TILE,
               "origin": [min(gxs) * SECT, min(gys) * SECT]},
              open(f"{a.out}/manifest.json", "w"))
    print(f"{cols}x{rows} cells, {len(blobs)} textures, "
          f"{len(blobs) * TILE * TILE * 4 / 1e6:.0f} MB -> {a.out}")


if __name__ == "__main__":
    main()
