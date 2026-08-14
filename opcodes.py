#!/usr/bin/env python3
"""Map script OPCODES to their engine handler functions, and name them.

Follows rows 718-722: the record parser at 0x0826aed6 only fills a slot array;
the DISPATCHER at 0x0826e8ce executes the record. Its switch at 0x0826ea49 is
`jmp DWORD PTR [eax*4+0x086f4298]` bounded by `cmp 0x8c`, so the opcode jump
table is 141 entries at 0x086f4298 -- opcodes 0..140, exactly the range the
data uses.

Each live case is a stub: it pushes the parsed slot array (and, for some, the
dynamic_cast'd target object) and CALLs one function, then jmps to the shared
end. So opcode -> handler is 1:1 and readable straight out of the case body.

Naming the handlers: they are not virtual, so RTTI gives nothing. What they do
carry is .rodata -- error/log format strings and, more usefully, the literal
name strings the handler compares its operands against. Those are dumped here
per opcode; combine with the operand tags the data actually uses
(`startcode.py --opcode N`) to name the instruction.

Usage:
    opcodes.py                 # table: opcode, handler, size, strings
    opcodes.py --json out.json
    opcodes.py --md analysis/script-opcodes.md   # + per-opcode data profile
"""
import collections
import json
import re
import struct
import subprocess
import sys

BINARY = 'install/sacred_orig'
DISPATCH = (0x0826e8ce, 0x082720f0)
TABLE_VA, TABLE_N = 0x086f4298, 141
DEFAULT_CASE = 0x082720dd
# Not a handler: the operand fetch. The dispatcher prologue and several cases
# call it as (slots, 1, 4, record) and compare the result against a small type
# code, so a case that calls it FIRST is doing its own work inline rather than
# delegating -- take the next call as the handler, or none at all.
ARG_FETCH = 0x085ff0e8
RO_VMA, RO_OFF, RO_SIZE = 0x086d8200, 0x690200, 0x5e9f2
DA_VMA, DA_OFF, DA_SIZE = 0x08737c00, 0x6eec00, 0x105010
TEXT_VMA, TEXT_SIZE = 0x08053828, 0x6849a4

# Classes so common across handlers that naming one says nothing: every script
# action ends up posting an event about itself.
BORING = {'cEvent', 'cEventNetwork', 'cObject', 'cCreature', 'cFile_ram'}

d = open(BINARY, 'rb').read()

# Names given ONLY where the handler's own strings say so; everything else is
# left blank on purpose rather than guessed from the operands.
NAMES = {
    0: 'return 0 (the only case that does; script halt)',
    1: 'CreateNPC',
    8: 'CreateOBJ',
    24: 'group alive? ("Group (%d) is dead")',
    37: 'sound, "SOUND_" prefix',
    38: 'sound, "SOUND_" prefix (same handler as 37)',
    44: 'NPCUWR_11%d/12%d/21%d/22%d',
    46: 'Teleport (by resnum or vx,vy,vz)',
    58: 'IsNotVarBit test',
    60: 'RES:%d lookup',
    63: 'QuestkompassPos',
    64: 'QuestkompassOBJ',
    65: 'atmo_rg', 67: 'atmo_rg (same handler as 65)',
    75: 'atmo_rg', 76: 'atmo_rg', 105: 'atmo_rg',
    78: 'chest ("Truhe %s falscht benannt")',
    91: 'blacksmith UI (schmiede, UI_WND_BLACKSMITH)',
    92: 'teleport figure ("direkt Teleportiert weil ohne Listner")',
    94: 'versteck (hidden spot)', 140: 'versteck (hidden spot)',
    98: 'weather ("Setup Sector:%d,%d", rain/regen/thunder/snow)',
    104: 'SOUND_FX_', 127: 'SOUND_FX_', 128: 'SOUND_FX_',
    108: 'GetPoolPos', 109: 'Clear/GetPoolPos', 113: 'GetPoolPos to region',
    133: 'GetPoolPos',
    119: 'pool by region (DQ_Quest, POOL_RG%d_)',
    130: 'cInterpretSQW::Teleporter(hex=%x)',
    138: 'UI_WND_TASKBAR', 139: 'UI_WND_TASKBAR',
}


def disasm(lo, hi):
    """addr -> instruction text, Intel syntax."""
    out = subprocess.run(
        ['objdump', '-M', 'intel', '-d', f'--start-address={lo:#x}',
         f'--stop-address={hi:#x}', BINARY],
        capture_output=True, text=True).stdout
    insns = {}
    for line in out.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if m:
            insns[int(m.group(1), 16)] = m.group(3).strip()
    return insns


