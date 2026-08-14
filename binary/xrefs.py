#!/usr/bin/env python3
"""Find every `call`/`jmp rel32` in .text that targets a given address.

    python3 analysis/tools/binary/xrefs.py install/sacred 0x816b34c

Why not grep the objdump: a whole-binary `objdump -d` of this stripped
binary desyncs (AGENTS.md "Three traps that cost hours"), so anything read
out of it can be off by a few bytes or missing entirely.  A direct scan for
the 5-byte `E8/E9 rel32` encoding cannot desync, because it checks every
offset independently and verifies the arithmetic.

False positives are possible (any 5 bytes of data can look like a call), so
each hit is reported with the owning function from ehframe_funcs -- a hit
inside a real function is a real call; a hit in a data blob is not.
"""
import struct
import sys

from ehframe_funcs import fdes, load


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    f, secs = load(sys.argv[1])
    target = int(sys.argv[2], 0)
    tva, toff, tsz = secs['.text']

    owners = sorted(s for s, _ in fdes(f, *secs['.eh_frame']))

    def owner(a):
        import bisect
        i = bisect.bisect_right(owners, a) - 1
        return owners[i] if i >= 0 else 0

    for i in range(tsz - 5):
        if f[toff + i] not in (0xE8, 0xE9):
            continue
        rel, = struct.unpack_from('<i', f, toff + i + 1)
        site = tva + i
        if site + 5 + rel == target:
            kind = 'call' if f[toff + i] == 0xE8 else 'jmp '
            o = owner(site)
            print(f'{site:#010x}  {kind}  in {o:#x}+{site - o:#x}')


if __name__ == '__main__':
    main()
