#!/usr/bin/env python3
"""Independent tag walker for Granny 1.x `.GRN` entries inside `models.pak`.

Personal-use interoperability work on legally-owned media. Output stays local.

This is the second, deliberately independent implementation of the tag walk
(the first lives in `godot-port/`, owned by a sibling task). It is written
from a written specification and from this module's own direct byte reads of
`install/pak/models.pak` -- never by opening or translating the GDScript
walker, and never by reading any Granny SDK or third-party GPL source. The
independence rationale is the project's two-decoder rule
(`research/method/discipline.md`): a Python file transliterated from the
GDScript one would make the later parity diff structurally incapable of
failing.

Two on-disk facts below were re-measured directly against `models.pak` this
session, using nothing but `struct.unpack_from` and a literal byte search for
each next known tag value (never the general pattern-scan the tag walker
itself is forbidden from using): the `0xCA5E0103` "object" chunk is 20 bytes
tag-inclusive on every one of four independently sampled entries (two kinds,
three mesh files plus one motion file), not the 16 stated in the plan's
written-specification text, and the `0xCA5E0101` "final" chunk is 36 bytes
tag-inclusive, not 32. Using the stated 16/32 desyncs the walk after the
second header tag on real data (verified: it stops at an unrecognised tag
four bytes early) rather than reaching `0xCA5EFFFF`, so the measured values
are what this module uses. `research/formats/granny-grn.md` writes this up.

    ./grn_tagwalk.py --entry=589        # one entry's tag, offset, length triples
    ./grn_tagwalk.py --corpus           # sweep all 4993 entries, report the invariant
    ./grn_tagwalk.py --falsify=1        # same sweep with every advance off by 1 byte
"""
import hashlib
import os
import struct
import sys

# Beside the existing PAK_HDR/PAK_IDX idiom this project's other analysis
# tools already use (see verify_ref.py, pak.py).
PAK_HDR, PAK_IDX = 256, 12
NAME_LEN = 64

# abspath() collapses the `..` lexically: the workspace reaches these tools
# through the analysis/tools symlink, and the kernel would resolve `..` past it.
GAME = os.environ.get("SACRED_INSTALL") or os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../../../install"))

ROOT_TAG = 0xCA5E0000
TERMINATOR_TAG = 0xCA5EFFFF

KIND_MESH, KIND_MOTION = 64, 65
# Root tag lives at a different constant offset per kind -- measured this
# session (matches 03-RESEARCH.md's "Container and Index Layer" census).
MAGIC_OFFSET = {KIND_MESH: 0x4EA, KIND_MOTION: 0x140}

# Total on-disk size, tag included, for each fixed-shape header chunk.
# Measured directly (not copied from the written spec's 16/32 -- see the
# module docstring) against BAT.GRN, GLADIATOR.GRN, GLAD_SA5_SHOULDER.GRN
# (kind 64) and BATX_ATTACK_BH_A.GRN (kind 65): identical shape, identical
# sizes, regardless of kind -- only the starting magic offset differs.
HEADER_CHUNK_SIZE = {
    0xCA5E0000: 32,  # root
    0xCA5E0102: 20,  # copyright
    0xCA5E0103: 20,  # object    -- measured 20, written spec said 16
    0xCA5E0101: 36,  # final     -- measured 36, written spec said 32
}

# Fixed 12-byte leaf chunks: 4-byte tag plus 8-byte payload, chained by a
# constant +12 advance. Confirmed on both sampled entries.
LEAF_SINGLE_TAG = 0xCA5E0200
LEAF_RANGES = ((0xCA5E1000, 0xCA5E1003), (0xCA5E0F00, 0xCA5E0F06))

DOCUMENTED_TAGS = sorted((0xCA5E0000, 0xCA5E0101, 0xCA5E0102, 0xCA5E0103))

# Per-entry safety net against a pathological loop on malformed bytes; real
# header chains observed this session run ~10 triples deep.
MAX_TRIPLES_PER_ENTRY = 4096
# Per-entry bounded read -- the file is 434 MB; nothing here may slurp it.
# Real chains fit in well under 200 bytes; this leaves generous headroom
# without ever reading a meaningful fraction of the file per entry.
HEADER_READ_CAP = 4096

