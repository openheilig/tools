#!/usr/bin/env python3
"""Recover Sacred's original source tree from the Armalion debug build's asserts.

The 2001-12-11 Armalion prerelease is a DEBUG build, so its assert strings
survived: the `C:\\Projects\\Armalion\\armaSource\\...` path of every file that
fired one, the `cClass::method()` naming the function, and the invariant text
itself. Retail is a release build and has none of this.

Walking the string table in FILE OFFSET order recovers the association,
because the linker emits a translation unit's string literals together: the
`cClass::method()` names between two path strings belong to the file named by
the nearer path. That is an ordering property of the object file, not an
inference about the code.

What it yields, none of which is otherwise reachable:

  * the module tree -- engine/object/{creature,items,base,inventory,sfx},
    engine/{granny,scenery,weather,kampaign,calendar}, ui/{windows,controls,
    commands}, library/{dx7,file,formats,math,resource,generic,timer},
    scripts, particle, kernel, sound, movie
  * which file a class lives in, e.g. combat in creature_fighting.cpp
  * the engine's own invariants, e.g. `fp->code[ip]<256` (the script VM's
    opcode is a byte indexing a byte array), `chunk.type==CHUNK_TYPE_ACS`
    and `hdr.ver==2` (the compiled-script container).

CAUTION. Armalion is a PRERELEASE, two years before retail. A name here is
evidence about Armalion and a hypothesis about retail; the class names it
shares with retail RTTI are the part that carries over, and `--rtti` reports
exactly that overlap rather than assuming it.

Usage:  armasource.py [--rtti <retail-classes.txt>] [out.tsv]
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.join(ROOT, 'donotpublish/analysis/builds/'
                          'armalion-2001-12-11/armalion.exe')
PATH = re.compile(r'armaSource[\\/][^\s"]*\.(?:cpp|h)', re.I)
METH = re.compile(r'\b([A-Za-z_]\w*)::([~A-Za-z_]\w*)\s*\(')


def strings_in_order(path=EXE, minlen=4):
    """-> [(file_offset, text)] in file order. Order is the whole point."""
    out = subprocess.run(['strings', '-a', '-t', 'd', f'-n{minlen}', path],
                         capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.split('\n'):
        line = line.strip()
        if not line:
            continue
        off, _, text = line.partition(' ')
        if off.isdigit():
            rows.append((int(off), text))
    return rows


def attribute(rows):
    """-> [(module, file, class, method, offset)].

    A method string is attributed to the nearest preceding source path, or to
    the nearest following one when it precedes every path (MSVC emits the
    condition before the file for the first assert of a unit).
    """
    paths = [(o, PATH.search(t).group(0).replace('\\', '/').lower())
             for o, t in rows if PATH.search(t)]
    if not paths:
        raise ValueError(f'{EXE}: no armaSource paths -- wrong binary?')
    out = []
    seen = set()
    for off, text in rows:
        for m in METH.finditer(text):
            key = (m.group(1), m.group(2))
            if key in seen:
                continue                       # an assert repeats per condition
            seen.add(key)
            before = [p for p in paths if p[0] <= off]
            near = before[-1] if before else paths[0]
            f = near[1].split('armasource/', 1)[-1]
            mod = f.rsplit('/', 1)[0] if '/' in f else '.'
            out.append((mod, f, m.group(1), m.group(2), off))
    return out


def main():
    a = sys.argv[1:]
    rtti = None
    if '--rtti' in a:
        i = a.index('--rtti')
        rtti = a[i + 1]
        del a[i:i + 2]
    rows = strings_in_order()
    rec = attribute(rows)
    files = sorted({r[1] for r in rec} |
                   {PATH.search(t).group(0).replace('\\', '/').lower()
                    .split('armasource/', 1)[-1]
                    for _, t in rows if PATH.search(t)})
    classes = sorted({r[2] for r in rec})

    text = 'module\tfile\tclass\tmethod\toffset\n' + ''.join(
        f'{m}\t{f}\t{c}\t{me}\t{o}\n' for m, f, c, me, o in sorted(rec))
    if a:
        open(a[0], 'w', encoding='utf-8').write(text)
    else:
        print(text, end='')

    print(f'armasource: {len(files)} source files, {len(rec)} method asserts, '
          f'{len(classes)} classes', file=sys.stderr)
    if rtti:
        have = set(re.findall(r'\b(c[A-Z]\w+)\b',
                              open(rtti, encoding='utf-8', errors='replace').read()))
        both = sorted(set(classes) & have)
        print(f'  {len(both)} of {len(classes)} also in retail RTTI: '
              f'{" ".join(both)}', file=sys.stderr)
    # the recovery is worthless if the ordering trick did not bind anything
    return 0 if len(files) > 40 and len(rec) > 60 else 1


if __name__ == '__main__':
    sys.exit(main())
