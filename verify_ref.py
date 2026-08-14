#!/usr/bin/env python3
"""Reference output for godot-port/verify.gd -- the Python side of the parity check.

Personal-use interoperability work on legally-owned media. Output stays local.

  ./verify_ref.py > /tmp/ref.txt
  godot --headless --path ../../godot-port --script res://verify.gd > /tmp/got.txt
  diff /tmp/ref.txt /tmp/got.txt

Prints the same tab-separated facts in the same order, minus the timing column
(which is Godot-only) and the `install` line (which is a path). Also mirrors
verify.gd's layering check fact-for-fact -- see LAYER_RULES/layer_check().
"""
import hashlib, math, os, struct, sys, zlib

# grn_tagwalk.py shares this directory -- imported, never translated, so the
# corpus-level independence Plan 03 established (03-03-SUMMARY.md) is not
# undone by a second hand-written walker living in this file too.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grn_tagwalk
import grn_bonenames

SECTORS = [(49, 49), (50, 50), (51, 51), (0, 15), (14, 19), (31, 24), (99, 99)]
# Deviation from 04-01-PLAN.md Task 3's literal text (documented in
# 04-01-SUMMARY.md): mirrors godot-port/verify.gd's WALKABLE_SECTORS --
# reusing SECTORS directly would leave every sampled sector at zero
# regions (measured, not assumed), which the task's own acceptance
# criteria ("non-zero region/open count", "md5 discriminates") make
# impossible to satisfy that way. A dedicated sample list follows this
# file's existing SECTORS/TEXTURES/MODELS convention rather than mutating
# SECTORS and disturbing the `sector` fact line Phase 1-3 already rely on.
WALKABLE_SECTORS = [(64, 39), (4, 37), (52, 51), (0, 15), (14, 19), (31, 24), (99, 99)]
TEXTURES = [0, 1, 2, 1000, 5000, 20000]
# BAT.GRN, GLADIATOR.GRN, GLAD_SA5_SHOULDER.GRN -- 03-PATTERNS.md's sampled
# set, mirrored verbatim by godot-port/verify.gd's MODELS constant.
MODELS = [1, 589, 203]
# One attack, one idle, one run, two bone counts between them -- mirrored
# verbatim by godot-port/verify.gd's MOTIONS constant (Plan 05-05 Task 2).
MOTIONS = [2847, 2899, 2903]
PAK_HDR, PAK_IDX = 256, 12
KEY_HDR, KEY_REC = 256, 768
SECT, CELL, NAME = 64, 32, 32

# Region table constants, independently derived from the byte layout (not a
# translation of godot-port/sacred.gd's Regions class -- see region_list()).
REGION_TABLE_OFF = NAME + SECT * SECT * CELL
REGION_REC = 36
REGION_TYPE = 6
# FLOOR, DOOR, STEP, OPEN -- mirrors godot-port/world/walkable.gd's allowlist as a
# plain constant, the same way LAYER_RULES above mirrors verify.gd's.
WALKABLE_CLASSES = {2, 9, 0xA, 0x10}   # FLOOR, DOOR, STEP, OPEN

GAME = os.environ.get("SACRED_INSTALL") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../../install")
PORT = os.environ.get("SACRED_PORT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../../godot-port")

# world/ never touches the scene tree/threads; view/ never names a world
# type or defines its own per-frame entry point -- checked, not just written.
LAYER_RULES = {
    "world": ["Node3D", "MeshInstance3D", "add_child", "get_tree", "queue_free",
        "SectorView", "IsoCamera", "Thread", "WorkerThreadPool", "call_deferred"],
    "view": ["ActorRegistry", "ActorState", "RecordStore", "Sim.",
        "func _process(", "func _physics_process("],
}


def strip_comments(src):
    """Blanks comment-only lines, truncates inline ones -- preserves line count."""
    out = []
    for line in src.split("\n"):
        if line.strip().startswith("#"):
            out.append("")
            continue
        hash_idx = line.find("#")
        out.append(line if hash_idx == -1 else line[:hash_idx])
    return "\n".join(out)