# Flat node-directory constants, added with the animation-clip work. The
# is a SEPARATE structure from the header chain walk_entry() reads above --
# reached at section_offset = magic_off + SECTION_OFF_DELTA, a count (u32)
# followed by an array of {tag, rel, children} triples. Independently
# written for this file, from analysis/tools/formats/grn_motion.py's own measured
# byte layout (05-02, VERIFIED corpus-wide) and godot-port/formats/models.gd's own
# independently-written twin (05-05 Task 1) -- never by opening or
# translating either one; see the module docstring's independence rationale
# and D-21/D-23's licence boundary (neither Iris1 nor the AoM Model Plugin
# document this directory shape).
SECTION_OFF_DELTA = 376
DIR_OFF = 16
NODE_STRIDE = 12
MAX_NODES = 1 << 20

TAG_BONE = 0xCA5E0506
TAG_ANIMATION_SECTION = 0xCA5E1205
TAG_ANIMATION = 0xCA5E1200
TAG_ANIM_TRANSFORM_TRACK_SECTION = 0xCA5E1203
TAG_ANIM_TRANSFORM_TRACK_KEYS = 0xCA5E1204

# Per-bone AnimationTransformTrackKeys record layout (05-02, VERIFIED
# zero-slack across all sampled records): a 52-byte header carrying the
# three declared counts, three flat time-tracks, three flat payload arrays,
# then an undocumented but real, count-independent 48-byte trailer (never
# itself decoded -- see grn_motion.py's constant_trailer()).
ANIM_RECORD_HEADER = 52
ANIM_OFF_NUM_TRANSLATES = 24
ANIM_OFF_NUM_QUATERNIONS = 28
ANIM_OFF_NUM_UNKNOWNS = 32
ANIM_RECORD_TRAILER = 48
MAX_KEYFRAMES = 1 << 20


def is_leaf_tag(tag):
    if tag == LEAF_SINGLE_TAG:
        return True
    return any(lo <= tag <= hi for lo, hi in LEAF_RANGES)


def pak_index3(f):
    """Like verify_ref.py's pak_index, but keeps all three u32 fields of
    each 12-byte record -- including the kind/flags word at +0 that
    verify_ref.py's own reader intentionally skips."""
    f.seek(4)
    n = struct.unpack("<I", f.read(4))[0]
    f.seek(PAK_HDR)
    idx = f.read(n * PAK_IDX)
    return [struct.unpack_from("<III", idx, i * PAK_IDX) for i in range(n)]


def derive_length(entries, i, file_size):
    """The only trustworthy on-disk length for either kind: never index
    field 3, which runs ~1.95x the true gap for kind=64 and silently
    over-reads into the next entry if trusted."""
    if i + 1 < len(entries):
        return entries[i + 1][1] - entries[i][1]
    return file_size - entries[i][1]


def read_name(f, offset):
    f.seek(offset)
    raw = f.read(NAME_LEN)
    # NUL-padded ASCII name: split on the first NUL rather than searching
    # for a tag-shaped pattern (this is a fixed 64-byte field, not a scan).
    return raw.split(b"\x00", 1)[0].decode("latin1", "replace")


def md5(b):
    return hashlib.md5(b).hexdigest()


def triples_md5(triples):
    """Per the shared specification: MD5 of the UTF-8 text formed by joining,
    in emission order, one record per triple as decimal-tag,decimal-offset,
    decimal-length\\n -- no trailing separator beyond the final newline, no
    spaces."""
    text = "".join(f"{tag},{offset},{length}\n" for _, offset, tag, length in triples)
    return md5(text.encode("utf-8"))


def classify(f, kind, offset, true_len):
    """The sole exclusion rule: walkable iff the derived length reaches the
    kind's magic offset plus four and the u32 there equals 0xCA5E0000. No
    index literal, no size threshold -- so a patched/modded install's own
    malformed entries would be caught the same way."""
    magic_off = MAGIC_OFFSET.get(kind)
    if magic_off is None:
        return False, None, "unrecognized kind"
    if true_len < magic_off + 4:
        return False, magic_off, "too short to reach the magic offset"
    f.seek(offset + magic_off)
    word = f.read(4)
    if len(word) < 4 or struct.unpack("<I", word)[0] != ROOT_TAG:
        return False, magic_off, "the bytes there are not the magic value"
    return True, magic_off, None


