#!/usr/bin/env python3
"""Name the script opcodes from the compiler's own keyword tables.

`opcodes.py` names opcodes from the OUTSIDE -- what strings a handler happens
to carry. That is naming-by-payload, and it is wrong three times: opcodes 67,
75 and 76 came out as `atmo_rg`, which is a frequent operand string and not an
identity. This reads the compiler's own binding instead.

The binary ships two keyword tables. Each is a run of NUL-terminated name
strings, then a pointer array into that run, then a parallel `u32` opcode
array whose first slot is a zero sentinel -- so pointer `i` pairs with number
`i + 1`, and the pairing is the compiler's, not ours.

    table A   ptr 0x6a1ee0   op 0x6a1fd4   61 entries
    table B   ptr 0x6a23f0   op 0x6a24e0   60 entries

THE OFFSETS ARE NOT THE ONES `research/formats/script-bytecode.md` CARRIED
until 2026-08-16: it said 0x69b240/0x69b334 and 0x69b750/0x69b840, each low by
0x6d90, which in this build lands in texture-name strings. The tables were
re-found by anchoring on a known name (`MachVersteck` is A[60]) and walking
back. The document is corrected; this is the record of why.

Nothing here is a fit. Every claim the layout makes is asserted below --
sentinel zero, a zero terminator past the last opcode, every pointer inside
.rodata, every name printable, every opcode inside the dispatcher's 0..140 --
and the CONTROL is that seven opcodes had already been named by unrelated
routes (handler .rodata strings) before this table was read. All seven must
still agree. A wrong base offset or a wrong pairing does not reproduce seven
independently-recovered names, so the check is not a restatement.

Usage:
    opcode_names.py                  # TSV to stdout
    opcode_names.py out.tsv          # ... or to a file
"""
import os
import struct
import sys

# realpath: the private workspace reaches this repo through an `analysis/tools`
# symlink, and abspath would leave it in the path and root us inside there.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
BIN = os.path.join(ROOT, 'donotpublish/install/sacred_orig')

RO_VMA, RO_OFF, RO_SIZE = 0x086d8200, 0x690200, 0x5e9f2
#           name pointers   opcode numbers   entries
TABLES = {'A': (0x6a1ee0, 0x6a1fd4, 61),
          'B': (0x6a23f0, 0x6a24e0, 60)}
MAX_OPCODE = 140          # the dispatcher's jump table is 141 entries, 0..140

# Named before this table was read, from handler .rodata alone. The control.
INDEPENDENT = {1: 'CreateNPC', 8: 'CreateObj', 17: 'AddExp', 46: 'Teleport',
               63: 'QuestKompassPos', 64: 'QuestKompassObj', 121: 'AutoSave'}

# One opcode carries two keywords: B[26] `DelNPC` and B[27] `DelOBJ` both bind
# to 55. Creation does NOT work that way -- `CreateNPC` is 1 and `CreateObj` is
# 8, two instructions -- so the compiler distinguishes the two kinds when
# making them and not when destroying them. That asymmetry is data, so it is
# pinned rather than tolerated: any OTHER opcode with two names is a failure.
ALIASES = {55: {'DelNPC', 'DelOBJ'}}


def main():
    d = open(BIN, 'rb').read()
    u32 = lambda o: struct.unpack_from('<I', d, o)[0]      # noqa: E731
    fail = []

    def cstr(va):
        if not (RO_VMA <= va < RO_VMA + RO_SIZE):
            return None
        o = va - RO_VMA + RO_OFF
        e = d.find(b'\0', o, o + 64)
        if e < 0:
            return None
        s = d[o:e].decode('latin-1')
        return s if s and all(33 <= ord(c) < 127 for c in s) else None

    rows = []
    for label, (pa, oa, n) in sorted(TABLES.items()):
        if pa + 4 * n != oa:
            fail.append(f'table {label}: pointer array of {n} does not end '
                        f'where the opcode array starts ({pa + 4 * n:#x} vs {oa:#x})')
        if u32(oa) != 0:
            fail.append(f'table {label}: first opcode slot is {u32(oa)}, not the zero sentinel')
        if u32(oa + 4 * (n + 1)) != 0:
            fail.append(f'table {label}: no zero terminator after entry {n}')
        for i in range(n):
            name = cstr(u32(pa + 4 * i))
            op = u32(oa + 4 * (i + 1))
            if name is None:
                fail.append(f'table {label}[{i}]: pointer {u32(pa + 4 * i):#x} '
                            f'is not a printable .rodata string')
                continue
            if op > MAX_OPCODE:
                fail.append(f'table {label}[{i}] {name}: opcode {op} is past {MAX_OPCODE}')
                continue
            rows.append((op, name, label, i))

    names_of = {}
    for op, name, _, _ in rows:
        names_of.setdefault(op, set()).add(name)
    for op, names in sorted(names_of.items()):
        if len(names) > 1 and names != ALIASES.get(op):
            fail.append(f'opcode {op} carries {sorted(names)}, expected '
                        f'{sorted(ALIASES.get(op, []))  or "one name"}')
    for op, names in ALIASES.items():
        if names_of.get(op) != names:
            fail.append(f'opcode {op} no longer carries {sorted(names)} -- '
                        f'the table now says {sorted(names_of.get(op, []))}')
    seen = {op: sorted(n)[0] for op, n in names_of.items()}

    agree = 0
    for op, name in INDEPENDENT.items():
        got = seen.get(op)
        if got is None:
            fail.append(f'control: opcode {op} should be {name!r}, the table names nothing')
        elif got.lower() != name.lower():
            fail.append(f'control: opcode {op} is {got!r}, independently named {name!r}')
        else:
            agree += 1

    rows.sort()
    text = 'opcode\tname\ttable\tindex\n' + ''.join(
        f'{op}\t{name}\t{label}\t{i}\n' for op, name, label, i in rows)
    if len(sys.argv) > 1:
        open(sys.argv[1], 'w', encoding='utf-8').write(text)
    else:
        print(text, end='')

    unnamed = sorted(set(range(MAX_OPCODE + 1)) - set(seen))
    print(f'opcode_names: {len(rows)} entries, {len(seen)} of {MAX_OPCODE + 1} '
          f'opcodes named, {agree} of {len(INDEPENDENT)} controls agree, '
          f'{len(unnamed)} unnamed {unnamed}', file=sys.stderr)
    for m in fail:
        print('  FAIL ' + m, file=sys.stderr)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
