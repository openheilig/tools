#!/usr/bin/env python3
"""Extract the hero's skinned strips across idle frames of an apitrace.

Retail draws the world through P · MV with GL matrix state persisting across
windows and frames; sprite passes run under an identity modelview with
already-screen-space vertices, 3D passes under the iso camera. This script
streams one continuous call range tracking the matrix state exactly
(glMatrixMode, glLoadIdentity, glLoadMatrixf, glMultMatrixf, glOrtho,
glTranslated, glScaled), projects every vertex to screen pixels (viewport
1024x768), and per glClear-delimited frame keeps the strips inside the hero's
screen box that CHANGE between frames (the idle animation).

Usage:
  hero_cycle.py <trace> <windows.txt> <first_idx> <count> <out.json>
windows.txt rows: <world_idx> <ortho_call> <draws>; world = draws >= MIN_DRAWS.
"""

import io
import json
import pickle
import struct
import subprocess
import sys

MIN_DRAWS = 500
HERO_BOX = (430.0, 230.0, 620.0, 420.0)
GL_PROJECTION = 5889

IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def mat_mul(a, b):
    """column-major 4x4: a @ b"""
    return [sum(a[c * 4 + r] * b[r * 4 + c2] for r in range(4))
            for c2 in range(4) for c in range(4)]


def transform(m, v):
    return (
        m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12],
        m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13],
        m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14],
        m[3] * v[0] + m[7] * v[1] + m[11] * v[2] + m[15],
    )


def project(clip):
    x, y, z, w = clip
    if w == 0:
        return None
    ndc_x, ndc_y = x / w, y / w
    wx = (ndc_x + 1) * 0.5 * 1024.0
    wy = (1 - (ndc_y + 1) * 0.5) * 768.0
    return wx, wy


def decode(b, size, typ, stride, count):
    base = {5126: 'f', 5125: 'I', 5124: 'i', 5121: 'B', 5123: 'H', 5120: 'b'}.get(typ)
    if base is None:
        return None
    isz = struct.calcsize(base)
    st = stride if stride else isz * size
    try:
        return [struct.unpack_from('<' + base * size, b, i * st) for i in range(count)]
    except Exception:
        return None


def window_events(trace, a, b):
    out = subprocess.run(["apitrace", "pickle", "--calls=%d-%d" % (a, b), trace],
                         capture_output=True)
    events = []
    fh = io.BytesIO(out.stdout)
    while True:
        try:
            events.append(pickle.load(fh))
        except EOFError:
            break
    return events