def walk_entry(f, entry_offset, magic_off, budget, desync=0):
    """Walk (tag, entry-relative offset, length) triples from magic_off,
    never past budget (the entry's own derived length). Never searches for a
    tag-shaped byte pattern -- every advance is by a declared size read from
    the fixed-shape table above, exactly as the shared specification
    requires (dense float geometry in the untagged bulk region collides with
    the tag pattern at corpus scale, so scanning for it is unsafe).

    desync is added to every advance; used only by --falsify to show the
    walk is not vacuously correct -- a byte-level desync must break tag
    matching almost immediately, not silently keep synchronising."""
    read_len = min(budget, magic_off + HEADER_READ_CAP)
    f.seek(entry_offset)
    buf = f.read(read_len)
    pos = magic_off
    triples = []
    while True:
        if len(triples) >= MAX_TRIPLES_PER_ENTRY:
            return triples, "triple-budget"
        if pos + 4 > budget or pos + 4 > len(buf):
            return triples, "exceeds-length"
        tag = struct.unpack_from("<I", buf, pos)[0]
        if tag == TERMINATOR_TAG:
            triples.append((len(triples) + 1, pos, tag, 4))
            return triples, "terminator"
        if tag in HEADER_CHUNK_SIZE:
            length = HEADER_CHUNK_SIZE[tag]
        elif is_leaf_tag(tag):
            length = 12
        else:
            return triples, "unknown-tag"
        if pos + length > budget or pos + length > len(buf):
            return triples, "exceeds-length"
        triples.append((len(triples) + 1, pos, tag, length))
        pos += length + desync


def clip_directory(buf, sec):
    """Flat node directory at absolute buffer offset `sec`: a count (u32)
    then an array of {tag, rel, children} triples, each 12 bytes, starting
    DIR_OFF bytes into the section. Returns [] on any structural failure --
    refuse rather than partially decode, the same posture walk_entry() and
    classify() already take."""
    if sec < 0 or len(buf) < sec + DIR_OFF + NODE_STRIDE:
        return []
    n = struct.unpack_from("<I", buf, sec)[0]
    if n <= 0 or n > MAX_NODES:
        return []
    dir_off = sec + DIR_OFF
    if dir_off + n * NODE_STRIDE > len(buf):
        return []
    nodes = []
    for j in range(n):
        o = dir_off + j * NODE_STRIDE
        tag, rel, children = struct.unpack_from("<III", buf, o)
        if (tag & 0xFFFF0000) != ROOT_TAG:
            return []
        nodes.append({"tag": tag, "rel": rel, "children": children})
    return nodes


def clip_span(nodes, j, buf_size, sec):
    """Payload byte length of node j: the gap to the next node with a
    strictly larger rel, or to the end of the section for the last one."""
    r = nodes[j]["rel"]
    for k in range(j + 1, len(nodes)):
        nr = nodes[k]["rel"]
        if nr > r:
            return nr - r
    return buf_size - sec - r


def direct_children(nodes, j):
    """Indices of node j's DIRECT children only -- one level, skipping each
    child's own subtree via its declared descendant count."""
    out = []
    last = min(j + 1 + nodes[j]["children"], len(nodes))
    k = j + 1
    while k < last:
        out.append(k)
        k += 1 + nodes[k]["children"]
    return out


def child_with_tag(nodes, j, tag):
    """First node in j's declared subtree run carrying `tag`."""
    last = min(j + 1 + nodes[j]["children"], len(nodes))
    for k in range(j + 1, last):
        if nodes[k]["tag"] == tag:
            return k
    return -1


