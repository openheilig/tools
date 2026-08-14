#!/usr/bin/env python3
"""Recover function boundaries from .eh_frame in the stripped LGP binary.

    python3 analysis/tools/binary/ehframe_funcs.py install/sacred > funcs.txt
    python3 analysis/tools/binary/ehframe_funcs.py install/sacred 0x8210b91   # who owns this addr

Why this exists: `install/sacred` has no symbol table, and a linear
`objdump -d` of it desyncs (see AGENTS.md "Three traps that cost hours") --
three of the four addresses behind the CalcResults analysis do not even
appear in a whole-binary sweep.  But GCC 3.4.4 emitted a full .eh_frame, and
every FDE in it carries `initial_location` + `address_range`: an exact,
authoritative (start, size) for each function with unwind info.  Anchoring
`objdump --start-address=` on an FDE start is always correctly aligned.

Encoding note: this binary uses DW_EH_PE_absptr for initial_location (the
values read back as plain 0x81xxxxx VAs), so no CIE augmentation parsing is
needed.  The script asserts that -- if a future binary uses pcrel, it will
say so rather than emit silent garbage.
"""
import struct
import sys


def load(path):
    f = open(path, 'rb').read()
    e_shoff, = struct.unpack_from('<I', f, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', f, 46)
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, typ, flags, addr, off, size = struct.unpack_from('<6I', f, o)
        secs.append((name, addr, off, size))
    stroff = secs[e_shstrndx][2]

    def nm(n):
        end = f.index(b'\0', stroff + n)
        return f[stroff + n:end].decode()

    return f, {nm(n): (a, o, s) for n, a, o, s in secs}


def fdes(f, addr, off, size):
    """Yield (start, length) for every FDE in .eh_frame."""
    p = 0
    while p + 4 <= size:
        ln, = struct.unpack_from('<I', f, off + p)
        if ln == 0:
            break                      # terminator
        if ln == 0xFFFFFFFF:
            raise SystemExit('64-bit DWARF not supported')
        body = p + 4
        cie_id, = struct.unpack_from('<I', f, off + body)
        if cie_id != 0:                # 0 == CIE, anything else == FDE
            loc, rng = struct.unpack_from('<II', f, off + body + 4)
            if loc and rng:
                yield loc, rng
        p = body + ln


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    f, secs = load(sys.argv[1])
    if '.eh_frame' not in secs:
        raise SystemExit('no .eh_frame section')
    addr, off, size = secs['.eh_frame']
    raw = sorted(set(fdes(f, addr, off, size)))
    if not raw:
        raise SystemExit('no FDEs found')

    # A handful of entries decode to nonsense (linker-merged fragments from
    # the static libs, and CIEs whose augmentation we deliberately skip).
    # Drop anything outside .text rather than let one 0xffd65562 poison the
    # table -- and say how many, because a silent filter is how a bad number
    # gets quoted later.
    tlo, tsz = secs['.text'][0], secs['.text'][2]
    funcs = [(s, n) for s, n in raw if tlo <= s < tlo + tsz and n < tsz]
    if len(funcs) != len(raw):
        print(f'# dropped {len(raw) - len(funcs)} FDEs outside '
              f'.text [{tlo:#x},{tlo + tsz:#x})', file=sys.stderr)
    lo = min(s for s, _ in funcs)
    if lo < 0x8000000:
        raise SystemExit('initial_location looks pc-relative, not absptr: '
                         f'lowest is {lo:#x} -- parse the CIE augmentation')

    if len(sys.argv) > 2:              # lookup mode
        q = int(sys.argv[2], 0)
        hit = [(s, n) for s, n in funcs if s <= q < s + n]
        for s, n in hit:
            print(f'{q:#x} is in {s:#x}..{s + n:#x} (size {n:#x}, +{q - s:#x})')
        if not hit:
            print(f'{q:#x} is in no FDE (leaf without unwind info, or data)')
        return

    for s, n in funcs:
        print(f'{s:#010x} {n:#x}')
    print(f'# {len(funcs)} functions, '
          f'{min(s for s, _ in funcs):#x}..'
          f'{max(s + n for s, n in funcs):#x}', file=sys.stderr)


if __name__ == '__main__':
    main()
