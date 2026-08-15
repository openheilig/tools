import sys, os
# resolve relative to THIS file, not the caller's cwd -- the old hardcoded
# 'analysis/tools/binary' only worked from one directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
            # carry the ancestry: a slot may hold a BASE class's method, so a
            # consumer comparing a method's class to this one needs the chain
            anc, seen, stack = [], set(), list(r.get("bases", []))
            while stack:
                b = stack.pop()
                if b in seen or b not in classes:
                    if b not in seen:
                        seen.add(b); anc.append(b)
                    continue
                seen.add(b); anc.append(b)
                stack.extend(classes[b].get("bases", []))
            rows.append((a, "%s__vf%02d" % (name.replace("::", "__"), slot),
                         name, slot, ";".join(anc)))
    rows.sort()
    return rows

if __name__ == "__main__":
    rows = emit(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "-"
    f = sys.stdout if out == "-" else open(out, "w")
    f.write("addr\tname\tclass\tslot\tancestors\n")
    for a, n, c, s, anc in rows:
        f.write("0x%08x\t%s\t%s\t%d\t%s\n" % (a, n, c, s, anc))
