import sys, os
sys.path.insert(0, 'analysis/tools/binary')
import vtables as V

def emit(path):
    classes, blob, v2o = V.main(path)
    rows = []
    for name, r in sorted(classes.items()):
        best, n = 0, 0
        for vt in r["vtables"]:
            c = len(V.vfuncs(blob, v2o, vt))
            if c > n:
                best, n = vt, c
        if not best:
            continue
        for slot, a in enumerate(V.vfuncs(blob, v2o, best)):
            rows.append((a, "%s__vf%02d" % (name.replace("::", "__"), slot), name, slot))
    rows.sort()
    return rows

if __name__ == "__main__":
    rows = emit(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "-"
    f = sys.stdout if out == "-" else open(out, "w")
    f.write("addr\tname\tclass\tslot\n")
    for a, n, c, s in rows:
        f.write("0x%08x\t%s\t%s\t%d\n" % (a, n, c, s))