def clip_decode(f, entries, index, file_size, desync=0):
    """Decode entry `index`'s kind=65 AnimationTransformTrackKeys records via
    the flat node directory at section_offset = magic_off + SECTION_OFF_DELTA.
    Reuses derive_length/classify -- the entry-length and magic-offset rules
    already established above -- rather than re-deriving either.

    desync displaces each record's computed base offset by N bytes before
    the count fields are read, mirroring godot-port/main.gd's
    --clip-falsify=N ("displaces the clip record's base offset by N"): used
    only by --falsify to prove the zero-slack reconciliation actually
    depends on real byte alignment, not vacuously passing.

    Returns None on any structural failure (mirrors models.gd's
    push_error-and-return-empty posture)."""
    kind, offset, _field3 = entries[index]
    true_len = derive_length(entries, index, file_size)
    ok, magic_off, _reason = classify(f, kind, offset, true_len)
    if not ok:
        return None
    sec = magic_off + SECTION_OFF_DELTA
    f.seek(offset)
    buf = f.read(true_len)
    if len(buf) < true_len:
        return None
    nodes = clip_directory(buf, sec)
    if not nodes:
        return None

    bone_count = sum(1 for nd in nodes if nd["tag"] == TAG_BONE)
    sec_j = next((j for j, nd in enumerate(nodes) if nd["tag"] == TAG_ANIMATION_SECTION), -1)
    if sec_j == -1:
        return None
    anim_j = child_with_tag(nodes, sec_j, TAG_ANIMATION)
    if anim_j == -1:
        return None
    tts_j = child_with_tag(nodes, anim_j, TAG_ANIM_TRANSFORM_TRACK_SECTION)
    if tts_j == -1:
        return None
    key_nodes = [k for k in direct_children(nodes, tts_j)
                 if nodes[k]["tag"] == TAG_ANIM_TRANSFORM_TRACK_KEYS]
    if not key_nodes:
        return None

    records = []
    max_length = 0.0
    raw = bytearray()
    for j in key_nodes:
        span = clip_span(nodes, j, len(buf), sec)
        off = sec + nodes[j]["rel"] + desync
        if off < 0 or span <= ANIM_RECORD_HEADER or off + span > len(buf):
            return None
        if off + ANIM_OFF_NUM_UNKNOWNS + 4 > len(buf):
            return None
        nt = struct.unpack_from("<I", buf, off + ANIM_OFF_NUM_TRANSLATES)[0]
        nq = struct.unpack_from("<I", buf, off + ANIM_OFF_NUM_QUATERNIONS)[0]
        nu = struct.unpack_from("<I", buf, off + ANIM_OFF_NUM_UNKNOWNS)[0]
        if nt > MAX_KEYFRAMES or nq > MAX_KEYFRAMES or nu > MAX_KEYFRAMES:
            return None
        implied = ANIM_RECORD_HEADER + 16 * nt + 20 * nq + 16 * nu + ANIM_RECORD_TRAILER
        if implied != span:
            return None
        p = off + ANIM_RECORD_HEADER
        if nt:
            last_t = struct.unpack_from("<f", buf, p + (nt - 1) * 4)[0]
            max_length = max(max_length, last_t)
        raw += buf[off:off + span]
        records.append((nt, nq, nu))

    keys = sum(nt + nq + nu for nt, nq, nu in records)
    return {
        "bones": bone_count,
        "records": len(records),
        "length": max_length,
        "keys": keys,
        "md5": md5(bytes(raw)),
    }


def cmd_clip(models_path, index, desync=0):
    with open(models_path, "rb") as f:
        entries = pak_index3(f)
        file_size = os.fstat(f.fileno()).st_size
        if not 0 <= index < len(entries):
            print(f"clip\t{index}\tERROR out of range (0..{len(entries) - 1})")
            raise SystemExit(1)
        name = read_name(f, entries[index][1])
        suffix = f"\tfalsify={desync}" if desync else ""
        result = clip_decode(f, entries, index, file_size, desync=desync)
        if result is None:
            print("clip\t%d\tname=%s\tbones=0\trecords=0\tlength=0.000000\tkeys=0\tmd5=%s\treason=refused%s" % (
                index, name, md5(b""), suffix))
            raise SystemExit(1)
        print("clip\t%d\tname=%s\tbones=%d\trecords=%d\tlength=%.6f\tkeys=%d\tmd5=%s%s" % (
            index, name, result["bones"], result["records"], result["length"],
            result["keys"], result["md5"], suffix))


def cmd_entry(models_path, index):
    with open(models_path, "rb") as f:
        entries = pak_index3(f)
        file_size = os.fstat(f.fileno()).st_size
        if not 0 <= index < len(entries):
            print(f"grn\t{index}\tERROR out of range (0..{len(entries) - 1})")
            return
        kind, offset, field3 = entries[index]
        true_len = derive_length(entries, index, file_size)
        name = read_name(f, offset)
        walkable, magic_off, reason = classify(f, kind, offset, true_len)
        printed_magic_off = magic_off if magic_off is not None else -1
        print("grn\t%d\tname=%s\tkind=%d\ttrue_len=%d\tmagic_off=%d\tmagic_ok=%s" % (
            index, name, kind, true_len, printed_magic_off,
            "true" if walkable else "false"))
        if not walkable:
            print(f"grnend\t{index}\ttags=0\tconsumed=0\tmd5={triples_md5([])}\tstop={reason}")
            return
        triples, stop_reason = walk_entry(f, offset, magic_off, true_len)
        for ordinal, rel_offset, tag, length in triples:
            print("tag\t%d\t%d\t%d\t0x%08x\t%d" % (index, ordinal, rel_offset, tag, length))
        consumed = triples[-1][1] + triples[-1][3] if triples else 0
        print(f"grnend\t{index}\ttags={len(triples)}\tconsumed={consumed}"
              f"\tmd5={triples_md5(triples)}\tstop={stop_reason}")


