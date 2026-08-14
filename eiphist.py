#!/usr/bin/env python3
"""Resolve the autopilot EIP sampler's output against the same run's maps.

    SACRED_PROF=1 ... play.sh          -> /tmp/sacred-eip.bin
                                          /tmp/sacred-maps.txt (dumped in-process)
    python3 analysis/tools/eiphist.py [first_frac] [last_frac]

Prints a module histogram for an early slice (normal running) and a late slice
(the phase under investigation), plus the hottest addresses of the late slice
as module+offset -- feed those straight to objdump.

Sanity check that matters: if no sample lands in an executable *section*, the
maps and the samples are from different processes.  That already happened once.
"""
import collections
import struct
import sys

MAPS = "/tmp/sacred-maps.txt"
BIN = "/tmp/sacred-eip.bin"


def load_maps():
    out = []
    for line in open(MAPS):
        # maxsplit: the project path contains a space ("Sacred Gold"), and a
        # plain split() truncates it to ".../Sacred" -- which once made xshim.so
        # look like the game binary.
        p = line.split(None, 5)
        if len(p) < 6 or "x" not in p[1]:
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        out.append((a, b, int(p[2], 16), p[5].strip()))
    return out


def main():
    head = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
    tail = float(sys.argv[2]) if len(sys.argv) > 2 else 0.7
    maps = load_maps()
    d = open(BIN, "rb").read()
    n = len(d) // 4
    eips = struct.unpack("<%dI" % n, d[: n * 4])

    def res(a):
        for s, e, off, nm in maps:
            if s <= a < e:
                return nm.split("/")[-1], a - s + off
        return "???", a

    for label, sl in (("early", eips[: int(n * head)]), ("late", eips[int(n * tail):])):
        c = collections.Counter(res(a)[0] for a in sl)
        print(f"--- {label} ({len(sl)} samples) ---")
        for k, v in c.most_common(8):
            print(f"  {v:6} {100 * v / max(1, len(sl)):5.1f}%  {k}")

    print("--- hottest addresses, late slice ---")
    late = eips[int(n * tail):]
    c = collections.Counter(res(a) for a in late)
    for (nm, off), v in c.most_common(12):
        print(f"  {v:6} {100 * v / max(1, len(late)):5.1f}%  {nm}+0x{off:x}")


if __name__ == "__main__":
    main()
