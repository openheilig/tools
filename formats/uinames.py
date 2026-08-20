#!/usr/bin/env python3
"""uinames.py -- retail's OWN name for every interface element.

    python3 uinames.py <sacred>                 # id, name, sheet, rect
    python3 uinames.py <sacred> --grep MANA     # only names matching a regex
    python3 uinames.py <sacred> --check         # self-check, exit 1 on failure

WHY THIS EXISTS. The gfx element table at 0x880DC68 gives 1886 sub-rects with
ids and sheets but no meaning, so every element had to be identified by pixel
match -- slow, and wrong at least twice (the portrait ring was assigned to the
mercenary window; the potion belt was called the combat-art slots). The names
were in the binary the whole time.

THE NAME TABLE is a packed NUL-separated blob of 1452 strings. Nothing points
into it -- no pointer to any of its strings exists anywhere in the image, and
no instruction takes one as an immediate -- so it is walked, not indexed, and
that is why searching for xrefs never found it.

    gfx id = blob index - 5

THE ANCHOR IS SELF-IDENTIFYING, which is what makes the offset a measurement
rather than a guess: blob index 6 is `UI_INVALID`, and gfx id 1 is the one
entry whose SHEET NAME field literally reads `INVALID`. Three independent
shape checks agree -- `UI_HORSE_VHP_FULL` lands on the only tall-and-thin rect
in the block (15x71), `UI_HORSE_HHP_FULL`/`_EMPTY` on the two 71x14 ones, and
`UI_CHR_HEALTH_01`/`_02` on the 95x107 pair -- and every entry in the named
range carries its own id field equal to the derived id, 1446 for 1446.

COVERAGE IS PARTIAL AND THE END IS RAGGED. The blob's first four strings are
attribute names (`control`, `type`, `tooltipFade`, `tooltipDelay`), not
elements, and it ends `UI_MAX`, `UI_STATIC`, `UI_LISTBOX` -- an enum
terminator with two strays after it. So names cover ids 1..1444 and the table
has 1886: everything above `UI_MAX` is unnamed here, including `GUI_HERO_*`
(1488..1511). An id this tool cannot name is not an error.
"""
import re
import struct
import sys

BLOB = (0x6CF9FD, 0x6D5722)     # file offsets of the packed name blob
OFFSET = 5                      # blob index - OFFSET = gfx id
TABLE = 0x880DC68               # gfx element table, virtual
STRIDE = 84


def _vaddr_to_off(elf, v):
    ph, = struct.unpack_from('<I', elf, 0x1C)
    size, = struct.unpack_from('<H', elf, 0x2A)
    n, = struct.unpack_from('<H', elf, 0x2C)
    for i in range(n):
        o = ph + i * size
        p_type, p_off, p_vaddr, _, p_filesz, _ = struct.unpack_from('<6I', elf, o)
        if p_type == 1 and p_vaddr <= v < p_vaddr + p_filesz:
            return p_off + (v - p_vaddr)
    raise ValueError(f'{v:#x} is in no PT_LOAD segment')


def load(path):
    """-> list of (id, name, sheet, (x, y, w, h)). Only ids the blob names."""
    elf = open(path, 'rb').read()
    names = [s.decode('latin1')
             for s in elf[BLOB[0]:BLOB[1]].split(b'\0') if s]
    out = []
    for i in range(OFFSET + 1, len(names)):
        gid = i - OFFSET
        rec = elf[_vaddr_to_off(elf, TABLE + STRIDE * (gid - 1)):][:STRIDE]
        sheet = rec[:32].split(b'\0')[0].decode('latin1')
        u0, v0, u1, v1 = struct.unpack_from('<4f', rec, 0x24)
        own, = struct.unpack_from('<i', rec, 0x4C)
        if own != gid:                       # past the table, or misaligned
            break
        # SIZE IS u1 - u0, not u1 - u0 + 1 -- see research/formats/ui-taskbar.md.
        out.append((gid, names[i], sheet,
                    (int(u0), int(v0), int(u1 - u0), int(v1 - v0))))
    return out


def _check(path):
    rows = load(path)
    elf = open(path, 'rb').read()
    ok = True

    def want(cond, what):
        nonlocal ok
        print(('  ok   ' if cond else '  FAIL ') + what)
        ok = ok and cond

    by_id = {r[0]: r for r in rows}
    # The anchor: id 1's sheet-name field is the string INVALID, and the blob
    # names it UI_INVALID. If the offset were wrong this would not line up.
    rec = elf[_vaddr_to_off(elf, TABLE):][:STRIDE]
    want(rec[:32].split(b'\0')[0] == b'INVALID' and by_id[1][1] == 'UI_INVALID',
         'id 1 is UI_INVALID and its sheet field reads INVALID')
    # Shape checks -- a name that describes an orientation must land on a rect
    # that has it. These are what turn the offset from plausible into measured.
    want(by_id[76][1] == 'UI_HORSE_VHP_FULL' and by_id[76][3][3] > by_id[76][3][2],
         'UI_HORSE_VHP_FULL is taller than it is wide')
    want(by_id[78][1] == 'UI_HORSE_HHP_FULL' and by_id[78][3][2] > by_id[78][3][3],
         'UI_HORSE_HHP_FULL is wider than it is tall')
    want(by_id[78][3][2:] == by_id[79][3][2:],
         'the two horse HHP states are the same size')
    want(by_id[42][1] == 'UI_CHR_HEALTH_01' and by_id[43][1] == 'UI_CHR_HEALTH_02'
         and by_id[42][3][2:] == by_id[43][3][2:] == (95, 107),
         'the portrait ring is the UI_CHR_HEALTH pair, 95x107 both')
    want(by_id[43][3][0] == 96,
         'UI_CHR_HEALTH_02 starts at x 96, not 95')
    # Mana: the point of the whole exercise. Sacred has no mana gauge, and the
    # ONE thing that looks like one is a trap worth pinning down rather than
    # filtering out -- UI_PORTRAIT_MP / _MP_H / _MP_E is the MULTIPLAYER
    # portrait frame, 127x189 on GUI_main_14, sitting between UI_NET_* and
    # UI_HORSEMERC. MP is not mana points. If a real mana element ever appears
    # this assertion is what will say so.
    # `MP` must be anchored between underscores or the count drowns in EMPTY,
    # COMPASS, CHAMP and VAMP -- 165 false positives on a bare substring.
    mp = [r[1] for r in rows
          if re.search(r'MANA|_MP(_|$)|ENERG|STAMIN|AUSDAUER', r[1])]
    want(mp == ['UI_PORTRAIT_MP', 'UI_PORTRAIT_MP_H', 'UI_PORTRAIT_MP_E'],
         f'the only mana-looking names are the multiplayer portrait: {mp}')
    want(len(rows) > 1400, f'named {len(rows)} elements')
    print('uinames: self-check ' + ('ok' if ok else 'FAILED'))
    return 0 if ok else 1


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    path = argv[0]
    if '--check' in argv:
        return _check(path)
    pat = None
    if '--grep' in argv:
        pat = re.compile(argv[argv.index('--grep') + 1], re.I)
    for gid, name, sheet, (x, y, w, h) in load(path):
        if pat and not pat.search(name):
            continue
        print(f'{gid:5}  {name:28} {sheet:20} ({x:3},{y:3}) {w:3}x{h:3}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