def main():
    trace, windows_path, first, count, out_path = sys.argv[1:6]
    first, count = int(first), int(count)
    rows = []
    for ln in open(windows_path):
        p = ln.split()
        if len(p) == 3:
            rows.append((int(p[0]), int(p[1]), int(p[2])))
    rows = [r for r in rows if r[2] >= MIN_DRAWS]
    pos = next((i for i, r in enumerate(rows) if r[0] >= first), None)
    if pos is None or pos + count > len(rows):
        print("hero_cycle: not enough windows", file=sys.stderr)
        return 1
    sel = rows[pos:pos + count]
    all_ortho = [r[1] for r in rows]
    i0 = rows.index(sel[0])
    back = min(3, i0)
    range_start = all_ortho[i0 - back] if back else sel[0][1]
    range_end = (all_ortho[i0 + count] - 1) if i0 + count < len(all_ortho) else sel[-1][1] + 60000

    ev = window_events(trace, range_start, range_end)
    ptrs = {}
    tex = None
    proj = None
    mode = None            # unknown until the first glMatrixMode in range
    mv = None              # exact modelview state
    frames = []
    cur = None
    dbg = {"decoded": 0, "onscreen": 0}
    for e in ev:
        name = e[2]
        d = dict(e[3]) if e[3] else {}
        if name == 'glClear':
            if cur is not None:
                print("hero_cycle: dbg frame (clear@%d) decoded=%d onscreen=%d inbox=%d" % (
                    e[0], dbg["decoded"], dbg["onscreen"], len(cur["strips"])), flush=True)
            frames.append(cur if cur else {"clear_call": e[0], "strips": []})
            cur = {"clear_call": e[0], "strips": []}
            dbg["decoded"] = 0
            dbg["onscreen"] = 0
            continue
        if name == 'glBindTexture':
            tex = d.get('texture')
        elif name == 'glMatrixMode':
            mode = d.get('mode', 5888)
        elif name == 'glLoadIdentity' and mode != GL_PROJECTION:
            mv = list(IDENTITY)
        elif name == 'glLoadMatrixf':
            m = d.get('m')
            if not m or len(m) != 16:
                continue
            if mode == GL_PROJECTION:
                proj = m
            else:
                mv = m
        elif name == 'glMultMatrixf' and mode != GL_PROJECTION:
            mv = mat_mul(mv, d.get('m')) if mv else d.get('m')
        elif name == 'glOrtho':
            if mode is None:
                mode = GL_PROJECTION   # glOrtho at a range start is the frame's projection
            l = d.get('left'); r_ = d.get('right')
            b = d.get('bottom'); t = d.get('top')
            n = d.get('zNear'); f = d.get('zFar')
            m = [2.0 / (r_ - l), 0.0, 0.0, 0.0,
                 0.0, 2.0 / (t - b), 0.0, 0.0,
                 0.0, 0.0, -2.0 / (f - n), 0.0,
                 -(r_ + l) / (r_ - l), -(t + b) / (t - b), -(f + n) / (f - n), 1.0]
            if mode == GL_PROJECTION:
                proj = m
            else:
                mv = mat_mul(mv, m) if mv else m
        elif name == 'glTranslated' and mode != GL_PROJECTION:
            tv = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0,
                  d.get('x', 0), d.get('y', 0), d.get('z', 0), 1]
            mv = mat_mul(mv, tv) if mv else tv
        elif name == 'glScaled' and mode != GL_PROJECTION:
            sv = [d.get('x', 1), 0, 0, 0, 0, d.get('y', 1), 0, 0,
                  0, 0, d.get('z', 1), 0, 0, 0, 0, 1]
            mv = mat_mul(mv, sv) if mv else sv
        elif name == 'glVertexPointer':
            ptrs['v'] = (d.get('size'), d.get('type'), d.get('stride'), d.get('pointer'))
        elif name == 'glDrawArrays':
            if cur is None:
                continue
            vp = ptrs.get('v')
            if not (proj and mv and vp and isinstance(vp[3], (bytes, bytearray))):
                continue
            pts = decode(vp[3], vp[0], vp[1], vp[2], d['count'])
            if not pts:
                continue
            full = mat_mul(proj, mv)
            scr = []
            for p in pts:
                clip = transform(full, (p[0], p[1], p[2], 1.0))
                sp = project(clip)
                if sp:
                    scr.append(sp)
            if len(scr) == len(pts) and scr:
                dbg["decoded"] += 1
                xs = [p[0] for p in scr]
                ys = [p[1] for p in scr]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                onscreen = x1 >= 0 and x0 <= 1024 and y1 >= 0 and y0 <= 768
                if onscreen:
                    dbg["onscreen"] += 1
                bx0, by0, bx1, by1 = HERO_BOX
                if x1 >= bx0 and x0 <= bx1 and y1 >= by0 and y0 <= by1:
                    cur["strips"].append({
                        "call": e[0], "tex": tex, "n": d['count'],
                        "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                        "pts": [[round(p[0], 2), round(p[1], 2)] for p in scr],
                    })
    if cur and cur["strips"]:
        frames.append(cur)

    for i, fr in enumerate(frames):
        print("hero_cycle: frame %d (clear@%d) -> %d hero-box strips" % (
            i, fr["clear_call"], len(fr["strips"])), flush=True)

    def sig(s):
        return (s["n"], tuple(s["pts"][0]))
    base = {sig(s) for s in frames[0]["strips"]} if frames else set()
    out = []
    for fr in frames:
        mv_strips = [s for s in fr["strips"] if sig(s) not in base]
        out.append({"clear_call": fr["clear_call"], "hero_strips": mv_strips})
        print("hero_cycle:   -> %d animated" % len(mv_strips), flush=True)
    json.dump(out, open(out_path, "w"))
    print("hero_cycle: wrote", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