def layer_check():
    """Forbidden-token scan; violations print file:line:token on stderr, last
    stdout line is always "layer\\tfiles=<n>\\tviolations=<n>"."""
    files = 0
    violations = 0
    for subdir in sorted(LAYER_RULES):
        forbidden = LAYER_RULES[subdir]
        dir_path = os.path.join(PORT, subdir)
        for name in sorted(os.listdir(dir_path)) if os.path.isdir(dir_path) else []:
            if not name.endswith(".gd"):
                continue
            files += 1
            path = os.path.join(dir_path, name)
            with open(path) as gd:
                lines = strip_comments(gd.read()).split("\n")
            for i, line in enumerate(lines):
                for token in forbidden:
                    if token in line:
                        violations += 1
                        print(f"{path}:{i + 1}:{token}", file=sys.stderr)
    print("layer\tfiles=%d\tviolations=%d" % (files, violations))


def pak_index(f):
    f.seek(4)
    n = struct.unpack("<I", f.read(4))[0]
    f.seek(PAK_HDR)
    idx = f.read(n * PAK_IDX)
    return [struct.unpack_from("<II", idx, i * PAK_IDX + 4) for i in range(n)]


def md5(b):
    return hashlib.md5(b).hexdigest()


# Granny node-directory constants, mirrored from Sacred.Models. Skeletons are
# found by tag through the same flat directory the geometry uses -- never by
# scanning for a byte pattern.
SEC_OFF = 1634          # entry-relative base of the node section
DIR_OFF = 16            # directory follows a u32 numNodes plus 12 bytes of header
NODE_STRIDE = 12        # {u32 tag, u32 rel, u32 numTotalChildren}
BONE_STRIDE = 68        # {i32 parent, 3f pos, 4f quat xyzw, 9f scale-shear}
T_SKELETON_SECTION = 0xCA5E0507
T_BONE_SECTION = 0xCA5E0508
T_MESH = 0xCA5E0601
T_MESH_VERTICES = 0xCA5E0801
T_MESH_NORMALS = 0xCA5E0802
T_MESH_TRIANGLES = 0xCA5E0901
T_MESH_WEIGHTS = 0xCA5E0702
T_FORM_MESH_BONE_SECTION = 0xCA5E0C09
T_FORM_MESH_BONE = 0xCA5E0C0A


def node_directory(buf):
    """[(tag, rel, numTotalChildren)] -- the flat node directory at SEC_OFF."""
    n = struct.unpack_from("<I", buf, SEC_OFF)[0]
    return [struct.unpack_from("<III", buf, SEC_OFF + DIR_OFF + j * NODE_STRIDE)
            for j in range(n)]


def node_child(d, j, tag):
    """First child of node j carrying `tag`, searching only j's declared run."""
    for k in range(j + 1, min(j + 1 + d[j][2], len(d))):
        if d[k][0] == tag:
            return k
    return -1


def mat_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def xform_mul(a, b):
    """Transform3D composition: (basis, origin) pairs, row-major basis."""
    return (mat_mul(a[0], b[0]),
            [sum(a[0][r][k] * b[1][k] for k in range(3)) + a[1][r] for r in range(3)])


