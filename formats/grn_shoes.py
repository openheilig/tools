#!/usr/bin/env python3
"""Historical private-prototype helper: emit a Seraphim `shoes` draw batch.

This records the 2026-08-30 Bevy-export investigation, not the current
production model renderer's status. It reads a user's own retail archives
and writes private converted assets; none of that output may be published.

The exported OBJ already carries every merged vertex's world position, normal
and UV (each surface duplicates the full merged buffers; only faces differ),
including the shoe corners, unreferenced. The missing data is the 270 shoe
triangles' corner lists and the boots image:

  1. decode both Mesh nodes' position/normal/triangle arrays and the six
     group records (0xCA5E0E02/04/06) straight from models.pak bytes;
  2. rebuild each mesh's (position, normal) PAIR table in triangle-scan
     order -- the space the group records' corner ids index (mesh 1 has
     exactly 2063 pairs; its head group's max corner is 2062);
  3. map GRN -> world with the port's own axis convention, world = (x, z,
     -y) (models.gd GRN_TO_GODOT, no scale, no translation), and snap every
     corner to its OBJ vertex;
  4. VALIDATE by reconstructing the `legs` group's faces from the same path
     and comparing them to the OBJ's tex_1 faces exactly;
  5. append the shoe faces to the OBJ as group `tex_10` and decode
     `Sera_boots.tga` from texture.pak to tex_10.png.

    ./grn_shoes.py MODELS_PAK TEXTURE_PAK SERAPHIM_OBJ BEVY_TEXTURE_DIR
"""
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grn_tagwalk import pak_index3, derive_length, read_name  # noqa: E402
from export_terrain import decode_tex  # noqa: E402

SECTION_OFF_MESH = 1634
TAG_MESH = 0xCA5E0601
TAG_MESH_VERTICES = 0xCA5E0801
TAG_MESH_TRIANGLES = 0xCA5E0901
TAG_MODEL_GROUP = 0xCA5E0E02
TAG_MODEL_GROUP_COUNT = 0xCA5E0E04
TAG_MODEL_GROUP_TRIS = 0xCA5E0E06
GROUP_TRI_STRIDE = 16
VEC3_STRIDE = 12
ENTRY = 661  # SERAPHIM
LEGS_TRIS, SHOES_TRIS = 390, 270  # measured group triangle counts


def read_entry(path, want=None, index=None):
    """pak record is (kind, offset, flags); the payload STARTS with the
    64-byte entry name, and the true length is derived from the next
    record's offset (derive_length)."""
    with open(path, "rb") as f:
        entries = pak_index3(f)
        size_total = os.fstat(f.fileno()).st_size
        if index is not None:
            hits = [index]
        else:
            hits = []
            for i in range(len(entries)):
                off = entries[i][1]
                f.seek(off)
                if want.lower() in read_name(f, off).lower():
                    hits.append(i)
                    break
            if not hits:
                raise SystemExit(f"entry {want!r} not found in {path}")
        i = hits[0]
        _kind, off, _flags = entries[i]
        size = derive_length(entries, i, size_total)
        name = read_name(f, off)
        f.seek(off)
        return f.read(size), name


def directory(buf):
    n = struct.unpack_from("<I", buf, SECTION_OFF_MESH)[0]
    base = SECTION_OFF_MESH + 16
    return [struct.unpack_from("<III", buf, base + j * 12) for j in range(n)]


def span(nodes, j, buf):
    r = nodes[j][1]
    end = len(buf) - SECTION_OFF_MESH
    for k in range(j + 1, len(nodes)):
        if nodes[k][1] > r:
            return nodes[k][1] - r
    return end - r


def child(nodes, j, tag):
    """Flat descendant-window scan, the port's _child_with_tag semantics:
    a subtree's nodes are contiguous and children counts the whole
    subtree, so a flat scan finds nodes at any depth."""
    last = min(j + 1 + nodes[j][2], len(nodes))
    for k in range(j + 1, last):
        if nodes[k][0] == tag:
            return k
    return -1


