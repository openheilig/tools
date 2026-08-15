#!/usr/bin/env python3
"""Map each balance-table stat family (AK, FK, W, R, ...) to the skill it tunes.

The families in `balance.bin` are German abbreviations and the engine never
spells them out. They are resolved here WITHOUT guessing, by an identity the
binary states itself:

  * A creature carries 8 skill slots at `+0x24`, one byte each. That byte is
    the SKILL TYPE. `FUN_0821b576(creature, slot)` returns it.
  * `cUI_StatisticsChar::vf06` turns that same byte into a name with a literal
    `add $0x24b7, %eax` -- so **resource id = skill type + 9399** -- and hands
    the byte unchanged to `FUN_081f686a` as its switch selector.
  * `FUN_081f686a`'s jump table at 0x086ed568 is therefore indexed BY SKILL
    TYPE. Case i reads the balance globals belonging to skill 9399 + i.

The jump table is a permutation, not the identity, which is why reading the
cases in address order gives a wrong and plausible-looking answer.

The check is not an assertion, it is a coincidence that cannot survive being
wrong: eleven case bodies push their own skill's resource id as a literal, and
every one of them must equal 9399 + that case's table index. A single
mis-association breaks it. Guessing from the German instead would have got
four of eleven wrong -- FK is Faustkampf not Fernkampf, BK is Beidhaendiger
Kampf not Bogenkampf, W is Wendigkeit not Waffe, R is Ruestung not Resistenz.

Usage:  skillmap.py [out.tsv]      writes the table, exits 1 on a mismatch

Inputs: install/sacred_orig (via objdump) and
        research/formats/generated/balance-globals.tsv.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BIN = os.path.join(ROOT, 'donotpublish/install/sacred_orig')
RES = os.path.join(ROOT, 'donotpublish/install/scripts/us/global.res')
BAL = os.path.join(ROOT, 'research/formats/generated/balance-globals.tsv')
sys.path.insert(0, os.path.join(ROOT, 'tools/formats'))
import globalres                                              # noqa: E402

RES_BASE = 9399            # the literal in `add $0x24b7, %eax`
TABLE = 0x086ed568         # FUN_081f686a's jump table
NCASE = 34                 # from `cmp $0x21` + `ja`, so indices 0..33
BODY_END = 0x081f9200      # past the last case
SUFFIX = re.compile(r'(off|__?[sw])(AW|SP|VW|S|Ph|Fe|Ma|Gi)?$')


def globals_by_addr():
    """-> {address: balance key}, from the independently derived map."""
    out = {}
    for line in open(BAL, encoding='utf-8').read().split('\n')[1:]:
        f = line.split('\t')
        if len(f) > 2:
            out[int(f[2], 16)] = f[0]
    return out


def disasm(lo, hi):
    """-> [(addr, text)] for one address range."""
    d = subprocess.run(['objdump', '-d', f'--start-address={lo:#x}',
                        f'--stop-address={hi:#x}', BIN],
                       capture_output=True, text=True, check=True).stdout
    out = []
    for line in d.split('\n'):
        m = re.match(r'\s*([0-9a-f]+):\s', line)
        if m:
            out.append((int(m.group(1), 16), line))
    return out


def jump_table():
    """-> [target] indexed by skill type. Read from .rodata, not inferred."""
    with open(BIN, 'rb') as f:
        elf = f.read()
    # the program headers give the vaddr->file mapping; .rodata is the only
    # segment this address can be in, so find it by scanning the PT_LOADs
    import struct
    phoff, phentsize, phnum = struct.unpack_from('<I', elf, 0x1c)[0], \
        struct.unpack_from('<H', elf, 0x2a)[0], struct.unpack_from('<H', elf, 0x2c)[0]
    for i in range(phnum):
        p = phoff + i * phentsize
        typ, off, vaddr, _pa, filesz = struct.unpack_from('<5I', elf, p)
        if typ == 1 and vaddr <= TABLE < vaddr + filesz:
            base = off + TABLE - vaddr
            return list(struct.unpack_from(f'<{NCASE}I', elf, base))
    raise ValueError(f'{TABLE:#x} is in no PT_LOAD segment')


def build():
    """-> (rows, mismatches). One row per skill type with a case body."""
    g2k = globals_by_addr()
    _slots, by_hash = globalres.load(RES)
    tbl = jump_table()
    ends = sorted(set(tbl)) + [BODY_END]
    nxt = {a: ends[ends.index(a) + 1] for a in set(tbl)}
    ins = disasm(min(tbl), BODY_END)
    default = max(tbl, key=tbl.count)          # the shared no-op target

    rows, bad = [], []
    for i, a in enumerate(tbl):
        if a == default:
            continue
        fams, ids = [], []
        for ad, text in ins:
            if not a <= ad < nxt[a]:
                continue
            for m in re.finditer(r'0x(8b8[0-9a-f]{4})', text):
                k = g2k.get(int(m.group(1), 16))
                if k:
                    k = SUFFIX.sub('', k)
                    if k not in fams:
                        fams.append(k)
            for m in re.finditer(r'\$0x([0-9a-f]+)', text):
                v = int(m.group(1), 16)
                if 9400 <= v <= 9432 and v not in ids:
                    ids.append(v)
        rid = RES_BASE + i
        if ids and ids != [rid]:
            bad.append(f'type {i}: body pushes {ids}, expected [{rid}]')
        rows.append((i, rid, globalres.by_id(rid, by_hash) or '?',
                     ','.join(fams), bool(ids)))
    return rows, bad


if __name__ == '__main__':
    rows, bad = build()
    confirmed = sum(1 for r in rows if r[4])
    out = ['skill_type\tresource_id\tskill\tbalance_families\tself_confirmed']
    out += [f'{i}\t{r}\t{n}\t{f or "-"}\t{int(c)}' for i, r, n, f, c in rows]
    text = '\n'.join(out) + '\n'
    if len(sys.argv) > 1:
        open(sys.argv[1], 'w', encoding='utf-8').write(text)
    else:
        print(text, end='')
    print(f'skillmap: {len(rows)} skills, {confirmed} confirmed by a '
          f'self-pushed id, {len(bad)} mismatches', file=sys.stderr)
    for m in bad:
        print('  FAIL ' + m, file=sys.stderr)
    sys.exit(1 if bad or confirmed < 11 else 0)
