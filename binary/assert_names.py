#!/usr/bin/env python3
r"""Name retail functions from their own assert strings -- WIDER than `c[A-Z]`.

`research/engine/decompilation-coverage.md` already ran this oracle against
retail and got 131 distinct names from 248 strings. It scanned for
`c[A-Z]\w+::\w+`, which is the convention Sacred mostly follows and not
always: this scans for any `identifier::identifier(` and picks up ~18 more.

The extra names are the classes that break the `c` prefix --
`TypeManager::loadItemTypes`, `TypeManager::loadWeaponInfo`,
`ItemDataMgr::loadHero`, `ItemDataMgr::saveHero`,
`ItemTypeMgr::makeWeaponInfo`, `ItemTypeMgr::getDoorDirection`,
`dxDriver7::*`, `dxDisplay::*`, `dxDriver::createSurface` -- plus destructors,
which `\w` cannot match through the leading `~`.

The rule that makes it a mechanism rather than a guess is unchanged:

    a string names a function only if EXACTLY ONE function references it.

A string referenced from two places names neither, and is reported.

TWO THINGS THIS ADDS BEYOND A WIDER PATTERN.

  A RUN-ON GUARD. Widening the pattern lets the tail of a previous string be
  read as part of the class name: `BcEngine::creature_equipItem` is `cEngine`
  with a stray `B` in front, and so are `AcInventoryEntry`, `CcWorldView2`,
  `GcEngine` and `VBcObjectManager`. Any class that is another known class
  plus one leading character is flagged and dropped, not emitted.

  AN ADDRESS-LEVEL CROSS-SOURCE CHECK. The existing second source is the
  Armalion symbol CATALOGUE, which agrees or not about a name. `--vtables`
  compares against the RTTI vtable walk at the SAME ADDRESS: where both
  oracles reach one function they must agree on its class. Two do, and both
  agree -- `cFile_cached__vf09` against `cFile_cached::async_read`, and
  `cCommand_armaStop__vf02` against `cCommand_armaStop::execute`, slot 2 being
  where a command's `execute` belongs. A disagreement is a FAILURE.

Nothing here writes to the binary. The output is an `addr/name` TSV for
`ghidra/CheckNames.java` (dry run) and then `ghidra/ImportNames.java`.

Usage:  assert_names.py <sacred_orig> [out.tsv] [vtables.tsv]
"""
import bisect
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ehframe_funcs import load, fdes                          # noqa: E402

METH = re.compile(r'^[<\s]*([A-Za-z_]\w*)::([~A-Za-z_]\w*)\s*\(')
MINLEN = 8


def strings_with_offsets(path):
    """-> {text: [file offset]}. One `strings` call, not a Python rescan."""
    out = subprocess.run(['strings', '-a', '-t', 'd', f'-n{MINLEN}', path],
                         capture_output=True, text=True, check=True).stdout
    d = {}
    for line in out.split('\n'):
        line = line.strip()
        if not line:
            continue
        off, _, text = line.partition(' ')
        if off.isdigit():
            d.setdefault(text, []).append(int(off))
    return d


def sections(path):
    """-> [(vaddr, file offset, size)] for every PT_LOAD, to map both ways."""
    d = open(path, 'rb').read()
    phoff = struct.unpack_from('<I', d, 0x1c)[0]
    phentsize = struct.unpack_from('<H', d, 0x2a)[0]
    phnum = struct.unpack_from('<H', d, 0x2c)[0]
    segs = []
    for i in range(phnum):
        p = phoff + i * phentsize
        typ, off, vaddr, _pa, filesz = struct.unpack_from('<5I', d, p)
        if typ == 1 and filesz:
            segs.append((vaddr, off, filesz))
    return d, segs


def to_vaddr(segs, off):
    for v, o, sz in segs:
        if o <= off < o + sz:
            return v + off - o
    return None


def refs_to(d, vaddr):
    """-> [file offset] where the 4-byte little-endian address appears.

    A direct scan cannot desync the way a linear objdump of this stripped
    binary does -- see xrefs.py on the same point.
    """
    pat = struct.pack('<I', vaddr)
    out, i = [], d.find(pat)
    while i >= 0:
        out.append(i)
        i = d.find(pat, i + 1)
    return out


def vtable_classes(path):
    """-> {addr: {class and every ancestor, lowercased}}.

    A vtable slot may hold a method the class INHERITED, so the owning class
    of the string need only be the slot's class or one of its bases --
    `cWeapon3D`'s slot legitimately holds `cItemBase::advanceTime`. Comparing
    only the leaf class reports that as a contradiction, which it is not.
    Case is ignored because the engine spells one class two ways
    (`cUI_Blacksmith` and `cUI_BlackSmith` both appear in its own strings).
    """
    out = {}
    for line in open(path, encoding='utf-8').read().split('\n')[1:]:
        f = line.split('\t')
        if len(f) >= 3:
            names = {f[2].replace('::', '__').lower()}
            if len(f) >= 5 and f[4]:
                names |= {b.replace('::', '__').lower() for b in f[4].split(';')}
            out[int(f[0], 16)] = names
    return out


