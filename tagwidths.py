#!/usr/bin/env python3
"""Derive the script tag widths from the interpreter, by FOLLOWING CONTROL FLOW.

Row 719 tried to read the widths by slicing each handler's extent as
[start, next_handler_start) and it scored WORSE than the fitted table -- because
switch cases are not laid out contiguously in tag order, so a handler with no
cursor advance of its own silently inherited its neighbour's.

This walks the CFG instead. From each handler entry in the jump table it
explores every path to the shared epilogue, accumulating the cursor advance:

    add DWORD PTR [esi], imm   ->  advance += imm
    inc DWORD PTR [esi]        ->  advance += 1
    add DWORD PTR [esi], reg   ->  variable (a string length)
    call strcpy                ->  the payload is a NUL-terminated string

KNOWN BLIND SPOT (row 726): a FIXED PREFIX BEFORE a variable-length payload is
invisible here. Tags 0x48/0x49/0x4a/0x5d/0x5e/0x6d/0x6e (0x0826cb0e) and 0x7a
(0x0826de28) read a u32 into the numeric slots and THEN strcpy a string; the
walk sees the strcpy, reports STR, and the u32 is lost. If a tag is reported
STR, check its handler for a `mov [ecx+edx*4+0xa86c],eax` before the strcpy.

A handler with one advance on every path is a fixed width of (advance - 1),
one byte of that being the tag itself. Several distinct advances mean a
VARIANT, and those are reported with all their values rather than averaged
into a lie.

Usage:  tagwidths.py <objdump-of-interpreter> [--verbose]
"""
import re, sys, struct, collections

BINARY = 'install/sacred_orig'
TABLE_VA = 0x86f3fbc          # the 162-entry tag jump table
TABLE_N = 0xa2
DEFAULT_HANDLER = 0x826e0bc   # 66 tags land here
EPILOGUE = {0x826e8b2, 0x826e8b9, 0x826e8c4}
RO_VMA, RO_OFF = 0x086d8200, 0x690200

JCC = re.compile(r'^(j\w+)\s+([0-9a-f]+)')
ADD_IMM = re.compile(r'^add\s+DWORD PTR \[esi\],(0x[0-9a-f]+)$')
ADD_REG = re.compile(r'^add\s+DWORD PTR \[esi\],e\w\w$')


def load_insns(path):
    """addr -> (text, next_addr). objdump order gives instruction lengths."""
    rows = []
    for line in open(path):
        m = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if m:
            rows.append((int(m.group(1), 16), m.group(3).strip()))
    rows.sort()
    insns = {}
    for i, (a, t) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        insns[a] = (t, nxt)
    return insns


def walk(entry, insns, limit=4000):
    """Every path from `entry` to the epilogue.

    Returns a set of (advance, saw_strcpy) outcomes -- one per terminal path,
    so a handler that copies a string on one branch and takes a fixed field on
    another is reported as the VARIANT it is instead of collapsing to STR."""
    outcomes = set()
    seen = set()
    stack = [(entry, 0, False)]
    steps = 0
    while stack and steps < limit:
        addr, adv, sawstr = stack.pop()
        steps += 1
        if addr is None or addr in EPILOGUE:
            outcomes.add((adv, sawstr))
            continue
        key = (addr, adv, sawstr)
        if key in seen:
            continue
        seen.add(key)
        item = insns.get(addr)
        if item is None:
            outcomes.add((adv, sawstr))
            continue
        text, nxt = item
        if 'strcpy' in text:
            sawstr = True
        m = ADD_IMM.match(text)
        if m:
            adv += int(m.group(1), 16)
        elif ADD_REG.match(text):
            outcomes.add((-1, True))              # advanced by a computed length
            continue
        elif text.startswith('inc    DWORD PTR [esi]'):
            adv += 1
        if text.startswith('ret'):
            outcomes.add((adv, sawstr))
            continue
        j = JCC.match(text)
        if j:
            target = int(j.group(2), 16)
            stack.append((target, adv, sawstr))
            if j.group(1) != 'jmp':               # conditional: fall through too
                stack.append((nxt, adv, sawstr))
            continue
        stack.append((nxt, adv, sawstr))
    return outcomes


def main():
    d = open(BINARY, 'rb').read()
    off = TABLE_VA - RO_VMA + RO_OFF
    ents = [struct.unpack_from('<I', d, off + 4 * i)[0] for i in range(TABLE_N)]
    insns = load_insns(sys.argv[1] if len(sys.argv) > 1 else '/tmp/interp.txt')

    per_handler = {}
    for h in sorted(set(ents)):
        if h == DEFAULT_HANDLER:
            continue
        per_handler[h] = walk(h, insns)

    out = {}
    for tag, h in enumerate(ents):
        if h == DEFAULT_HANDLER:
            continue
        outs = per_handler[h]
        strs = {o for o in outs if o[1] or o[0] == -1}
        fixed = {o[0] for o in outs if not o[1] and o[0] > 0}
        if strs and not fixed:
            out[tag] = 'STR'
        elif strs and fixed:
            out[tag] = 'VARIANT'
        elif not fixed:
            out[tag] = 'END'
        elif len(fixed) == 1:
            out[tag] = next(iter(fixed)) - 1
        else:
            out[tag] = 'MULTI' + str(sorted(x - 1 for x in fixed))
    for tag in sorted(out):
        print(f"0x{tag:02x}\t{out[tag]}")
    print(f"# {len(out)} tags; shapes: "
          f"{collections.Counter(str(v).split('[')[0] for v in out.values()).most_common()}",
          file=sys.stderr)


if __name__ == '__main__':
    main()
