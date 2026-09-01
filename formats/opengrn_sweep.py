#!/usr/bin/env python3
"""Third-decoder corpus sweep: github.com/karolak6612/open-grn's
grn_unpack.unpack() against our grn_tagwalk decode, over every walkable
models.pak entry. Run from the workspace root:

    OPENGRN_TOOLS=<dir with grn_dump.py+grn_unpack.py> \
        python3 analysis/tools/formats/opengrn_sweep.py

Their MIT tools are RUN, never vendored, translated or adopted (the
clean-room rule; D-21's licence boundary) -- point OPENGRN_TOOLS at a
scratch copy and keep that copy out of every repo. One runtime dependency
of theirs: grn_dump.py reads its 64-byte signature from
<tools_root>/../src/format/grn_signature.inc, so the layout must be
<root>/tools/grn_*.py + <root>/src/format/grn_signature.inc. Also needs a
writable scratch dir for the per-entry slice: set OPENGRN_SLICE (default
tmp/opengrn/sweep_slice.grn).

Slice = entry bytes from magic_offset-0x40 (the signature); their framing
is anchored there. Compares COUNTS only -- names, geometry bytes and every
material->texture tuple were verified on the 15-entry sample (111/111,
2026-09-01) and the full sweep agreed on all counts. Also tallies the
track interpolation modes their decode exposes (row 1219: quad everywhere
on ordinary tracks), as a standing tripwire for the corpus's shape.

Baseline 2026-09-01: 4991/4993 walkable, their decoder 0 failures, ZERO
divergences in any field. A divergence here is a bug report against one of
the two decoders -- first question is always the tree shape (direct vs
subtree children), which is what the first sweep pass got wrong.
"""
import os
import struct
import sys
import time
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_TOOLS = os.environ.get("OPENGRN_TOOLS",
                        os.path.abspath(os.path.join(
                            _HERE, "../../../tmp/opengrn/tools")))
sys.path.insert(0, _TOOLS)
import grn_tagwalk as g  # noqa: E402
from grn_unpack import unpack  # noqa: E402

path = os.path.join(g.GAME, "pak", "models.pak")
size = os.path.getsize(path)
f = open(path, "rb")
entries = g.pak_index3(f)
slice_path = Path(os.environ.get(
    "OPENGRN_SLICE",
    os.path.abspath(os.path.join(_HERE, "../../../tmp/opengrn/sweep_slice.grn"))))

fields = ["n_bones", "n_meshes", "src_positions", "src_normals", "triangles",
          "n_materials", "mat_refs", "n_textures", "n_tracks"]
tally = {k: [0, 0] for k in fields}  # [agree, disagree]
mode_tally = {}
divergences = []
their_fail = []
walked = refused = 0
t0 = time.time()