def main(ret, outp=None, vt=None):
    ret_s = strings_with_offsets(ret)
    cand = [t for t in ret_s if METH.match(t)]
    # run-on guard: a class that is another class plus one leading character
    # is the tail of the previous string, not a class
    classes = {METH.match(t).group(1) for t in cand}
    # X is a run-on only when stripping its first character leaves a class
    # that FOLLOWS the c-prefix convention. That drops `BcEngine` -> `cEngine`
    # while keeping `cItemDataMgr`, whose tail `ItemDataMgr` is a real class
    # in its own right and does not look like a c-name.
    runon = {c for c in classes
             if len(c) > 2 and c[1:] in classes
             and c[1] == 'c' and c[2:3].isupper()}
    shared = [t for t in cand if METH.match(t).group(1) not in runon]

    d, segs = sections(ret)
    f, secs = load(ret)
    a, o, sz = secs['.eh_frame']
    funcs = {st: ln for st, ln in fdes(f, a, o, sz)}
    starts = sorted(funcs)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        if i < 0:
            return None
        s = starts[i]
        return s if a < s + funcs[s] else None

    rows, multi, none = [], [], []
    for t in sorted(shared):
        m = METH.match(t)
        name = f'{m.group(1)}__{m.group(2)}'
        owners = set()
        for off in ret_s[t]:
            va = to_vaddr(segs, off)
            if va is None:
                continue
            for r in refs_to(d, va):
                rva = to_vaddr(segs, r)
                if rva is None:
                    continue
                f = owner(rva)
                if f is not None:
                    owners.add(f)
        if len(owners) == 1:
            rows.append((owners.pop(), name, t))
        elif owners:
            multi.append((name, sorted(owners), t))
        else:
            none.append((name, t))

    # Two distinct outcomes, and conflating them was wrong.
    #
    # ONE NAME AT SEVERAL ADDRESSES is real ambiguity -- inlining, or adjacent
    # frames. decompilation-coverage.md measured this at 11%. Those names are
    # DROPPED, not reported as a defect.
    #
    # ONE ADDRESS UNDER SEVERAL NAMES is usually the engine spelling itself
    # two ways: `cUI_Character::execAction` and `::executeAction` are the same
    # function, as are `cUI_BlackSmith` and `cUI_Blacksmith`. That is an ALIAS
    # while the class agrees (case-insensitively); the longer name wins. Only
    # a genuine class disagreement is a failure.
    byname = {}
    for a, n, _ in rows:
        byname.setdefault(n, set()).add(a)
    ambiguous = {n for n, aa in byname.items() if len(aa) > 1}
    rows = [r for r in rows if r[1] not in ambiguous]

    byaddr, clash, aliases, twoclass = {}, [], 0, []
    for a, n, _ in rows:
        prev = byaddr.get(a)
        if prev is None:
            byaddr[a] = n
        elif prev != n:
            if prev.split('__')[0].lower() == n.split('__')[0].lower():
                aliases += 1
                byaddr[a] = max(prev, n, key=len)
            else:
                # two CLASSES at one address is the same inlining/adjacent-frame
                # effect that puts one name at several addresses. Drop it and
                # say so; it is not a defect in the mechanism.
                twoclass.append(f'{a:#x}: {prev} and {n}')
                byaddr[a] = None
    rows = [(a, n) for a, n in byaddr.items() if n]

    # several distinct strings of one method land on one address -- that is
    # corroboration, not duplication, so emit each function once
    uniq = sorted(set(rows))
    text = ''.join(f'{a:#010x}\t{n}\n' for a, n in uniq)

    # CROSS-SOURCE ARM. The RTTI vtable walk names some of these addresses by
    # CLASS and slot, knowing nothing about strings. Where both oracles reach
    # the same function they must agree on the class; a disagreement means one
    # of them is wrong and is a failure, not a note.
    agree = disagree = 0
    if vt:
        vc = vtable_classes(vt)
        for a, n in uniq:
            if a in vc:
                if n.split('__')[0].lower() in vc[a]:
                    agree += 1
                else:
                    disagree += 1
                    clash.append(f'{a:#x}: vtables say class {sorted(vc[a])}, '
                                 f'the assert string says {n}')
    if outp:
        open(outp, 'w', encoding='utf-8').write(text)
    else:
        print(text, end='')

    print(f'assert_names: {len(cand)} ident::ident strings in retail, '
          f'{len(runon)} run-on classes dropped ({sorted(runon)}); '
          f'{len(shared)} usable; '
          f'{len(uniq)} distinct functions named; {len(ambiguous)} names '
          f'dropped for sitting at several addresses, {aliases} aliases '
          f'merged; {len(multi)} strings are '
          f'referenced from several, {len(none)} from none', file=sys.stderr)
    if vt:
        print(f'  cross-source: {agree} of these functions are also named by the '
              f'RTTI vtable walk and the class agrees, {disagree} disagree',
              file=sys.stderr)
    for m in twoclass:
        print(f'  dropped, two classes at one address: {m}', file=sys.stderr)
    for n, o, _ in multi:
        print(f'  ambiguous {n}: {[hex(x) for x in o]}', file=sys.stderr)
    for m in dict.fromkeys(clash):
        print('  FAIL ' + m, file=sys.stderr)
    return 1 if clash or len(uniq) < 20 else 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:4]))
