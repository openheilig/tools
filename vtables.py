#!/usr/bin/env python3
"""Recover C++ vtables and the class hierarchy from the stripped LGP Linux binary.

AGENTS.md records the Linux port's RTTI as "stripped (only libstdc++ typeinfo
survives)".  That is not correct: 318 Itanium-ABI mangled typeinfo *name*
strings ("13cCreatureHero") are still in .rodata.  Given those we can walk the
standard layout backwards and recover far more than names:

    typeinfo name string  <--  type_info.name (+4)
    type_info             <--  vtable[-1]
    vtable[0..]           =    the class's virtual functions
    type_info+8           ->   base class type_info   (__si_class_type_info)

`sacred` is a non-PIE ET_EXEC, so every internal pointer is stored literally in
the file -- no relocation processing needed.

    python3 analysis/tools/vtables.py install/sacred
"""
import struct
import sys
from collections import OrderedDict

U32 = struct.Struct("<I")


def sections(blob):
    """Yield (name, vaddr, file_off, size) for each section of a 32-bit LE ELF."""
    if blob[:4] != b"\x7fELF" or blob[4] != 1:
        sys.exit("not a 32-bit ELF")
    e_shoff, = U32.unpack_from(blob, 0x20)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", blob, 0x2E)
    hdrs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, _typ, _flags, addr, off, size = struct.unpack_from("<IIIIII", blob, o)
        hdrs.append((name, addr, off, size))
    stroff = hdrs[e_shstrndx][2]
    out = []
    for name, addr, off, size in hdrs:
        end = blob.index(b"\0", stroff + name)
        out.append((blob[stroff + name:end].decode(), addr, off, size))
    return out


def main(path):
    blob = open(path, "rb").read()
    secs = sections(blob)
    # every section that is actually present in the file and mapped
    mapped = [(n, a, o, s) for (n, a, o, s) in secs if a and s and n != ".bss"]

    def v2o(va):
        for _n, a, o, s in mapped:
            if a <= va < a + s:
                return o + (va - a)
        return None

    # 1. locate mangled typeinfo name strings: "<len>c<Name>\0"
    names = {}          # vaddr -> mangled name
    for _n, a, o, s in mapped:
        data = blob[o:o + s]
        pos = 0
        while True:
            i = data.find(b"c", pos)
            if i < 0:
                break
            pos = i + 1
            j = i
            while j > 0 and data[j - 1:j].isdigit():
                j -= 1
            if j == i:
                continue
            end = data.find(b"\0", i)
            if end < 0 or end - j > 64:
                continue
            cand = data[j:end]
            try:
                txt = cand.decode("ascii")
            except UnicodeDecodeError:
                continue
            body = txt.lstrip("0123456789")
            digits = txt[:len(txt) - len(body)]
            if not digits or int(digits) != len(body):
                continue
            if not body[:1] == "c" or not body[1:2].isupper():
                continue
            names[a + j] = txt

    # 2. index every 4-byte word in mapped sections -> where it occurs
    where = {}
    for _n, a, o, s in mapped:
        data = blob[o:o + s]
        for k in range(0, (s & ~3) - 3, 4):
            w, = U32.unpack_from(data, k)
            if w:
                where.setdefault(w, []).append(a + k)

    # 3. name string <- type_info.name(+4);  type_info <- vtable[-1]
    classes = OrderedDict()
    for nva, mangled in sorted(names.items(), key=lambda kv: kv[1].lstrip("0123456789")):
        pretty = mangled.lstrip("0123456789")
        for name_slot in where.get(nva, []):
            ti = name_slot - 4
            vts = [w + 4 for w in where.get(ti, [])]
            rec = classes.setdefault(pretty, {"mangled": mangled, "ti": ti, "vtables": [], "bases": []})
            rec["vtables"] = sorted(set(rec["vtables"]) | set(vts))

    def ti_name(va):
        """Resolve a type_info address to a class name, if it is one."""
        off = v2o(va + 4) if va else None
        if off is None:
            return None
        p, = U32.unpack_from(blob, off)
        n = names.get(p)
        return n.lstrip("0123456789") if n else None

    for rec in classes.values():
        ti = rec["ti"]
        # __si_class_type_info: one base pointer at +8
        b = ti_name(read32(blob, v2o, ti + 8))
        if b:
            rec["bases"] = [b]
            continue
        # __vmi_class_type_info: flags@+8, base_count@+12, then (base_ti, off)*
        cnt = read32(blob, v2o, ti + 12)
        if 0 < cnt <= 8:
            got = []
            for k in range(cnt):
                nb = ti_name(read32(blob, v2o, ti + 16 + k * 8))
                if nb:
                    got.append(nb)
            rec["bases"] = got
    return classes, blob, v2o


def read32(blob, v2o, va):
    off = v2o(va)
    if off is None:
        return 0
    return U32.unpack_from(blob, off)[0]


def vfuncs(blob, v2o, vt, limit=64):
    out = []
    off = v2o(vt)
    if off is None:
        return out
    for k in range(limit):
        w, = U32.unpack_from(blob, off + k * 4)
        # plausible .text pointer for this binary
        if not (0x8048000 <= w < 0x8900000):
            break
        out.append(w)
    return out


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "install/sacred"
    classes, blob, v2o = main(p)
    print(f"# vtable recovery from {p}: {len(classes)} classes with typeinfo")
    print(f"# {'class':32} {'typeinfo':>10} {'vtable':>10} {'#virt':>6}  base")
    for name, r in sorted(classes.items()):
        # a base-class pointer inside another type_info also equals our ti, so
        # score every candidate and keep the one that actually looks like a
        # vtable (i.e. is followed by the most .text pointers)
        best, n = 0, 0
        for vt in r["vtables"]:
            c = len(vfuncs(blob, v2o, vt))
            if c > n:
                best, n = vt, c
        r["vtable"], r["nvirt"] = best, n
        print(f"{name:34} 0x{r['ti']:08x} 0x{best:08x} {n:6}  {', '.join(r['bases'])}")
