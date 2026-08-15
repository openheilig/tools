#!/usr/bin/env python3
"""Pin `nextStaticId` at +0x1f in world/static.pak, by structure not a header.

`engine/formats/statics.gd` takes the offset from Resacred-old's `rs_file.h`.
That is an outside description, and the property that accompanied it -- "the
value is a valid record index" -- does not discriminate: six offsets in the
64-byte record satisfy it for every record (0x00, 0x04, 0x08, 0x12, 0x13,
0x1f, plus 0x07 in retail).

Two structural properties do, and both are measured here.

1. A CHAIN IS A LINKED LIST, so no record may be the target of two links.
   The honest measure is EXCESS = (number of links) - (distinct targets).
   +0x1f scores 0 in both builds, over 51,224 and 174,422 links. Every rival
   that carries a comparable number of links scores in the hundreds of
   thousands.

   > The obvious wrong metric is "how many targets are hit more than once",
   > which counts a field pointing 418,026 times at ONE record as a single
   > collision. +0x1a does exactly that and looked like the best rival until
   > the measure was changed. Excess is used for that reason.

2. A LINKED RECORD IS NEVER A HEAD. The world cells name chain heads at
   WldxEntry +0x04, a different file entirely. Of +0x1f's 174,422 targets,
   **zero** are among the 31,752 heads sampled from 400 sectors -- the two
   files partition the records between them. The rivals do not: +0x1a's single
   target is itself a head.

The Armalion prerelease is usable for arm 1 because `Static.PAK` is `OBJ` v1
in both builds with the same 64-byte payload (research/formats/pak-containers.md).
Its CELL records are `WLK` v4 and laid out differently, so it is not used for
arm 2.

Usage:  static_next_check.py [static.pak ...]     default: the retail install
        Arm 2 runs only for a static.pak with world/ sector files beside it.
"""
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(ROOT, 'donotpublish/install/world/static.pak')
NEXT = 0x1f
REC = 64
KEY_REC, CELL, CELLS = 768, 32, 4096
KEY_OFF, KEY_CSZ, CELL_HEAD = 236, 240, 4
SECTORS = 400            # enough heads to be decisive, fast enough to run


def links(d, offs, n, at):
    """-> (total links, distinct targets). Zero means 'no link'."""
    seen, tot = set(), 0
    for o in offs:
        v = struct.unpack_from('<I', d, o + at)[0]
        if v and v < n:
            tot += 1
            seen.add(v)
    return tot, seen


def heads_from_world(world_dir):
    """-> set of chain heads named by the cells, or None if absent."""
    kp = os.path.join(world_dir, 'sectors.keyx')
    wp = os.path.join(world_dir, 'sectors.wldx')
    if not (os.path.exists(kp) and os.path.exists(wp)):
        return None
    k, w = open(kp, 'rb').read(), open(wp, 'rb').read()
    n = struct.unpack_from('<I', k, 4)[0]
    out, done = set(), 0
    for i in range(n):
        r = 256 + i * KEY_REC
        off = struct.unpack_from('<I', k, r + KEY_OFF)[0]
        csz = struct.unpack_from('<I', k, r + KEY_CSZ)[0]
        if not off or not csz:
            continue
        try:
            blob = zlib.decompress(w[off:off + csz])
        except zlib.error:
            continue
        if len(blob) < CELLS * CELL:
            continue
        for c in range(CELLS):
            v = struct.unpack_from('<I', blob, c * CELL + CELL_HEAD)[0]
            if v:
                out.add(v)
        done += 1
        if done >= SECTORS:
            break
    return out if done else None


def check(path):
    d = open(path, 'rb').read()
    if d[:3] != b'OBJ':
        raise ValueError(f'{path}: magic {d[:3]!r}, not OBJ')
    n = struct.unpack_from('<I', d, 4)[0]
    idx = struct.unpack_from(f'<{n * 3}I', d, 0x100)
    offs = [idx[i * 3 + 1] for i in range(n)]
    sizes = {idx[i * 3 + 2] for i in range(n)}
    if sizes != {REC}:
        raise ValueError(f'{path}: payloads are {sorted(sizes)}, not {REC}')

    fail = []
    self_ok = sum(1 for i, o in enumerate(offs)
                  if struct.unpack_from('<I', d, o)[0] == i)
    if self_ok != n:
        fail.append(f'{n - self_ok} records do not carry their own index')

    tot, tgt = links(d, offs, n, NEXT)
    excess = tot - len(tgt)
    if excess:
        fail.append(f'+0x{NEXT:02x} has {excess} excess links -- not a list')
    if tot < n // 100:
        fail.append(f'only {tot} links in {n} records -- too few to test')

    # a rival must carry a comparable number of links AND be visibly worse
    floor = max(1, tot // 10)
    best = None
    for o in range(4, REC - 3):
        if o == NEXT:
            continue
        t2, s2 = links(d, offs, n, o)
        if t2 >= floor and (best is None or t2 - len(s2) < best[1]):
            best = (o, t2 - len(s2), t2)
    if best is None:
        fail.append('no rival offset carries enough links to compare against')
    elif best[1] == 0:
        fail.append(f'+0x{best[0]:02x} carries {best[2]} links with no excess '
                    f'either, so this no longer picks out +0x{NEXT:02x}')

    hd = heads_from_world(os.path.join(os.path.dirname(path)))
    overlap = None
    if hd is not None:
        # An EMPTY head set must fail, not skip. WldxEntry +0x08 is zero in
        # every cell of the world, so reading the head from there yields
        # nothing and the disjointness test would pass by having no work to
        # do -- exactly the silent pass this arm exists to avoid.
        if len(hd) < 1000:
            fail.append(f'only {len(hd)} chain heads found in {SECTORS} sectors '
                        f'-- the cell head field is wrong, so this arm proves '
                        f'nothing')
        overlap = len(tgt & hd)
        if overlap:
            fail.append(f'{overlap} of {len(tgt)} link targets are also cell '
                        f'heads -- a linked record must not be a head')

    print(f'{os.path.basename(path)}: {n} records, self-index {self_ok}/{n}; '
          f'+0x{NEXT:02x} {tot} links, {excess} excess; '
          f'best rival +0x{best[0]:02x} has {best[1]} excess over {best[2]} links'
          if best else '')
    if hd is not None:
        print(f'  vs the world cells: {len(hd)} heads, {overlap} also link targets')
    else:
        print('  no world/ beside this file, so the head-disjointness arm did not run')
    for m in fail:
        print('  FAIL ' + m)
    return not fail


if __name__ == '__main__':
    paths = sys.argv[1:] or [DEFAULT]
    sys.exit(0 if all(check(p) for p in paths) else 1)