def rostring(va):
    """The NUL-terminated .rodata string at `va`, if it is a plausible one."""
    if not (RO_VMA <= va < RO_VMA + RO_SIZE):
        return None
    off = va - RO_VMA + RO_OFF
    end = d.find(b'\0', off, off + 200)
    if end < 0:
        return None
    s = d[off:end]
    if len(s) < 3 or not all(32 <= c < 127 or c in b'\t\n' for c in s):
        return None
    return s.decode('latin-1')


def rtti():
    """(typeinfo VA -> class, vtable VA -> class, vtable slot VA -> class).

    Built here rather than reused from analysis/rtti/: those artifacts are
    keyed to `analysis/lgp-2010/sacred-1.0.02-final`, a DIFFERENT build whose
    addresses do not line up with sacred_orig's.
    """
    name = re.compile(r'^N?\d+[A-Za-z_]')
    def dem(n):
        parts, i = [], 1 if n.startswith('N') else 0
        while i < len(n) and n[i].isdigit():
            j = i
            while j < len(n) and n[j].isdigit():
                j += 1
            ln = int(n[i:j])
            parts.append(n[j:j + ln])
            i = j + ln
        return '::'.join(parts) if parts else n

    def cstr(va):
        o = va - RO_VMA + RO_OFF if RO_VMA <= va < RO_VMA + RO_SIZE else None
        if o is None:
            o = va - DA_VMA + DA_OFF if DA_VMA <= va < DA_VMA + DA_SIZE else None
        if o is None:
            return None
        e = d.find(b'\0', o, o + 120)
        return d[o:e].decode('latin-1') if e > 0 else None

    def word(va):
        for lo, off, size in ((RO_VMA, RO_OFF, RO_SIZE), (DA_VMA, DA_OFF, DA_SIZE)):
            if lo <= va < lo + size:
                return struct.unpack_from('<I', d, off + va - lo)[0]

    # a typeinfo is [vptr to one of the few __*_type_info vtables, name*, ...]
    hits = collections.Counter()
    for lo, off, size in ((RO_VMA, RO_OFF, RO_SIZE), (DA_VMA, DA_OFF, DA_SIZE)):
        for i in range(0, size - 8, 4):
            a, b = struct.unpack_from('<II', d, off + i)
            if 0x8900000 <= a < 0x8920000:
                s = cstr(b)
                if s and name.match(s):
                    hits[a] += 1
    tiv = {a for a, c in hits.items() if c > 2}
    ti = {}
    for lo, off, size in ((RO_VMA, RO_OFF, RO_SIZE), (DA_VMA, DA_OFF, DA_SIZE)):
        for i in range(0, size - 8, 4):
            a, b = struct.unpack_from('<II', d, off + i)
            if a in tiv:
                s = cstr(b)
                if s and name.match(s):
                    ti[lo + i] = dem(s)
    vt, slots = {}, {}
    for lo, off, size in ((RO_VMA, RO_OFF, RO_SIZE), (DA_VMA, DA_OFF, DA_SIZE)):
        for i in range(0, size - 4, 4):
            a = struct.unpack_from('<I', d, off + i)[0]
            if a in ti:
                vt[lo + i + 4] = ti[a]                  # vtable starts after ti*
    for v, c in vt.items():
        for k in range(300):
            a = word(v + 4 * k)
            if a is None or not (TEXT_VMA <= a < TEXT_VMA + TEXT_SIZE):
                break
            slots.setdefault(a, c)
    return ti, vt, slots


def cases():
    """opcode -> handler address, from the jump table and the case stubs."""
    ents = [struct.unpack_from('<I', d, TABLE_VA - RO_VMA + RO_OFF + 4 * i)[0]
            for i in range(TABLE_N)]
    insns = disasm(*DISPATCH)
    order = sorted(insns)
    nxt = {a: (order[i + 1] if i + 1 < len(order) else None)
           for i, a in enumerate(order)}
    out = {}
    for op, entry in enumerate(ents):
        if entry == DEFAULT_CASE:
            continue                      # unused opcode
        a, seen, found = entry, set(), []
        while a and a not in seen and len(seen) < 40:
            seen.add(a)
            t = insns.get(a, '')
            m = re.match(r'call\s+([0-9a-f]+)', t)
            if m and int(m.group(1), 16) != ARG_FETCH:
                found.append(int(m.group(1), 16))
            m = re.match(r'jmp\s+([0-9a-f]+)\b', t)
            if m:
                tgt = int(m.group(1), 16)
                if tgt >= DEFAULT_CASE:   # falls into the shared tail: done
                    break
                a = tgt
                continue
            if t.startswith(('ret', 'jmp')):
                break
            a = nxt[a]
        out[op] = (found, entry)
    return out


