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

    gfx id = blob index - 5      for ids up to ~351
    gfx id = blob index - 3      from ~443 on

THE OFFSET IS NOT CONSTANT, and the first version of this tool got that wrong.
Two elements somewhere in ids 352..443 carry no name, so everything above the
drift is named two places late. The band between the last confirmed +5 anchor
(id 351) and the first confirmed +3 one (id 443) is NOT resolved, and this
tool refuses to name it rather than guessing -- `load()` returns None for the
name there and `--check` asserts the refusal.

THE DRIFT IS MEASURED FROM RETAIL'S OWN DATA, not eyeballed. The combat-art
table at 0x8793D00 (stride 120) carries, at +48/+52/+56, the three element
indices each art draws with. Those must name an EMPTY / LOAD / FULL triple, and
they do for 50 of the 52 triples that resolve -- but only at offset +3. The low
end is pinned independently: id 351 is UI_PORTRAIT_MP at 127x189, and the
alternative reading puts a 60x25 arrow there.

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
# (last id where +5 is confirmed, first id where +3 is confirmed). Between them
# the mapping is unknown and this tool says so instead of guessing.
LOW_OFFSET, LOW_LAST = 5, 351
HIGH_OFFSET, HIGH_FIRST = 3, 443
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


def offset_for(gid):
    """-> the blob offset for this id, or None inside the unresolved band."""
    if gid <= LOW_LAST:
        return LOW_OFFSET
    if gid >= HIGH_FIRST:
        return HIGH_OFFSET
    return None


def load(path):
    """-> list of (id, name, sheet, (x, y, w, h)). name is None where the
    offset is unresolved -- see the drift note above. Only ids the blob names."""
    elf = open(path, 'rb').read()
    names = [s.decode('latin1')
             for s in elf[BLOB[0]:BLOB[1]].split(b'\0') if s]
    out = []
    for gid in range(1, len(names)):
        off = offset_for(gid)
        i = gid + off if off is not None else None
        if i is not None and i >= len(names):
            break
        rec = elf[_vaddr_to_off(elf, TABLE + STRIDE * (gid - 1)):][:STRIDE]
        sheet = rec[:32].split(b'\0')[0].decode('latin1')
        u0, v0, u1, v1 = struct.unpack_from('<4f', rec, 0x24)
        own, = struct.unpack_from('<i', rec, 0x4C)
        if own != gid:                       # past the table, or misaligned
            break
        # SIZE IS u1 - u0, not u1 - u0 + 1 -- see research/formats/ui-taskbar.md.
        out.append((gid, names[i] if i is not None else None, sheet,
                    (int(u0), int(v0), int(u1 - u0), int(v1 - v0))))
    return out


def art_triples(path):
    """-> the element index triples the combat-art table draws with.

    Ground truth for the offset: each is (EMPTY, LOAD, FULL) and consecutive.
    """
    elf = open(path, 'rb').read()
    out = []
    for i in range(1, 0x5F):
        rec = elf[_vaddr_to_off(elf, 0x8793D00 + 120 * i):][:120]
        a, b, c = struct.unpack_from('<3i', rec, 48)
        if b == a + 1 and c == a + 2:
            out.append(a)
    return sorted(set(out))


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
          if r[1] and re.search(r'MANA|_MP(_|$)|ENERG|STAMIN|AUSDAUER', r[1])]
    want(mp == ['UI_PORTRAIT_MP'],
         f'the only mana-looking name placed is the multiplayer portrait: {mp}')
    # The mana conclusion does NOT depend on the id mapping: it is a search over
    # the NAME LIST, which is complete whatever the offsets are.
    all_names = [s.decode('latin1')
                 for s in elf[BLOB[0]:BLOB[1]].split(b'\0') if s]
    hits = [n for n in all_names
            if re.search(r'MANA|_MP(_|$)|ENERG|STAMIN|AUSDAUER', n)]
    want(hits == ['UI_PORTRAIT_MP', 'UI_PORTRAIT_MP_H', 'UI_PORTRAIT_MP_E'],
         f'across ALL {len(all_names)} names, the only mana-looking ones are '
         f'the multiplayer portrait: {hits}')
    named = [r for r in rows if r[1]]
    want(len(named) > 1300, f'named {len(named)} of {len(rows)} elements')
    want(all(r[1] is None for r in rows if LOW_LAST < r[0] < HIGH_FIRST),
         f'ids {LOW_LAST + 1}..{HIGH_FIRST - 1} are left unnamed, not guessed')
    # THE DRIFT CHECK. Retail's combat-art table says which element triple each
    # art draws with; every one must land on EMPTY / LOAD / FULL. This is what
    # caught the constant-offset error, so it stays in the self-check.
    by_name = {r[0]: r[1] for r in rows}
    clean = bad = 0
    for t in art_triples(path):
        got = [by_name.get(t + 1 + k) for k in range(3)]
        if None in got:
            continue
        if (got[0].endswith('_EMPTY') and got[1].endswith('_LOAD')
                and got[2].endswith('_FULL')):
            clean += 1
        else:
            bad += 1
    want(bad == 0 and clean > 40,
         f'{clean} combat-art triples name EMPTY/LOAD/FULL, {bad} do not')
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