def cmd_corpus(models_path, desync=0):
    with open(models_path, "rb") as f:
        entries = pak_index3(f)
        file_size = os.fstat(f.fileno()).st_size
        n = len(entries)

        walkable = skipped = mesh_clean = motion_clean = 0
        names_digest = hashlib.md5()
        skip_lines = []
        tag_entry_count = {}
        tag_total_count = {}

        for i in range(n):
            kind, offset, field3 = entries[i]
            true_len = derive_length(entries, i, file_size)
            name = read_name(f, offset)
            names_digest.update(("%d:%s\n" % (i, name)).encode("utf-8"))
            ok, magic_off, reason = classify(f, kind, offset, true_len)
            if not ok:
                skipped += 1
                skip_lines.append((i, name, kind, reason))
                continue
            walkable += 1
            triples, stop_reason = walk_entry(f, offset, magic_off, true_len, desync=desync)
            if stop_reason == "terminator":
                if kind == KIND_MESH:
                    mesh_clean += 1
                elif kind == KIND_MOTION:
                    motion_clean += 1
            seen = set()
            for _, _, tag, _ in triples:
                tag_total_count[tag] = tag_total_count.get(tag, 0) + 1
                seen.add(tag)
            for tag in seen:
                tag_entry_count[tag] = tag_entry_count.get(tag, 0) + 1

        names_md5 = names_digest.hexdigest()
        suffix = f"\tfalsify={desync}" if desync else ""
        # Names were printed by both walkers and compared by neither, so a
        # truncated or misread name field passed the parity gate (measured
        # 2026-08-15: NAME_LEN 64 -> 4 mangles every name and the gate still
        # said PASS). One digest over index:name puts them in the compared
        # surface without adding 4993 lines to the output.
        print("corpus\tentries=%d\twalkable=%d\tskipped=%d\tmesh=%d\tmotion=%d\tnames=%s%s" % (
            n, walkable, skipped, mesh_clean, motion_clean, names_md5, suffix))
        for i, name, kind, reason in skip_lines:
            print(f"skip\t{i}\tname={name}\tkind={kind}\treason={reason}")

        rest = sorted(t for t in tag_entry_count if t not in DOCUMENTED_TAGS)
        ordered = [t for t in DOCUMENTED_TAGS if t in tag_entry_count] + rest
        for tag in ordered:
            definitional = "true" if tag == ROOT_TAG else "false"
            print("tagcount\t0x%08x\tdefinitional=%s\tfiles=%d\ttotal=%d" % (
                tag, definitional, tag_entry_count[tag], tag_total_count[tag]))


def main():
    models_path = os.path.join(GAME, "pak", "models.pak")
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    entry_index = None
    clip_index = None
    corpus = False
    falsify = 0
    for arg in args:
        if arg.startswith("--entry="):
            entry_index = int(arg.split("=", 1)[1])
        elif arg == "--corpus":
            corpus = True
        elif arg.startswith("--clip="):
            clip_index = int(arg.split("=", 1)[1])
        elif arg.startswith("--falsify="):
            falsify = int(arg.split("=", 1)[1])
        else:
            raise SystemExit(f"unknown argument: {arg}")
    # --clip=N (optionally with --falsify=N) takes precedence: it is the one
    # combination this file's callers actually invoke together (see the
    # module docstring). --entry=/
    # --corpus/bare --falsify= keep their pre-existing single-argument
    # behaviour unchanged.
    if clip_index is not None:
        cmd_clip(models_path, clip_index, desync=falsify)
    elif entry_index is not None:
        cmd_entry(models_path, entry_index)
    elif corpus or falsify:
        cmd_corpus(models_path, desync=falsify)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