def extents():
    """function start -> (start, end), from .eh_frame FDEs."""
    txt = subprocess.run([sys.executable, 'analysis/tools/ehframe_funcs.py',
                          BINARY], capture_output=True, text=True).stdout
    fns = {}
    for line in txt.splitlines():
        m = re.match(r'0x([0-9a-f]+)\s+0x([0-9a-f]+)', line)
        if m:
            lo, size = int(m.group(1), 16), int(m.group(2), 16)
            fns[lo] = (lo, lo + size)
    return fns


def profile():
    """opcode -> (record count, one sample argument list), over all 16 files."""
    import glob
    sys.path.insert(0, 'analysis/tools')
    import startcode
    out = {}
    for f in sorted(glob.glob('install/bin/*/*ode.bin')):
        for _off, op, _ln, args, ok in startcode.parse(open(f, 'rb').read()):
            if not ok:
                continue
            n, sample = out.get(op, (0, None))
            out[op] = (n + 1, sample if sample else args)
    return out


def markdown(table, path):
    prof = profile()
    with open(path, 'w') as o:
        o.write('# Sacred script opcodes\n\n'
                'Generated by `analysis/tools/opcodes.py` (rows 718-723). '
                'Opcode jump table at `0x086f4298`, 141 entries; the '
                'dispatcher is `0x0826e8ce`, its default case '
                '`0x082720dd` is `mov ecx,1; ret` -- an opcode with no case '
                'is silently ignored.\n\n'
                '`strings` are .rodata literals inside the handler itself. '
                '`name` is filled in only where those strings say what the '
                'handler does.\n\n'
                '`classes` are RTTI classes the handler names outright -- a '
                'typeinfo it dynamic_casts to, a vtable it constructs, or a '
                'method it calls directly. `cEvent`, `cEventNetwork`, '
                '`cObject`, `cCreature` and `cFile_ram` are filtered out: '
                'almost every handler touches them, so they carry no '
                'information. Most handlers name nothing beyond those.\n\n'
                '| op | handler | size | n in data | name | classes | strings | sample args |\n'
                '|---|---|---|---|---|---|---|---|\n')
        for op in range(TABLE_N):
            e = table.get(op)
            n, sample = prof.get(op, (0, None))
            h = e['handler'] if e else '(default: no-op)'
            strs = ' / '.join(s.strip() for s in e['strings'][:4]) if e else ''
            args = ', '.join(str(a)[:32] for a in (sample or [])[:6])
            o.write(f"| {op} | {h} | {e['size'] if e else ''} | {n} | "
                    f"{NAMES.get(op, '')} | {', '.join(e['classes']) if e else ''} | "
                    f"{strs.replace('|', '/')} | {args.replace('|', '/')} |\n")


def main():
    fns = extents()
    ti, vt, vslot = rtti()
    table, inline = {}, []
    cs = cases()
    entries = sorted({e for _c, e in cs.values()} | {DEFAULT_CASE})
    for op, (calls, entry) in sorted(cs.items()):
        h = calls[0] if calls else None
        if h:
            lo, hi = fns.get(h, (h, h + 0x400))
        else:
            # No delegated call: the case IS the implementation. Bound it by
            # the next case entry in address order.
            lo = entry
            hi = min([e for e in entries if e > entry] + [DISPATCH[1]])
        if h and h not in fns:
            inline.append(op)                 # extent unknown: strings unsafe
        strs, cls = [], collections.Counter()
        if h:
            for a, t in sorted(disasm(lo, min(hi, lo + 0x6000)).items()):
                for m in re.finditer(r'0x([0-9a-f]{7,8})', t):
                    v = int(m.group(1), 16)
                    s = rostring(v)
                    if s and s not in strs:
                        strs.append(s)
                    # a class the handler names: its typeinfo (dynamic_cast),
                    # its vtable (construction), or one of its methods called
                    # directly.
                    c = ti.get(v) or vt.get(v) or vslot.get(v)
                    if c and c not in BORING:
                        cls[c] += 1
        table[op] = dict(handler=hex(h) if h else f'inline@{entry:#x}',
                         size=hi - lo,
                         extra=[hex(c) for c in calls[1:]],
                         strings=strs,
                         classes=[c for c, _ in cls.most_common(4)])
        print(f"{op:<4} {str(table[op]['handler']):<12} {table[op]['size']:<7} "
              f"{' | '.join(strs[:6])}")
    if '--json' in sys.argv:
        json.dump(table, open(sys.argv[sys.argv.index('--json') + 1], 'w'),
                  indent=1)
    if inline:
        print('# no .eh_frame extent, strings unreliable: '
              + ', '.join(map(str, inline)), file=sys.stderr)
    if '--md' in sys.argv:
        markdown(table, sys.argv[sys.argv.index('--md') + 1])


if __name__ == '__main__':
    main()