def our_mesh(dirbuf, sec, nodes):
    T = lambda j: nodes[j]["tag"]
    R = lambda j: nodes[j]["rel"]
    meshes = []
    for j in range(len(nodes)):
        if T(j) != 0xCA5E0601:
            continue
        vt = g.child_with_tag(nodes, j, 0xCA5E0801)
        nt = g.child_with_tag(nodes, j, 0xCA5E0802)
        tt = g.child_with_tag(nodes, j, 0xCA5E0901)
        if vt == -1 or nt == -1 or tt == -1:
            continue
        span = lambda c: g.clip_span(nodes, c, len(dirbuf), sec)
        meshes.append((span(vt) // 12, span(nt) // 12, span(tt) // 24))
    return meshes


def our_materials(dirbuf, sec, nodes):
    kids = {j: g.direct_children(nodes, j) for j in range(len(nodes))}
    T = lambda j: nodes[j]["tag"]
    R = lambda j: nodes[j]["rel"]
    mats = []
    for j in range(len(nodes)):
        if T(j) != 0xCA5E0D00:
            continue
        d3 = [c for c in kids[j] if T(c) == 0xCA5E0D03]
        if d3:
            mats.append(struct.unpack_from("<I", dirbuf, sec + R(d3[0]) + 4)[0] - 1)
        else:
            mats.append(-1)
    return tuple(mats)


for i, (f0, off, f2) in enumerate(entries):
    kind = f0
    if kind not in (64, 65):
        continue
    tl = g.derive_length(entries, i, size)
    ok, mo, _ = g.classify(f, kind, off, tl)
    if not ok:
        refused += 1
        continue
    walked += 1
    f.seek(off + mo - 0x40)
    blob = f.read(tl - mo + 0x40)
    slice_path.write_bytes(blob)
    name = g.read_name(f, off)
    try:
        theirs = unpack(slice_path)
        if "error" in theirs:
            raise RuntimeError(theirs["error"])
        sec = theirs["sections"][1]
    except Exception as exc:  # noqa: BLE001
        their_fail.append((name, str(exc)[:80]))
        continue

    f.seek(off)
    buf = f.read(tl)
    sec_off = mo + g.SECTION_OFF_DELTA
    nodes = g.clip_directory(buf, sec_off)
    T = lambda j: nodes[j]["tag"]
    checks = {}
    if kind == 64:
        tbones = sec.get("bones", [])
        tmeshes = [m for m in sec.get("meshes", []) if m.get("vertex_count")]
        tmat = [(m["diffuse_texture_index"] if m["diffuse_texture_index"] is not None
                 else -1) for m in sec.get("materials", [])]
        om = our_mesh(buf, sec_off, nodes)
        checks["n_bones"] = (len(tbones), sum(1 for j in range(len(nodes)) if T(j) == 0xCA5E0506))
        checks["n_meshes"] = (len(tmeshes), len(om))
        checks["src_positions"] = (sum(m[0] for m in om), sum(m[0] for m in om))
        checks["src_positions"] = (sum(m["vertex_count"] for m in tmeshes),
                                   sum(m[0] for m in om))
        checks["src_normals"] = (sum(len(m["normals"]) for m in tmeshes),
                                 sum(m[1] for m in om))
        checks["triangles"] = (sum(m["triangle_count"] for m in tmeshes),
                               sum(m[2] for m in om))
        checks["n_materials"] = (len(tmat),
                                 sum(1 for j in range(len(nodes)) if T(j) == 0xCA5E0D00))
        checks["mat_refs"] = (tuple(tmat), our_materials(buf, sec_off, nodes))
        checks["n_textures"] = (len(sec.get("textures", [])),
                                sum(1 for j in range(len(nodes)) if T(j) == 0xCA5E0301))
    else:
        anim = sec.get("animation") or {}
        ttracks = anim.get("tracks", [])
        otracks = [j for j in range(len(nodes)) if T(j) == 0xCA5E1204]
        checks["n_tracks"] = (len(ttracks), len(otracks))
        for t in ttracks:
            key = (t.get("position_interp_mode"), t.get("quaternion_interp_mode"),
                   t.get("scale_shear_interp_mode"))
            mode_tally[key] = mode_tally.get(key, 0) + 1
    for field, (tv, ov) in checks.items():
        if tv == ov:
            tally[field][0] += 1
        else:
            tally[field][1] += 1
            if len(divergences) < 25:
                divergences.append((name, field, tv, ov))

elapsed = time.time() - t0
print(f"entries walked={walked} refused={refused} elapsed={elapsed:.0f}s")
print(f"their-decoder failures: {len(their_fail)}")
for name, err in their_fail[:10]:
    print(f"  {name}: {err}")
print("per-field agreement (theirs vs our grn_tagwalk):")
for k in fields:
    a, dd = tally[k]
    if a + dd:
        print(f"  {k:16s} {a}/{a+dd} agree{'' if dd == 0 else f'  {dd} DIVERGE'}")
print(f"divergences (capped 25):")
for name, field, tv, ov in divergences:
    print(f"  {name} {field}: theirs={tv} ours={ov}")
print("track interpolation modes (pos, quat, scale) -> tracks:")
for k in sorted(mode_tally, key=mode_tally.get, reverse=True):
    print(f"  {k}: {mode_tally[k]}")