def bone_facts(buf, names=None):
    """Everything the `bones` fact line needs, from one entry.

    md5 is over the RAW STORED bone bytes, so it needs no matrix decoder to be
    comparable with the Godot side. That hash is the real cross-implementation
    comparison here, and it is now the only one: the `rest_eq_bind` verdict this
    function also used to produce was removed from both harness sides for being
    circular -- it compared two compositions of the SAME stored local rests, so
    it was true by construction and could not fail.

    `names` (05-10): resolved bone names in Granny file order, from
    grn_bonenames's own "documented" chain -- "" where the chain does not
    resolve. Passed in rather than re-derived here, since bones() itself is
    already this function's SECOND independent implementation and a THIRD
    name-chain decode would only add a place for the two to silently drift.
    """
    empty = {"count": 0, "roots": 0, "binds": 0, "sanitised": 0, "md5": md5(b"")}
    d = node_directory(buf)
    bs = -1
    for j, (tag, _rel, children) in enumerate(d):
        if tag != T_SKELETON_SECTION:
            continue
        bs = node_child(d, j, T_BONE_SECTION)
        if bs != -1:
            break
    if bs == -1:
        return empty
    n = d[bs][2]
    boff = SEC_OFF + d[bs][1]
    if n <= 0 or boff + n * BONE_STRIDE > len(buf):
        return empty
    raw = buf[boff:boff + n * BONE_STRIDE]

    parents, rests = [], []
    for i in range(n):
        o = i * BONE_STRIDE
        parent = struct.unpack_from("<i", raw, o)[0]
        if parent < 0 or parent >= n:
            return empty
        pos = list(struct.unpack_from("<3f", raw, o + 4))
        qx, qy, qz, qw = struct.unpack_from("<4f", raw, o + 16)
        ss = struct.unpack_from("<9f", raw, o + 32)
        rot = [[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
               [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
               [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]]
        shear = [list(ss[0:3]), list(ss[3:6]), list(ss[6:9])]
        # Root bones are SELF-parented in this format, not -1 (measured; the
        # published parser assumes -1 and would read bone 0 as a self-loop).
        parents.append(-1 if parent == i else parent)
        rests.append((mat_mul(rot, shear), pos))

    def compose(order):
        world = [None] * n
        depth = [0] * n
        for b in order:
            p = parents[b]
            if p == -1:
                world[b], depth[b] = rests[b], 0
            else:
                if world[p] is None:
                    return None, None
                world[b], depth[b] = xform_mul(world[p], rests[b]), depth[p] + 1
        return world, depth

    # Side one: Granny file order, resolved parent-first by walking each chain.
    file_order = []
    seen = [False] * n
    for i in range(n):
        chain, c, steps = [], i, 0
        while not seen[c]:
            if steps > n or c in chain:
                return empty
            chain.append(c)
            if parents[c] == -1:
                break
            c = parents[c]
            steps += 1
        for b in reversed(chain):
            seen[b] = True
            file_order.append(b)
    # Kept as a CYCLE CHECK, not as one half of a comparison: compose() returns
    # None on a parent cycle, and an entry that cannot be composed is refused
    # rather than reported with a plausible bone count.
    world_a, _depth_a = compose(file_order)
    if world_a is None:
        return empty

    # Likewise kept as a SORTABILITY check: Skeleton3D requires every parent to
    # sit at a strictly lower index, so an entry whose bones cannot be
    # topologically ordered is refused here rather than at render time.
    topo, placed = [], [False] * n
    progress = True
    while progress and len(topo) < n:
        progress = False
        for b in range(n):
            if placed[b] or (parents[b] != -1 and not placed[parents[b]]):
                continue
            placed[b] = True
            topo.append(b)
            progress = True
    if len(topo) != n:
        return empty

    # Binds: one per distinct bone anything is weighted to, so a bone nothing
    # references gets no bind-array slot. Mesh-local bone indices resolve
    # through the FormMeshBone list whose length is that mesh's declared
    # highestBoneIndex + 1 -- the pairing is by length, never positional, and
    # an ambiguous match is refused rather than guessed.
    lists = []
    for j, (tag, _rel, children) in enumerate(d):
        if tag != T_FORM_MESH_BONE_SECTION:
            continue
        lists.append([struct.unpack_from("<i", buf, SEC_OFF + d[k][1])[0]
                      for k in range(j + 1, min(j + 1 + children, len(d)))
                      if d[k][0] == T_FORM_MESH_BONE])
    bound = []
    for j, (tag, _rel, _children) in enumerate(d):
        if tag != T_MESH:
            continue
        # Skipped exactly where Sacred.Models.mesh_arrays() skips it, so the
        # mesh sequences stay index-for-index parallel.
        if (node_child(d, j, T_MESH_VERTICES) == -1 or node_child(d, j, T_MESH_NORMALS) == -1
                or node_child(d, j, T_MESH_TRIANGLES) == -1):
            continue
        wj = node_child(d, j, T_MESH_WEIGHTS)
        if wj == -1:
            return empty
        want = struct.unpack_from("<i", buf, SEC_OFF + d[wj][1] + 4)[0] + 1
        hits = [li for li, l in enumerate(lists) if len(l) == want]
        if len(hits) != 1:
            return empty
        for g in lists[hits[0]]:
            if g not in bound:
                bound.append(g)
        lists.pop(hits[0])

    # Sanitised-name count -- mirrors view/model_view.gd's _build_rig() name
    # generation policy bone-for-bone, in the SAME visitation order (`topo`,
    # the topological/Skeleton3D order), since a duplicate's numeric suffix
    # depends on which bone was visited first. `stored` is the resolved name
    # (05-10) in Granny file order, "" where the chain did not resolve --
    # exactly what reaches ModelView through Sacred.Models.bones()[g]["name"].
    used = set()
    sanitised = 0
    for g in topo:
        stored = names[g] if names and g < len(names) else ""
        nm = stored.replace(":", "_").replace("/", "_")
        if nm == "":
            nm = "Bone_%d" % g
        while nm in used:
            nm = "%s_%d" % (nm, g)
        used.add(nm)
        if nm != stored:
            sanitised += 1

    return {
        "count": n,
        "roots": sum(1 for p in parents if p == -1),
        "binds": len(bound),
        "sanitised": sanitised,
        "md5": md5(raw),
    }


def region_list(stream, gx, gy):
    """Independent parse of a sector stream's region table -- reads the byte
    layout directly rather than translating godot-port/sacred.gd's
    Regions._init(). Mirrors its validity conditions exactly (declared grid
    byte size == width*height*CELL, grid fits inside the stream, anchor
    falls inside the owning sector) and its skip of the leading zero-sized
    origin marker, but derives none of them from that file's source text --
    only from the field offsets AGENTS.md/sacred.gd document.

    Returns a list of (anchor_x, anchor_y, w, h, grid_bytes) tuples in table
    order. A record whose type word is not REGION_TYPE ends the scan (not a
    skip) -- Regions._init() does the same: the region table is a contiguous
    run of typed records, not a sparse one.
    """
    regions = []
    if len(stream) <= REGION_TABLE_OFF + REGION_REC:
        return regions
    lo_x, lo_y = gx * SECT, gy * SECT
    p = REGION_TABLE_OFF
    while p + REGION_REC <= len(stream):
        if struct.unpack_from("<I", stream, p + 0x0C)[0] != REGION_TYPE:
            break
        cx, cy = struct.unpack_from("<II", stream, p)
        w, h = struct.unpack_from("<HH", stream, p + 0x08)
        off = struct.unpack_from("<I", stream, p + 0x10)[0]
        nbytes = struct.unpack_from("<I", stream, p + 0x14)[0]
        if (w > 0 and h > 0 and nbytes == w * h * CELL
                and off + nbytes <= len(stream)
                and lo_x <= cx < lo_x + SECT and lo_y <= cy < lo_y + SECT):
            regions.append((cx, cy, w, h, stream[off:off + nbytes]))
        p += REGION_REC
    return regions


def region_cell_class(grid, w, h, cx, cy):
    """Low nibble of the last byte of the cell's 32-byte record. A raw 0x00
    byte is EMPTY; a NON-ZERO byte whose nibble is 0 (0xd0, 0xe0) is OPEN
    (0x10), a building's open interior ground -- not the same thing.
    Out-of-range returns 0 (EMPTY), the same house accessor rule
    Sacred.Regions.cell_class() follows."""
    if cx < 0 or cy < 0 or cx >= w or cy >= h:
        return 0
    b = grid[(cy * w + cx) * CELL + 31]
    if b == 0:
        return 0
    return (b & 0x0F) or 0x10


def walkable_facts(stream, gx, gy):
    """(region_count, cell_count, open_cell_count, md5) for one sector's
    walkability fact line -- see godot-port/verify.gd's mirror for the
    hashed-text definition, which this function implements identically:
    per region, its anchor/size as decimal text, then one '1' (open, per
    WALKABLE_CLASSES) or '0' (blocked) per cell in row-major order,
    terminated by a newline; concatenated across regions in table order."""
    regions = region_list(stream, gx, gy)
    cells = 0
    open_cells = 0
    parts = []
    for cx0, cy0, w, h, grid in regions:
        parts.append("%d,%d,%d,%d" % (cx0, cy0, w, h))
        for y in range(h):
            for x in range(w):
                cells += 1
                if region_cell_class(grid, w, h, x, y) in WALKABLE_CLASSES:
                    open_cells += 1
                    parts.append("1")
                else:
                    parts.append("0")
        parts.append("\n")
    return len(regions), cells, open_cells, md5("".join(parts).encode("utf-8"))


def main():
    # One with-statement for every handle, matching grn_tagwalk.py's own
    # convention in this directory. Opening them together is safe: opening a
    # file produces no output, so the printed fact lines keep their order.
    with open(f"{GAME}/pak/tiles.pak", "rb") as tf, \
            open(f"{GAME}/pak/texture.pak", "rb") as xf, \
            open(f"{GAME}/pak/models.pak", "rb") as mf, \
            open(f"{GAME}/world/sectors.keyx", "rb") as kf, \
            open(f"{GAME}/world/sectors.wldx", "rb") as wf:
        tix, xix = pak_index(tf), pak_index(xf)
        # pak_index3() keeps the kind/flags word at +0 that pak_index() (above)
        # intentionally skips -- models.pak's entries need it, tiles.pak's and
        # texture.pak's readers do not, so pak_index() itself is untouched.
        mix3 = grn_tagwalk.pak_index3(mf)
        mix = [(off, field3) for _kind, off, field3 in mix3]
        for label, ix in (("tiles.pak", tix), ("texture.pak", xix), ("models.pak", mix)):
            print("pak\t%s\tcount=%d\tfirst=%d,%d\tlast=%d,%d" % (
                label, len(ix), ix[0][0], ix[0][1], ix[-1][0], ix[-1][1]))

        kf.seek(4)
        n, gw, gh = struct.unpack("<III", kf.read(12))
        kf.seek(KEY_HDR)
        keys = kf.read(n * KEY_REC)
        by_key = {}
        for i in range(n):
            b = i * KEY_REC
            by_key[struct.unpack_from("<I", keys, b + 32)[0]] = struct.unpack_from("<III", keys, b + 236)[:2] + (
                struct.unpack_from("<I", keys, b + 264)[0],)
        print("world\tcount=%d\tgrid=%dx%d" % (n, gw, gh))

        for gx, gy in SECTORS:
            e = by_key.get(gy * 100 + gx)
            if e is None:
                print("sector\t%d,%d\tlen=0\tmd5=%s" % (gx, gy, md5(b"")))
                continue
            off, csz, dsz = e
            wf.seek(off)
            d = zlib.decompress(wf.read(csz))
            # Not `assert`: python3 -O strips assert statements, which would
            # silently disable this harness's own integrity check.
            if len(d) != dsz:
                raise SystemExit(
                    "verify_ref: sector %d,%d decompressed to %d bytes, expected %d"
                    % (gx, gy, len(d), dsz))
            print("sector\t%d,%d\tlen=%d\tmd5=%s" % (gx, gy, len(d), md5(d)))

        # Walkability layer -- one fact line per sampled sector, between the
        # sector block and the tiles block on BOTH sides (04-01-PLAN.md
        # Task 3). Re-reads each sector's stream rather than reusing `d`
        # from the loop above -- that loop's `d` falls out of scope per
        # iteration by design, and re-fetching here keeps this block a
        # self-contained mirror of verify.gd's own second pass over SECTORS.
        for gx, gy in WALKABLE_SECTORS:
            e = by_key.get(gy * 100 + gx)
            if e is None:
                stream = b""
            else:
                off, csz, dsz = e
                wf.seek(off)
                stream = zlib.decompress(wf.read(csz))
                if len(stream) != dsz:
                    raise SystemExit(
                        "verify_ref: sector %d,%d decompressed to %d bytes, expected %d"
                        % (gx, gy, len(stream), dsz))
            n_regions, cells, open_cells, digest = walkable_facts(stream, gx, gy)
            print("walkable\t%d,%d\tregions=%d\tcells=%d\topen=%d\tmd5=%s" % (
                gx, gy, n_regions, cells, open_cells, digest))

        tf.seek(tix[0][0])
        rec = tf.read(len(tix) * 64)
        print("tiles\tcount=%d\ttex0=%d\ttexlast=%d" % (
            len(tix), struct.unpack_from("<I", rec, 0x20)[0],
            struct.unpack_from("<I", rec, (len(tix) - 1) * 64 + 0x20)[0]))

        for tid in TEXTURES:
            off, size = xix[tid]
            xf.seek(off)
            buf = xf.read(size + 80)
            w, h = struct.unpack_from("<HH", buf, 32)
            kind = buf[36]
            if kind != 4:
                print("texture\t%d\tERROR" % tid)
                continue
            raw = zlib.decompressobj().decompress(buf[80:])
            # Not `assert` -- see the sector check above.
            if len(raw) != w * h * 2:
                raise SystemExit(
                    "verify_ref: texture %d decompressed to %d bytes, expected %d"
                    % (tid, len(raw), w * h * 2))
            out = bytearray(w * h * 4)
            for i in range(w * h):
                p = raw[i * 2] | (raw[i * 2 + 1] << 8)
                out[i * 4 + 0] = ((p >> 8) & 0xF) * 17
                out[i * 4 + 1] = ((p >> 4) & 0xF) * 17
                out[i * 4 + 2] = (p & 0xF) * 17
                out[i * 4 + 3] = ((p >> 12) & 0xF) * 17
            print("texture\t%d\t%dx%d\tmd5=%s" % (tid, w, h, md5(bytes(out))))

        # Tag-walk layer only -- kind, derived length, tag count, triples md5.
        # Never a hash of decoded mesh data: no independent Python mesh decoder
        # exists to make such a hash meaningful (03-04-PLAN.md, Pitfall 8).
        # Reuses grn_tagwalk.py's per-entry walk rather than a third
        # implementation; grn_tagwalk.py itself is untouched by this file.
        models_file_size = os.fstat(mf.fileno()).st_size
        for idx in MODELS:
            kind, off, _field3 = mix3[idx]
            true_len = grn_tagwalk.derive_length(mix3, idx, models_file_size)
            name = grn_tagwalk.read_name(mf, off)
            walkable, magic_off, _reason = grn_tagwalk.classify(mf, kind, off, true_len)
            if not walkable:
                print("models\t%d\tname=%s\tkind=%d\tlen=%d\ttags=0\tmd5=%s" % (
                    idx, name, kind, true_len, grn_tagwalk.md5(b"")))
                continue
            triples, _stop_reason = grn_tagwalk.walk_entry(mf, off, magic_off, true_len)
            # sacred.gd's Sacred.Models.walk() -- the trusted GDScript walker --
            # never appends the terminator tag itself as a triple; it breaks out
            # of the inner loop on sight of 0xCA5EFFFF, before appending.
            # grn_tagwalk.py's own walk_entry() does append it (03-03-SUMMARY.md
            # key-decision #3, TSV row 397) -- a real, already-documented
            # difference between the two walkers' own diagnostic output that
            # this fact line does not paper over by editing either walker.
            # Instead this line's own tags=/md5= fields are defined, once, to
            # exclude the terminator, matching the trusted GDScript convention;
            # grn_tagwalk.py's --entry=/--corpus output is untouched by this
            # filter and keeps counting the terminator as its own tag.
            core = [t for t in triples if t[2] != grn_tagwalk.TERMINATOR_TAG]
            print("models\t%d\tname=%s\tkind=%d\tlen=%d\ttags=%d\tmd5=%s" % (
                idx, name, kind, true_len, len(core), grn_tagwalk.triples_md5(core)))

        # Bone names, computed once and shared by the `bones` and `bonename`
        # blocks below -- `bones`' own `sanitised` field now depends on the
        # resolved names (05-10), not just on a fixed always-empty premise, so
        # both fact lines need the same per-entry name list.
        #
        # Reuses grn_bonenames.py's own EntryCensus + arm_resolve("documented",
        # ...) -- the SAME two-hop chain implementation --entry/--harness/
        # --report already exercise -- rather than a third decode of the same
        # chain written here from scratch. quiet=True suppresses that module's
        # own `entry\t...`/`refuse\t...` print statements, which would
        # otherwise land in this harness's diffed stdout.
        gb_entries, gb_size = grn_bonenames.pak_index(grn_bonenames.MODELS_PATH)
        bone_names_by_idx = {}
        for idx in MODELS:
            census = grn_bonenames.EntryCensus(
                grn_bonenames.MODELS_PATH, gb_entries, gb_size, idx, quiet=True)
            names = []
            if census.ok:
                for i in range(census.bone_count()):
                    n, _detail = grn_bonenames.arm_resolve("documented", census, i)
                    names.append(n or "")
            bone_names_by_idx[idx] = names

        # Skeleton layer -- the Python side of godot-port/verify.gd's `bones` fact
        # line, printed between the models block and the layer check on both sides.
        #
        # The `rest_eq_bind` line that stood beside it was removed from BOTH sides
        # together: the assertion was circular (it compared two compositions of the
        # same stored local rests, so it was true by construction and could not
        # fail). Dropping it here alone would have broken parity.
        #
        # This is a genuine second implementation, not a translation: the node
        # directory walk, the 68-byte bone decode, the quaternion-to-matrix step and
        # the chain composition below are all written here, in float64, against the
        # bytes. sacred.gd does the same job in GDScript against Godot's float32
        # Transform3D. See the maxmag note in bone_facts() for the one place that
        # difference is visible.
        for idx in MODELS:
            kind, off, _field3 = mix3[idx]
            true_len = grn_tagwalk.derive_length(mix3, idx, models_file_size)
            name = grn_tagwalk.read_name(mf, off)
            mf.seek(off)
            f = bone_facts(mf.read(true_len), bone_names_by_idx.get(idx, []))
            print("bones\t%d\tcount=%d\troots=%d\tbinds=%d\tsanitised=%d\tmd5=%s" % (
                idx, f["count"], f["roots"], f["binds"], f["sanitised"], f["md5"]))

        # Bone-name layer -- the Python side of godot-port/verify.gd's
        # `bonename` fact line, printed directly after the bones block on
        # BOTH sides (05-10-PLAN.md, discharging 05-04's halt).
        for idx in MODELS:
            names = bone_names_by_idx.get(idx, [])
            named = sum(1 for n in names if n != "")
            uniq = set(names)
            text = "".join(n + "\n" for n in names)
            print("bonename\t%d\tnamed=%d\tempty=%d\tunique=%d\tmd5=%s" % (
                idx, named, len(names) - named, len(uniq), md5(text.encode("utf-8"))))

        # Animation-clip layer -- the Python side of godot-port/verify.gd's
        # `motion` fact line, printed between the bones block and the layer
        # check on both sides (Plan 05-05 Task 2).
        #
        # Reaches the clip through grn_tagwalk.clip_decode(), the SAME
        # function --clip=N calls -- not a second implementation written
        # here. Unlike bone_facts() above (a genuine, deliberately
        # independent second implementation of the skeleton decode), the
        # clip directory walk has exactly one Python implementation; this
        # loop is a caller of it, not a rewrite of it, per the plan's "no
        # third implementation of the entry-length rule in analysis/tools/".
        #
        # The md5 is over the RAW STORED per-bone record bytes -- the
        # concatenated spans, exactly as they sit in the file -- not over
        # decoded floats, the same choice bone_facts()'s md5 already makes
        # and for the same reason: both harness sides then compute it from
        # offsets, and neither needs the other's float decoder to be
        # identical for the hash to mean anything. `keys` IS a decoded
        # number (total keyframe count across all records), so this line
        # carries one byte-level field and one interpretation-level field.
        for idx in MOTIONS:
            name = grn_tagwalk.read_name(mf, mix3[idx][1])
            result = grn_tagwalk.clip_decode(mf, mix3, idx, models_file_size)
            if result is None:
                print("motion\t%d\tname=%s\tbones=0\trecords=0\tlength=0.000000\tkeys=0\tmd5=%s" % (
                    idx, name, grn_tagwalk.md5(b"")))
                continue
            print("motion\t%d\tname=%s\tbones=%d\trecords=%d\tlength=%.6f\tkeys=%d\tmd5=%s" % (
                idx, name, result["bones"], result["records"], result["length"],
                result["keys"], result["md5"]))

        layer_check()


if __name__ == "__main__":
    main()
