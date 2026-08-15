#!/usr/bin/env python3
"""Read the Armalion debug build's DEBUG.LOG -- a full engine session, traced.

`analysis/builds/armalion-2001-12-11/DEBUG.LOG` is what the 2001-12-11
prerelease printed on one complete run: start-up, every container it opened,
the campaign loading, and shutdown. Retail prints none of it. Three things in
it are evidence rather than colour:

  CLASS SIZES. The build dumps `sizeof` for 22 engine classes before doing
  anything else. That is a hard constraint on any struct claim -- a recovered
  layout that does not total the printed size is wrong, and one that does is
  agreeing with the compiler.

  CONTAINER VERSIONS. Each `.pak` is logged with its version and entry count,
  so the same containers can be compared against the retail files three years
  later. Same version means the layout did not change and Armalion-era
  knowledge transfers; a bumped version means it must not be assumed to.

  NAMES. `cItemDataMgr`, `cTextureLoader`, `cGrannyModelManager`,
  `cObjectManager`, `cUI_ManagerThread`, `cCommand_*` -- the loaders' own
  class names, matching the source tree in `armasource.py`.

The log is latin-1, not UTF-8.

CAUTION: Armalion is a prerelease. Only a version that MATCHES retail's licenses
carrying a reading across; everything else is Armalion's own state.

Usage:  armalog.py [--check <retail-pak-dir>]
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, 'donotpublish/analysis/builds/'
                          'armalion-2001-12-11/DEBUG.LOG')
PAKS = os.path.join(ROOT, 'donotpublish/install/pak')

SIZE = re.compile(r'^([a-zA-Z_]\w*)\s+(\d+)\s*$')
# "TEXTURES.PAK v3 entries17866", "ITEMS.PAK V2 #32768", ".\SCRIPTS\RESOURCE.PAK v1 entries65536"
PAK = re.compile(r'([\w.\\]*?([A-Z0-9_]+\.PAK))\s+[vV](\d+)\s*(?:entries|#)\s*(\d+)')


def read(path=LOG):
    return open(path, encoding='latin-1').read().split('\n')


def parse(lines):
    """-> (sizes, containers). Both keyed by name, first mention wins."""
    sizes, paks = {}, {}
    for ln in lines:
        ln = ln.rstrip()
        m = SIZE.match(ln)
        if m and not ln.startswith(' '):
            sizes.setdefault(m.group(1), int(m.group(2)))
        m = PAK.search(ln)
        if m:
            paks.setdefault(m.group(2), (int(m.group(3)), int(m.group(4))))
    return sizes, paks


def retail_paks(d=PAKS):
    """-> {filename: (magic, ver, count)} straight off each header."""
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if not f.endswith('.pak'):
            continue
        with open(os.path.join(d, f), 'rb') as fh:
            h = fh.read(8)
        if len(h) < 8:
            continue
        magic, ver, n = h[:3].decode('latin-1'), h[3], struct.unpack('<I', h[4:8])[0]
        out[f] = (magic, ver, n)
    return out


if __name__ == '__main__':
    sizes, paks = parse(read())
    print(f'# {len(sizes)} class sizes')
    for k, v in sorted(sizes.items(), key=lambda kv: -kv[1]):
        print(f'{k}\t{v}')
    print(f'\n# {len(paks)} containers, as Armalion 2001-12-11 loaded them')
    for k, (v, n) in sorted(paks.items()):
        print(f'{k}\tv{v}\t{n}')

    if '--check' in sys.argv:
        r = retail_paks()
        print(f'\n# retail, {len(r)} files -- version match means the layout is frozen')
        # match on the magic's own name, not the filename: they were renamed
        by_ver = {}
        for f, (mg, v, n) in sorted(r.items()):
            by_ver.setdefault(mg, (f, v, n))
            print(f'{f}\t{mg}\tv{v}\t{n}')
        same = [(a, b) for a, (av, _) in paks.items()
                for b, (bf, bv, _bn) in by_ver.items()
                if a.split('.')[0].startswith(b) and av == bv]
        print(f'\n# {len(same)} containers at the SAME version three years apart: '
              + ' '.join(f'{a}={b}' for a, b in same))
    if len(sizes) < 15 or len(paks) < 8:
        print('armalog: log did not parse as expected', file=sys.stderr)
        sys.exit(1)
