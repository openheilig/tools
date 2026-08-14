#!/usr/bin/env python3
"""Live memory scan/patch for the retail sacred process (06-02 transport).

    p6_memscan.py find  PID X [Y]      i32 hits for X (optionally with Y within 64B)
    p6_memscan.py refine PID X2        re-read prior find's hits, keep value == X2
    p6_memscan.py write PID ADDR VAL   patch i32 VAL at ADDR (hex ok)
    p6_memscan.py dump  PID ADDR LEN   hexdump LEN bytes around ADDR

Hits persist to /tmp/memscan-hits.txt so find->refine chains work across
game states. Reads /proc/PID/mem directly -- the shim's constructor calls
prctl(PR_SET_PTRACER, ANY), so yama scope 1 is not a problem.
"""
import os
import struct
import sys

HITS = "/tmp/memscan-hits.txt"


def regions(pid):
    out = []
    with open(f"/proc/{pid}/maps") as fh:
        for line in fh:
            parts = line.split()
            if parts[1] != "rw-p":
                continue
            path = parts[-1] if len(parts) == 6 else ""
            # ponytail: hero state may live in .data/.bss (file-backed, small)
            # or anon heap; only skip LARGE file-backed maps (textures/paks).
            lo, hi = (int(x, 16) for x in parts[0].split("-"))
            if path and not path.startswith("[") and hi - lo > 32 * 1024 * 1024:
                continue
            out.append((lo, hi, path or "anon"))
    return out


def scan(pid, needle):
    hits = []
    with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
        for lo, hi, tag in regions(pid):
            try:
                mem.seek(lo)
                buf = mem.read(hi - lo)
            except OSError:
                continue
            off = 0
            while True:
                i = buf.find(needle, off)
                if i < 0:
                    break
                hits.append((lo + i, tag))
                off = i + 1
    return hits


def read_i32(pid, addr):
    with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
        mem.seek(addr)
        return struct.unpack("<i", mem.read(4))[0]


def main():
    cmd, pid = sys.argv[1], sys.argv[2]
    if cmd == "find":
        x = int(sys.argv[3], 0)
        y = int(sys.argv[4], 0) if len(sys.argv) > 4 else None
        hits = scan(pid, struct.pack("<i", x))
        print(f"{len(hits)} hits for i32 {x}")
        kept = []
        if y is not None:
            yp = struct.pack("<i", y)
            with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
                for addr, tag in hits:
                    try:
                        mem.seek(addr - 64)
                        ctx = mem.read(132)
                    except OSError:
                        continue
                    if yp in ctx:
                        kept.append((addr, tag))
            print(f"{len(kept)} with i32 {y} within +/-64B")
        else:
            kept = hits
        with open(HITS, "w") as fh:
            for addr, tag in kept:
                fh.write(f"{addr} {tag}\n")
        for addr, tag in kept[:40]:
            print(f"  0x{addr:08x}  {tag}")
    elif cmd == "refine":
        want = int(sys.argv[3], 0)
        kept = []
        with open(HITS) as fh:
            addrs = [(int(l.split()[0]), l.split()[1]) for l in fh if l.strip()]
        for addr, tag in addrs:
            try:
                if read_i32(pid, addr) == want:
                    kept.append((addr, tag))
            except OSError:
                pass
        print(f"{len(kept)}/{len(addrs)} now hold {want}")
        with open(HITS, "w") as fh:
            for addr, tag in kept:
                fh.write(f"{addr} {tag}\n")
        for addr, tag in kept[:40]:
            print(f"  0x{addr:08x}  {tag}")
    elif cmd == "write":
        addr, val = int(sys.argv[3], 0), int(sys.argv[4], 0)
        with open(f"/proc/{pid}/mem", "r+b", buffering=0) as mem:
            mem.seek(addr)
            old = struct.unpack("<i", mem.read(4))[0]
            mem.seek(addr)
            mem.write(struct.pack("<i", val))
        print(f"0x{addr:08x}: {old} -> {val}")
    elif cmd == "dump":
        addr, ln = int(sys.argv[3], 0), int(sys.argv[4], 0)
        with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
            mem.seek(addr)
            buf = mem.read(ln)
        for k in range(0, ln, 16):
            chunk = buf[k:k + 16]
            hexs = " ".join(f"{c:02x}" for c in chunk)
            i32s = " ".join(f"{struct.unpack('<i', chunk[j:j+4])[0]:>11}"
                            for j in range(0, len(chunk) - 3, 4))
            print(f"  0x{addr+k:08x}  {hexs:<48}  {i32s}")
    else:
        raise SystemExit(__doc__)


main()