def decode(buf):
    nodes = directory(buf)
    meshes, groups = [], []
    for j in range(len(nodes)):
        if nodes[j][0] != TAG_MESH:
            continue
        vj = child(nodes, j, TAG_MESH_VERTICES)
        tj = child(nodes, j, TAG_MESH_TRIANGLES)
        if vj < 0 or tj < 0:
            continue
        v_off = SECTION_OFF_MESH + nodes[vj][1]
        n_pos = span(nodes, vj, buf) // VEC3_STRIDE
        pos = np.array(struct.unpack_from(f"<{n_pos*3}f", buf, v_off)).reshape(n_pos, 3)
        t_off = SECTION_OFF_MESH + nodes[tj][1]
        n_face = span(nodes, tj, buf) // 24
        tris = np.array(struct.unpack_from(f"<{n_face*6}I", buf, t_off)).reshape(n_face, 6)
        # (position, normal) PAIR table in scan order -- the space the
        # group records' corner ids index.
        pairs, pair_id, seen = [], [], {}
        for fi in range(n_face):
            for corner in range(3):
                key = (int(tris[fi, corner]), int(tris[fi, corner + 3]))
                if key not in seen:
                    seen[key] = len(pairs)
                    pairs.append(key)
                pair_id.append(seen[key])
        meshes.append({"pos": pos, "faces": n_face, "pairs": pairs,
                       "pair_id": pair_id})
    for j in range(len(nodes)):
        if nodes[j][0] != TAG_MODEL_GROUP:
            continue
        base = SECTION_OFF_MESH + nodes[j][1]
        mesh_idx, mat = struct.unpack_from("<II", buf, base)
        cj = child(nodes, j, TAG_MODEL_GROUP_COUNT)
        tris = -1
        if cj >= 0:
            tris = struct.unpack_from("<I", buf, SECTION_OFF_MESH + nodes[cj][1] + 4)[0]
        recs = []
        tj = child(nodes, j, TAG_MODEL_GROUP_TRIS)
        if tj >= 0:
            q = SECTION_OFF_MESH + nodes[tj][1]
            cnt = struct.unpack_from("<I", buf, q)[0]
            for t in range(cnt):
                recs.append(struct.unpack_from("<4I", buf, q + 4 + t * GROUP_TRI_STRIDE))
        groups.append({"mesh": mesh_idx, "mat": mat, "tris": tris, "recs": recs})
    return meshes, groups


def parse_obj(path):
    verts, groups, cur = [], {}, None
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            verts.append(tuple(map(float, p[1:4])))
        elif p[0] == "usemtl":
            cur = p[1]
            groups.setdefault(cur, [])
        elif p[0] == "f" and cur is not None:
            groups[cur].append(tuple(int(x.split("/")[0]) for x in p[1:4]))
    return verts, groups


def main():
    models_pak, tex_pak, obj_path, tex_dir = sys.argv[1:5]
    buf, name = read_entry(models_pak, index=ENTRY)
    print(f"entry {name} bytes={len(buf)}")
    meshes, groups = decode(buf)
    for mi, m in enumerate(meshes):
        print(f"  mesh {mi}: faces={m['faces']} positions={len(m['pos'])} pairs={len(m['pairs'])}")

    by_count = {g["tris"]: g for g in groups if g["tris"] > 0}
    shoes, legs = by_count[SHOES_TRIS], by_count[LEGS_TRIS]

    def corner_pos(group):
        m = meshes[group["mesh"]]
        out = []
        for r in group["recs"]:
            out.append([m["pos"][m["pairs"][c][0]] for c in r[1:4]])
        return out

    # world = (x, z, -y) -- models.gd GRN_TO_GODOT, measured axis swap
    to_world = lambda p: (p[0], p[2], -p[1])

    verts, obj_groups = parse_obj(obj_path)
    V = np.array(verts)
    print(f"OBJ: {len(verts)} verts, groups={sorted(obj_groups)}")

    # VALIDATION: rebuild the legs faces and compare with the OBJ's tex_1.
    leg_faces = obj_groups["tex_1"]
    rebuilt = []
    for tri in corner_pos(legs):
        ids = []
        for p in tri:
            w = to_world(p)
            d = np.sqrt(((V - np.array(w)) ** 2).sum(1))
            ids.append(int(d.argmin()) + 1)
            assert d[ids[-1] - 1] < 0.02, f"leg corner snap failed: {d[ids[-1]-1]:.4f}"
        rebuilt.append(tuple(ids))
    match = sum(1 for f in rebuilt if f in set(leg_faces))
    print(f"legs validation: {match}/{len(leg_faces)} faces reproduced exactly")
    assert match == len(leg_faces), "legs reconstruction mismatch -- stop"

    # shoes faces
    shoe_faces = []
    for tri in corner_pos(shoes):
        ids = []
        for p in tri:
            w = to_world(p)
            d = np.sqrt(((V - np.array(w)) ** 2).sum(1))
            vi = int(d.argmin()) + 1
            assert d[vi - 1] < 0.02, f"shoe corner snap failed: {d[vi-1]:.4f}"
            ids.append(vi)
        shoe_faces.append(tuple(ids))

    with open(obj_path, "a") as f:
        f.write("g tex_10\nusemtl tex_10\n")
        for a, b, c in shoe_faces:
            f.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
    print(f"appended {len(shoe_faces)} shoe faces to {obj_path}")

    tbuf, tname = read_entry(tex_pak, want="Sera_boots")
    w, h, rgba = decode_tex(tbuf, 0, len(tbuf))
    from PIL import Image
    img = Image.frombytes("RGBA", (w, h), bytes(rgba))
    out = os.path.join(tex_dir, "tex_10.png")
    img.save(out)
    print(f"texture: {tname} {w}x{h} -> {out}")


if __name__ == "__main__":
    main()
