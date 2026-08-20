#!/usr/bin/env python3
"""artcoeffs.py -- the combat-art regeneration coefficients, out of the ELF.

    python3 artcoeffs.py <sacred>            # id, base, step, element triple
    python3 artcoeffs.py <sacred> --tsv      # the same, tab separated
    python3 artcoeffs.py <sacred> --check    # self-check, exit 1 on failure

WHY THIS IS IN THE EXECUTABLE AND NOT A PAK. Sacred charges TIME for a combat
art rather than mana (findings log row 1042), and an art's regeneration is

    total = base + level * step

with `base` and `step` authored per art. Those two numbers are not in
`creature.pak`, `balance.bin` or any other data file -- they are a static array
compiled into the binary at 0x8793D00, stride 120, records 1..0x5E. Record 0 is
a zero slot and `sub_8306C6A` starts its scan at 1, which is why this reader
does too.

THE FIELDS, from the two functions that consume them:

    +0x00  i16      art id, what sub_8306C6A matches on
    +0x30  i32[3]   the EMPTY / LOAD / FULL element ids the slot draws with
    +0x40  f32      base   -- sub_8306D8A: total = base + level*step
    +0x44  f32      step

THE ART ID IS NOT A global.res TEXT ID. Resolving one through the resource tree
returns a real string -- id 1000 comes back "Buy item?" -- because the name
hash of "1000" happens to name a UI string. That is a collision, not a name,
and it is recorded here because the wrong answer looks entirely plausible.

A NOTE ON PROVENANCE. This reads the LINUX LGP binary. The address is a
constant of that build, so the reader validates a signature rather than
trusting the offset: record 1 must be art 1000 at base 5 / step 3, the first
four ids must be 1000, 1001, 1002, 1009, and every element triple must be three
consecutive ids. A different build fails the signature instead of returning
plausible garbage.
"""
import struct
import sys

TABLE = 0x8793D00
STRIDE = 120
FIRST, LAST = 1, 0x5E          # sub_8306C6A's own bounds
O_ID, O_ELEM, O_BASE = 0x00, 0x30, 0x40

# The signature: what this table is, if it is this table at all.
SIG_IDS = (1000, 1001, 1002, 1009)
SIG_BASE, SIG_STEP = 5.0, 3.0


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
    """-> list of (id, base, step, (empty, load, full)) for records 1..94."""
    elf = open(path, 'rb').read()
    out = []
    for i in range(FIRST, LAST + 1):
        rec = elf[_vaddr_to_off(elf, TABLE + STRIDE * i):][:STRIDE]
        art, = struct.unpack_from('<h', rec, O_ID)
        elem = struct.unpack_from('<3i', rec, O_ELEM)
        base, step = struct.unpack_from('<2f', rec, O_BASE)
        out.append((art, base, step, elem))
    return out


def _check(path):
    rows = load(path)
    ok = True

    def want(cond, what):
        nonlocal ok
        print(('  ok   ' if cond else '  FAIL ') + what)
        ok = ok and cond

    want(len(rows) == 94, f'{len(rows)} records (expected 94)')
    want(tuple(r[0] for r in rows[:4]) == SIG_IDS,
         f'the first four art ids are {tuple(r[0] for r in rows[:4])}')
    want(abs(rows[0][1] - SIG_BASE) < 1e-6 and abs(rows[0][2] - SIG_STEP) < 1e-6,
         f'art {rows[0][0]} is base {rows[0][1]} / step {rows[0][2]}')
    want(all(r[0] != 0 for r in rows), 'no record inside the bounds is a null slot')
    want(all(r[3][1] == r[3][0] + 1 and r[3][2] == r[3][0] + 2 for r in rows),
         'every element triple is three consecutive ids')
    # Balance sanity: these are authored seconds, not junk floats.
    want(all(0.0 < r[1] <= 120.0 for r in rows),
         f'base spans {min(r[1] for r in rows)}..{max(r[1] for r in rows)}')
    want(all(0.0 <= r[2] <= 120.0 for r in rows),
         f'step spans {min(r[2] for r in rows)}..{max(r[2] for r in rows)}')
    # A step of 0 is legal (an art that never slows down); a NEGATIVE one would
    # invert the cost model, and sub_82047D4's `if (both > total)` guard says
    # retail expects the curve to rise.
    want(all(r[2] >= 0.0 for r in rows), 'no art regenerates FASTER as it levels')
    print('artcoeffs: self-check ' + ('ok' if ok else 'FAILED'))
    return 0 if ok else 1


def main(argv):
    if not argv:
        print('usage: artcoeffs.py <sacred> [--tsv|--check]')
        return 2
    if '--check' in argv:
        return _check(argv[0])
    rows = load(argv[0])
    if '--tsv' in argv:
        print('id\tbase\tstep\tempty\tload\tfull')
        for art, base, step, e in rows:
            print(f'{art}\t{base:g}\t{step:g}\t{e[0]}\t{e[1]}\t{e[2]}')
        return 0
    for art, base, step, e in rows:
        print(f'{art:6}  base {base:6.1f}  step {step:6.1f}  elem {e[0]}..{e[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
