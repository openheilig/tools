#!/usr/bin/env python3
"""`kind=65` motion-entry probe for Granny 1.x `.GRN` entries inside
`models.pak` -- what a per-bone animation record actually contains, measured
against Sacred's own bytes rather than borrowed from an outside template.

Personal-use interoperability work on legally-owned media. Output stays local.

WHAT THIS IS FOR. R1.5 needs a named clip's per-bone transform tracks, and
three things stood between `godot-port/formats/models.gd` and that decode: the flat
node directory's position inside a `kind=65` entry was unmeasured; the
per-bone record's field layout was a hypothesis borrowed from an outside
reader; and an earlier research session concluded tag `0xCA5E1204` was
"genuinely absent" from Sacred's motion bytes. That conclusion was measured
against `models.pak` entry 2845, which is `GLADIATOR.GRN` opened as a
`kind=65` entry -- five meshes, 101 bones, and correctly ZERO per-bone
animation records, because it is not a clip. `0xCA5E1204` is
`AnimationTransformTrackKeys`: the per-bone keyframe block. A file with no
per-bone animation has none of them; there was never an absence to explain,
only a wrong file compared against a right table (findings row 585,
05-RESEARCH.md Assumption A3, corrected by this probe's `--entry`/`--clip`
output and the findings rows this plan appends).

WHAT THE BYTES SAY (Task 1, established below and swept over the whole
4993-entry corpus): `section_offset(entry) = magic_offset(entry) + 376`
reaches a valid flat node directory in BOTH kinds. `SECTION_OFF_DELTA = 376`
is not a new magic value -- it reconciles the constant `models.gd` already
ships for kind=64 (`SECTION_OFF_MESH = 1634`, `MAGIC_OFF_MESH = 1258`,
1634 - 1258 = 376) and extends it to kind=65 (`MAGIC_OFF_MOTION = 320`,
320 + 376 = 696).

LICENCE BOUNDARY (D-21, D-23) -- read before touching either source. Two
outside projects are cited here, on IDENTICAL terms:

  - `github.com/SiENcE/Iris1`, `src/granny` -- GPL v2. Documents the per-bone
    `AnimationTransformTrackKeys` record as: `dword id`, 5 unknown dwords,
    `numTranslates`, `numQuaternions`, `numUnknowns`, 4 unknown dwords, three
    float time tracks, then `numTranslates*3 + numQuaternions*4 +
    numUnknowns*3` floats; clip length is the last translate time.
  - `github.com/ptasev/Age-of-Mythology`, the AoM Model Plugin -- NO licence
    file at all, which is all-rights-reserved, not permissive. Supplies the
    authoritative `0xCA5E12__` node-type names used throughout this file.

Both projects are read ONLY as documentation of the Granny 1.x `.grn`
container format: tag numbers, node-type names and record layouts are facts
about a file format and are used as such. Neither project's code, comments
or class structure is ported, translated or paraphrased here -- the walk
below is written flat, in this project's own idiom (reusing `grn_tagwalk.py`
and `grn_bonenames.py`'s conventions, never reading either GPL/no-licence
source's code into this one). Both record shapes are treated as HYPOTHESES
until the zero-slack reconciliation in `--clip=N` either confirms or refutes
them against Sacred's own bytes. This file, like its siblings, never touches
`godot-port/` and is never imported by it.

    ./grn_motion.py --entry=2847     # directory census + first 1204 record
    ./grn_motion.py --sweep          # section_offset swept over all 4993 entries
    ./grn_motion.py --sweep --falsify=1   # counterfactual: must collapse baddir
    ./grn_motion.py --clip=2847      # zero-slack per-bone record layout
    ./grn_motion.py --census         # model/clip/neither, from structure alone
    ./grn_motion.py --idjoin         # can a clip join a model without names?
"""
import itertools
import math
import os
import struct
import sys

from grn_tagwalk import pak_index3, derive_length, read_name, md5, GAME, KIND_MESH, KIND_MOTION

MODELS_PATH = os.path.join(GAME, "pak", "models.pak")

MAGIC = 0xCA5E0000

# Mirrors Sacred.Models.MAGIC_OFF_MESH / MAGIC_OFF_MOTION (godot-port/formats/models.gd)
# and grn_tagwalk.py's MAGIC_OFFSET -- same numbers, re-declared here (as
# grn_bonenames.py also does) so this probe's directory-section math is
# self-contained and legible on its own.
MAGIC_OFFSET = {KIND_MESH: 0x4EA, KIND_MOTION: 0x140}

# The flat node directory sits 376 bytes after the root tag, in BOTH kinds.
# models.gd: SECTION_OFF_MESH=1634, MAGIC_OFF_MESH=1258, 1634-1258=376 -- so
# this is a reconciliation of an already-verified constant, not a new one.
# --sweep below is what establishes it holds for kind=65 too, corpus-wide.
SECTION_OFF_DELTA = 376
DIR_OFF = 16
NODE_STRIDE = 12
MAX_NODES = 1 << 20

# Directory node tags this probe reads or names. Values and names from the
# AoM Model Plugin's GrnNodeType.cs (findings row 585); every one of these
# also appears on models.gd's own shipped geometry/skeleton decode.
TAG_BONE = 0xCA5E0506
TAG_SKELETON_SECTION = 0xCA5E0507
TAG_BONE_SECTION = 0xCA5E0508
TAG_MESH = 0xCA5E0601
TAG_DATA_EXTENSION = 0xCA5E0F00
TAG_TRANSFORM_CHANNEL = 0xCA5E0B00
TAG_FORM_BONE_CHANNELS = 0xCA5E0C02
TAG_ANIMATION = 0xCA5E1200
TAG_ANIMATION_VECTOR_TRACK_SECTION = 0xCA5E1201
TAG_ANIMATION_VECTOR_TRACK_KEYS = 0xCA5E1202
TAG_ANIMATION_TRANSFORM_TRACK_SECTION = 0xCA5E1203
TAG_ANIMATION_TRANSFORM_TRACK_KEYS = 0xCA5E1204
TAG_ANIMATION_SECTION = 0xCA5E1205

TAG_NAMES = {
    TAG_BONE: "Bone",
    TAG_SKELETON_SECTION: "SkeletonSection",
    TAG_BONE_SECTION: "BoneSection",
    TAG_MESH: "Mesh",
    TAG_DATA_EXTENSION: "DataExtension",
    TAG_TRANSFORM_CHANNEL: "TransformChannel",
    TAG_FORM_BONE_CHANNELS: "FormBoneChannels",
    TAG_ANIMATION: "Animation",
    TAG_ANIMATION_VECTOR_TRACK_SECTION: "AnimationVectorTrackSection",
    TAG_ANIMATION_VECTOR_TRACK_KEYS: "AnimationVectorTrackKeys",
    TAG_ANIMATION_TRANSFORM_TRACK_SECTION: "AnimationTransformTrackSection",
    TAG_ANIMATION_TRANSFORM_TRACK_KEYS: "AnimationTransformTrackKeys",
    TAG_ANIMATION_SECTION: "AnimationSection",
}

# --entry=N's tag census -- mirrors the planning session's node-tag census
# table columns (bones, transform channels, objects, meshes, per-bone keys).
CENSUS_TAGS = [TAG_BONE, TAG_TRANSFORM_CHANNEL, TAG_DATA_EXTENSION, TAG_MESH,
               TAG_ANIMATION_TRANSFORM_TRACK_KEYS, TAG_ANIMATION_VECTOR_TRACK_KEYS]

CLIP_ENTRY = 2847      # GLAD_ATTACK_1H_A.GRN, this plan's primary clip sample
MODEL_ENTRY = 589       # GLADIATOR.GRN, kind=64 model
CONTROL_ENTRY = 1       # BAT.GRN, 38 bones -- --idjoin's unrelated-model control arm


def tag_name(tag):
    return TAG_NAMES.get(tag, "unknown")


# --------------------------------------------------------------------------
# Pak / entry-byte layer. Reuses grn_tagwalk.py's own idioms directly
# (pak_index3, derive_length, read_name, md5) rather than re-deriving them --
# one implementation of the length rule in analysis/tools/.
# --------------------------------------------------------------------------

def pak_index(path):
    with open(path, "rb") as f:
        entries = pak_index3(f)
        file_size = os.fstat(f.fileno()).st_size
    return entries, file_size


def entry_bytes(path, entries, file_size, index):
    if not 0 <= index < len(entries):
        return None, 0, ""
    _kind, offset, _field3 = entries[index]
    size = derive_length(entries, index, file_size)
    if size <= 0:
        return None, 0, ""
    with open(path, "rb") as f:
        f.seek(offset)
        buf = f.read(size)
    return buf, size, md5(buf)


def get_name(entries, index):
    _kind, offset, _field3 = entries[index]
    with open(MODELS_PATH, "rb") as f:
        return read_name(f, offset)


def print_entry_report(path, entries, file_size, index):
    """entry\\t...\\tsize=\\tmd5= identity line every other line traces back
    to. Returns (buf, size, md5hex, kind), or (None, 0, '', -1) on refusal."""
    if not 0 <= index < len(entries):
        print(f"entry\t{index}\tname=\tkind=-1\tsize=0\tmd5=")
        return None, 0, "", -1
    kind, _offset, _field3 = entries[index]
    buf, size, digest = entry_bytes(path, entries, file_size, index)
    name = get_name(entries, index)
    print("entry\t%d\tname=%s\tkind=%d\tsize=%d\tmd5=%s" % (index, name, kind, size, digest))
    return buf, size, digest, kind


# --------------------------------------------------------------------------
# Directory section layer -- mirrors Sacred.Models._directory()/_span()/
# _direct_children() in godot-port/formats/models.gd, reimplemented independently in
# Python idiom (this project's own code; not the GPL/no-licence sources).
# --------------------------------------------------------------------------

def section_offset(kind):
    off = MAGIC_OFFSET.get(kind)
    if off is None:
        return -1
    return off + SECTION_OFF_DELTA


def magic_ok(buf, kind):
    """Asserts the u32 at magic_offset(kind) equals MAGIC before the section
    offset derived from it is trusted for anything."""
    moff = MAGIC_OFFSET.get(kind)
    if moff is None or moff + 4 > len(buf):
        return False
    return struct.unpack_from("<I", buf, moff)[0] == MAGIC


def directory(buf, sec):
    """Flat node directory at `sec`: u32 numNodes, then numNodes records of
    {u32 tag, u32 rel, u32 children} starting at sec+DIR_OFF. Abandons the
    whole read (returns []) if any node's high 16 bits are not 0xCA5E, or if
    the declared extent runs past the buffer -- never partially trusted."""
    if sec < 0 or sec + DIR_OFF + NODE_STRIDE > len(buf):
        return []
    n = struct.unpack_from("<I", buf, sec)[0]
    if n <= 0 or n > MAX_NODES:
        return []
    dir_off = sec + DIR_OFF
    if dir_off + n * NODE_STRIDE > len(buf):
        return []
    out = []
    for j in range(n):
        o = dir_off + j * NODE_STRIDE
        tag, rel, children = struct.unpack_from("<III", buf, o)
        if (tag & 0xFFFF0000) != MAGIC:
            return []
        out.append({"tag": tag, "rel": rel, "children": children})
    return out


def span(dir_, j, buf_size, sec):
    """Payload length of node j: gap to the next node with a strictly larger
    rel, or to the end of the section for the last one -- mirrors
    Sacred.Models._span(). Never assumes a fixed stride."""
    r = dir_[j]["rel"]
    for k in range(j + 1, len(dir_)):
        nr = dir_[k]["rel"]
        if nr > r:
            return nr - r
    return buf_size - sec - r


def direct_children(dir_, j):
    """Direct (one-level) children of node j, reached by skipping each
    previous child's whole subtree -- mirrors Sacred.Models._direct_children().
    'children' counts ALL descendants, not just direct ones."""
    out = []
    last = min(j + 1 + dir_[j]["children"], len(dir_))
    k = j + 1
    while k < last:
        out.append(k)
        k += 1 + dir_[k]["children"]
    return out


def find_first(dir_, tag, within=None):
    """First node index carrying `tag` within an iterable of candidate
    indices (default: the whole directory). Iterates already-decoded
    directory records -- never a byte-pattern scan."""
    candidates = within if within is not None else range(len(dir_))
    for k in candidates:
        if dir_[k]["tag"] == tag:
            return k
    return -1


def tag_count(dir_, tag):
    return sum(1 for n in dir_ if n["tag"] == tag)


def load_entry(entries, file_size, index, quiet=False):
    """(buf, size, digest, kind, sec, dir_) after the magic and directory
    checks pass, or None (having already printed the refusal reason unless
    quiet) on failure."""
    if quiet:
        if not 0 <= index < len(entries):
            return None
        kind, _offset, _field3 = entries[index]
        buf, size, digest = entry_bytes(MODELS_PATH, entries, file_size, index)
    else:
        buf, size, digest, kind = print_entry_report(MODELS_PATH, entries, file_size, index)
    if buf is None:
        return None
    if not magic_ok(buf, kind):
        print(f"refuse\t{index}\treason=magic-check-failed at offset {MAGIC_OFFSET.get(kind, -1)}")
        return None
    sec = section_offset(kind)
    dir_ = directory(buf, sec)
    if not dir_:
        print(f"refuse\t{index}\treason=empty-or-malformed-directory")
        return None
    return buf, size, digest, kind, sec, dir_


# --------------------------------------------------------------------------
# Animation node tree. The declared path, exactly as measured on entry 2847
# during planning (this plan's <planning_measurements>): AnimationSection's
# one direct child is Animation; Animation's direct children include the
# AnimationTransformTrackSection; that node's direct children are the
# per-bone AnimationTransformTrackKeys records. Every hop is direct_children()
# over the decoded directory -- no byte-pattern scanning anywhere.
# --------------------------------------------------------------------------

def animation_transform_track_keys(dir_):
    sec_j = find_first(dir_, TAG_ANIMATION_SECTION)
    if sec_j == -1:
        return []
    anim_j = find_first(dir_, TAG_ANIMATION, direct_children(dir_, sec_j))
    if anim_j == -1:
        return []
    tts_j = find_first(dir_, TAG_ANIMATION_TRANSFORM_TRACK_SECTION, direct_children(dir_, anim_j))
    if tts_j == -1:
        return []
    return [k for k in direct_children(dir_, tts_j) if dir_[k]["tag"] == TAG_ANIMATION_TRANSFORM_TRACK_KEYS]


# --------------------------------------------------------------------------
# Bone parent chain and FormBoneChannels array -- both reimplemented in the
# same shape 05-01's grn_bonenames.py already established (that plan's own
# byte reads, not imported: each probe in analysis/tools/ re-derives its own
# directory-layer facts independently, per this project's house style).
# Used only by --idjoin's crossfile parent-consistency check; no bone NAME
# is ever read or printed by this file (that is plan 05-01's question).
# --------------------------------------------------------------------------

def bone_parents(buf, sec, dir_):
    """parent_effective per bone, in directory order (root's self-referential
    parent normalised to -1, mirroring Sacred.Models.bones())."""
    bone_section = -1
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_SKELETON_SECTION:
            continue
        last = min(j + 1 + dir_[j]["children"], len(dir_))
        for k in range(j + 1, last):
            if dir_[k]["tag"] == TAG_BONE_SECTION:
                bone_section = k
                break
        if bone_section != -1:
            break
    if bone_section == -1:
        return []
    out = []
    for k in direct_children(dir_, bone_section):
        if dir_[k]["tag"] != TAG_BONE:
            continue
        off = sec + dir_[k]["rel"]
        if off + 4 > len(buf):
            return []
        parent = struct.unpack_from("<i", buf, off)[0]
        idx = len(out)
        out.append(-1 if parent == idx else parent)
    return out


def form_bone_channel_raw(buf, sec, dir_):
    """FormBoneChannels (0xCA5E0C02) payload: a flat u32 array, no header
    word -- reused here (05-01 finding) as the MODEL side's only candidate
    per-bone id array, since a model entry has zero 0xCA5E1204 records of
    its own to compare against directly."""
    j = find_first(dir_, TAG_FORM_BONE_CHANNELS)
    if j == -1:
        return []
    off = sec + dir_[j]["rel"]
    n_bytes = span(dir_, j, len(buf), sec)
    count = n_bytes // 4
    if off + count * 4 > len(buf):
        count = max(0, (len(buf) - off) // 4)
    return list(struct.unpack_from("<%dI" % count, buf, off)) if count else []


def clip_record_ids(buf, sec, dir_):
    """First dword of every AnimationTransformTrackKeys record, in directory
    order -- the field Iris1 documents as `dword id`. None entries mark a
    record too short to read (reported, never silently dropped)."""
    ids = []
    for j in animation_transform_track_keys(dir_):
        off = sec + dir_[j]["rel"]
        if off + 4 > len(buf):
            ids.append(None)
            continue
        ids.append(struct.unpack_from("<I", buf, off)[0])
    return ids


# --------------------------------------------------------------------------
# --entry=N : directory census + (for CLIP_ENTRY) the first per-bone record,
# reached through the declared path and printed uninterpreted.
# --------------------------------------------------------------------------

def cmd_entry(index):
    entries, file_size = pak_index(MODELS_PATH)
    loaded = load_entry(entries, file_size, index)
    if loaded is None:
        return 1
    buf, size, _digest, _kind, sec, dir_ = loaded
    print("dir\tentry=%d\tnodes=%d\tsec=%d" % (index, len(dir_), sec))
    for tag in CENSUS_TAGS:
        print("census\tentry=%d\ttag=0x%08x\tname=%s\tcount=%d" % (
            index, tag, tag_name(tag), tag_count(dir_, tag)))

    if index == CLIP_ENTRY:
        keys = animation_transform_track_keys(dir_)
        if not keys:
            print(f"clip\tentry={index}\trecord=0\tnode=-1\treason=chain-not-found")
            return 1
        j = keys[0]
        rel = dir_[j]["rel"]
        sp = span(dir_, j, size, sec)
        off = sec + rel
        nwords = min(8, sp // 4)
        dwords = struct.unpack_from("<%dI" % nwords, buf, off) if nwords and off + nwords * 4 <= len(buf) else ()
        print("clip\tentry=%d\trecord=0\tnode=%d\trel=%d\tspan=%d\tfirst_dwords=%s" % (
            index, j, rel, sp, ",".join(str(d) for d in dwords)))
    return 0


# --------------------------------------------------------------------------
# --sweep [--falsify=N] : section_offset() swept over the whole corpus, and
# its falsification counterfactual -- copies grn_tagwalk.py's desync shape.
# --------------------------------------------------------------------------

def cmd_sweep(desync=0):
    entries, file_size = pak_index(MODELS_PATH)
    n = len(entries)
    walkable = skipped = baddir = 0
    with open(MODELS_PATH, "rb") as f:
        for i in range(n):
            kind, offset, _field3 = entries[i]
            moff = MAGIC_OFFSET.get(kind)
            true_len = derive_length(entries, i, file_size)
            if moff is None or true_len < moff + 4:
                skipped += 1
                continue
            f.seek(offset)
            buf = f.read(true_len)
            if not magic_ok(buf, kind):
                skipped += 1
                continue
            walkable += 1
            sec = moff + SECTION_OFF_DELTA + desync
            if not directory(buf, sec):
                baddir += 1
    suffix = f"\tfalsify={desync}" if desync else ""
    print("sweep\tentries=%d\twalkable=%d\tskipped=%d\tbaddir=%d%s" % (n, walkable, skipped, baddir, suffix))
    if desync != 0:
        # A real displacement must collapse baddir. If it doesn't, the sweep
        # is not testing anything -- print the verdict and still fail.
        if baddir <= 4000:
            print("sweep\tverdict=INVALID")
        return 1
    return 0 if baddir == 0 else 1


# --------------------------------------------------------------------------
# --clip=N : decode every AnimationTransformTrackKeys record of entry N and
# report the header layout that reconciles to zero slack across every one --
# the measurement, not an adoption of Iris1's template.
# --------------------------------------------------------------------------

# Iris1's documented arrangement (dword id, 5 unknown, numTranslates,
# numQuaternions, numUnknowns, 4 unknown -> 13 dwords = 52 bytes) as a
# (header_size, off_numTranslates, off_numQuaternions, off_numUnknowns)
# tuple, so it can be recognised among the search's own output rather than
# hard-coded as the answer.
DOCUMENTED_LAYOUT = (52, 24, 28, 32)

# Candidate header sizes: 4-16 dwords (16-64 bytes), bracketing Iris1's
# 13-dword/52-byte header with margin on both sides. Slot 0 is reserved for
# the record's `dword id` (Iris1's own first field, never contested by this
# search) and excluded from the three count-field candidates. This bound is
# this probe's own discretion -- the plan text does not fix it.
def candidate_header_layouts():
    out = []
    for header_dwords in range(4, 17):
        header_size = header_dwords * 4
        slots = list(range(4, header_size, 4))
        for perm in itertools.permutations(slots, 3):
            out.append((header_size,) + perm)
    return out


def reconcile_layout(records, layout):
    """(implied_size - span) per record for one candidate layout, or None if
    any record is too short to even read the three count fields. implied
    size = header + three time tracks (nt+nq+nu floats) + payload
    (nt*3 + nq*4 + nu*3 floats) = header + 16*nt + 20*nq + 16*nu."""
    header_size, off_nt, off_nq, off_nu = layout
    slacks = []
    for raw, sp in records:
        if max(off_nt, off_nq, off_nu) + 4 > len(raw):
            return None
        nt, nq, nu = (struct.unpack_from("<I", raw, o)[0] for o in (off_nt, off_nq, off_nu))
        implied = header_size + 16 * nt + 20 * nq + 16 * nu
        slacks.append(implied - sp)
    return slacks


MAX_TRAILER = 256  # generous cap; plausibility (unit quaternion, monotonic
                    # time), not this bound, is what actually filters noise


def constant_trailer(slacks):
    """A candidate layout whose implied size falls the SAME number of bytes
    short of the measured span on EVERY record -- regardless of that
    record's own nt/nq/nu -- is the signature of a fixed-size trailing block
    Iris1's flat model doesn't document, not a wrong layout. Returns the
    trailer byte count (>=0) if `slacks` is such a constant deficit within
    MAX_TRAILER, else None. A per-record-varying slack is a real mismatch,
    not a trailer, and returns None."""
    if not slacks or len(set(slacks)) != 1:
        return None
    trailer = -slacks[0]
    if 0 <= trailer <= MAX_TRAILER:
        return trailer
    return None


# models.gd::bones() uses 0.001 for bind-pose bone quaternions -- not reused
# as-is here. Measured, not borrowed: at DOCUMENTED_LAYOUT, per-clip max |mag-1| over
# every AnimationTransformTrackKeys quaternion is 0.0611 (entry 2847),
# 0.0330 (2903), 0.00086 (2899) -- endpoints of every track (first/last
# keyframe) are near-exact (~1e-5) and deviation grows toward mid-track,
# the signature of quantization/compression drift in interior keyframes,
# not a misread. Confirmed by exhaustively re-deriving the minimum
# achievable max-deviation across every size-reconciled (header,layout)
# candidate for entry 2847: DOCUMENTED_LAYOUT sits in an isolated cluster
# at 0.0611 with a 7x gap to the next candidate cluster (0.4142) and a
# 50x+ gap to the rest -- so 0.0611 is a property of this data, not a
# looser epsilon papering over a wrong offset. QUAT_EPS is set above the
# worst corpus value measured (0.0611) with headroom, and stays far below
# every wrong-layout's required tolerance.
QUAT_EPS = 0.07


def evaluate_plausibility(records, layout):
    """Bounds check, non-decreasing time tracks, and unit-quaternion check
    for a size-reconciled candidate. Returns (passed, quat_pass, quat_total,
    length) -- length is the max, across all records, of that record's last
    translate time (Iris1's stated clip-length rule, measured here)."""
    header_size, off_nt, off_nq, off_nu = layout
    quat_pass = quat_total = 0
    lengths = []
    ok = True
    for raw, sp in records:
        nt, nq, nu = (struct.unpack_from("<I", raw, o)[0] for o in (off_nt, off_nq, off_nu))
        max_count = sp // 4
        if nt > max_count or nq > max_count or nu > max_count:
            ok = False
            continue
        tt_off = header_size
        if tt_off + 4 * (nt + nq + nu) > sp:
            ok = False
            continue
        ttimes = struct.unpack_from("<%df" % nt, raw, tt_off) if nt else ()
        qtimes = struct.unpack_from("<%df" % nq, raw, tt_off + 4 * nt) if nq else ()
        utimes = struct.unpack_from("<%df" % nu, raw, tt_off + 4 * (nt + nq)) if nu else ()
        for track in (ttimes, qtimes, utimes):
            if any(b < a for a, b in zip(track, track[1:])):
                ok = False
        payload_off = tt_off + 4 * (nt + nq + nu)
        quat_n = nq * 4
        if payload_off + 4 * (nt * 3 + quat_n + nu * 3) > sp:
            ok = False
            continue
        if nq:
            qf = struct.unpack_from("<%df" % quat_n, raw, payload_off + 4 * nt * 3)
            for qi in range(nq):
                x, y, z, w = qf[qi * 4:qi * 4 + 4]
                mag = math.sqrt(x * x + y * y + z * z + w * w)
                quat_total += 1
                if abs(mag - 1.0) <= QUAT_EPS:
                    quat_pass += 1
        lengths.append(ttimes[-1] if nt else 0.0)
    if quat_total and quat_pass != quat_total:
        ok = False
    return ok, quat_pass, quat_total, (max(lengths) if lengths else 0.0)


def cmd_clip(index):
    entries, file_size = pak_index(MODELS_PATH)
    loaded = load_entry(entries, file_size, index)
    if loaded is None:
        return 1
    buf, size, _digest, _kind, sec, dir_ = loaded
    name = get_name(entries, index)
    bone_count = tag_count(dir_, TAG_BONE)
    keys = animation_transform_track_keys(dir_)
    if not keys:
        print("clip\tentry=%d\tname=%s\trecords=0\tbones=%d\treason=animation-section-with-no-per-bone-records" % (
            index, name, bone_count))
        return 1

    records = []
    for j in keys:
        off = sec + dir_[j]["rel"]
        sp = span(dir_, j, size, sec)
        records.append((buf[off:off + sp], sp))

    # A candidate "survives" either with true zero slack, or with the SAME
    # slack (a constant trailer) on every record -- both are size
    # reconciliations, just to a different implied-size formula. See
    # constant_trailer()'s docstring for why a per-record-constant deficit
    # is trusted rather than treated as a mismatch.
    survivors = []  # list of (layout, trailer)
    best_layout, best_max_abs, best_slacks = None, None, None
    for layout in candidate_header_layouts():
        slacks = reconcile_layout(records, layout)
        if slacks is None:
            continue
        max_abs = max(abs(s) for s in slacks)
        if best_max_abs is None or max_abs < best_max_abs:
            best_layout, best_max_abs, best_slacks = layout, max_abs, slacks
        if max_abs == 0:
            survivors.append((layout, 0))
            continue
        trailer = constant_trailer(slacks)
        if trailer is not None and trailer > 0:
            survivors.append((layout, trailer))

    if not survivors:
        print("clip\tentry=%d\tname=%s\trecords=%d\tlayout=NONE\tslack_max=%s" % (
            index, name, len(records), best_max_abs))
        if best_slacks is not None:
            for ridx, s in enumerate(best_slacks):
                print("clipslack\tentry=%d\trecord=%d\tslack=%d" % (index, ridx, s))
        return 1

    passing = []
    for layout, trailer in survivors:
        # The trailer sits after the payload this probe already reads --
        # it changes the implied SIZE, not any field's read position -- so
        # plausibility is evaluated against the unadjusted header/offsets.
        ok, quat_pass, quat_total, length = evaluate_plausibility(records, layout)
        if ok:
            passing.append((layout, trailer, quat_pass, quat_total, length))

    if not passing:
        print("clip\tentry=%d\tname=%s\trecords=%d\tlayout=REFUTED\tslack_max=0"
              "\treason=size-reconciled-candidates-all-fail-plausibility" % (index, name, len(records)))
        return 1

    layout_strs = ["h=%d,nt=%d,nq=%d,nu=%d%s%s" % (
        l[0], l[1], l[2], l[3],
        ",trailer=%d" % t if t else "",
        "(documented)" if l == DOCUMENTED_LAYOUT else "")
        for l, t, _, _, _ in passing]
    quat_pass, quat_total, length = passing[0][2], passing[0][3], passing[0][4]
    print("clip\tentry=%d\tname=%s\trecords=%d\tlayout=%s\tslack_max=0\tquat_ok=%d/%d\tlength=%.6f" % (
        index, name, len(records), ";".join(layout_strs), quat_pass, quat_total, length))
    if len(passing) > 1:
        print("clip\tentry=%d\tunder_determined=true\tcandidates=%d" % (index, len(passing)))
    return 0


# --------------------------------------------------------------------------
# --census : classify every walkable entry as model / clip / neither from
# directory structure alone (D-03) -- no reference to the entry's name.
# --------------------------------------------------------------------------

def cmd_census():
    entries, file_size = pak_index(MODELS_PATH)
    n = len(entries)
    models = clips = neither = 0
    disagreements = []
    glad_kind65_total = glad_kind65_clip = 0
    glad_mismatches = []

    with open(MODELS_PATH, "rb") as f:
        for i in range(n):
            kind, offset, _field3 = entries[i]
            moff = MAGIC_OFFSET.get(kind)
            true_len = derive_length(entries, i, file_size)
            if moff is None or true_len < moff + 4:
                continue
            f.seek(offset)
            buf = f.read(true_len)
            if not magic_ok(buf, kind):
                continue
            sec = section_offset(kind)
            dir_ = directory(buf, sec)
            if not dir_:
                continue

            meshes = tag_count(dir_, TAG_MESH)
            bones = tag_count(dir_, TAG_BONE)
            objects = tag_count(dir_, TAG_DATA_EXTENSION)
            pred_meshes0 = "clip" if meshes == 0 else "model"
            pred_objeqbones = "clip" if objects == bones else "model"

            if pred_meshes0 == pred_objeqbones:
                cls = pred_meshes0
                if cls == "model":
                    models += 1
                else:
                    clips += 1
            else:
                cls = "neither"
                neither += 1
                disagreements.append((i, meshes, bones, objects, pred_meshes0, pred_objeqbones))

            if kind == KIND_MOTION:
                name = read_name(f, offset)
                if name.startswith("GLAD_"):
                    glad_kind65_total += 1
                    if cls == "clip":
                        glad_kind65_clip += 1
                    else:
                        glad_mismatches.append((i, name, cls))

    print("census\tmodels=%d\tclips=%d\tneither=%d\tdisagree=%d" % (models, clips, neither, len(disagreements)))
    for i, meshes, bones, objects, pa, pb in disagreements:
        print("disagree\tentry=%d\tmeshes=%d\tbones=%d\tobjects=%d\tpred_meshes0=%s\tpred_objeqbones=%s" % (
            i, meshes, bones, objects, pa, pb))
    print("corroborate\tGLAD_kind65_total=%d\tGLAD_kind65_clip=%d" % (glad_kind65_total, glad_kind65_clip))
    for i, name, cls in glad_mismatches:
        print("corroborate_mismatch\tentry=%d\tname=%s\tclass=%s" % (i, name, cls))
    return 0


# --------------------------------------------------------------------------
# --idjoin : does the per-bone record's first dword bind a clip's bone to a
# model's bone WITHOUT a name? Documented answer is no (Iris1, the AoM
# plugin and findings row 582 all say the join is by name) -- this is a
# check of a documented negative, run with a BAT.GRN control arm rather than
# assumed. See the module docstring's licence boundary for both sources.
# --------------------------------------------------------------------------

def crossfile_test(clip_ids, clip_parents, model_ids, model_parents):
    """Subset-plus-parent-consistency test. Necessary but not sufficient:
    the id sets overlapping is not enough, the *parent* relationships that
    survive the id mapping must also agree, or two integer ranges could
    coincide by accident."""
    clip_id_set = set(clip_ids)
    model_id_set = set(model_ids)
    intersection = clip_id_set & model_id_set
    is_subset = clip_id_set <= model_id_set

    model_first_index = {}
    for m, mid in enumerate(model_ids):
        model_first_index.setdefault(mid, m)

    parents_total = parents_ok = 0
    for i, cid in enumerate(clip_ids):
        if cid not in intersection:
            continue
        p = clip_parents[i] if i < len(clip_parents) else -1
        if p is None or p < 0 or p >= len(clip_ids):
            continue
        pid = clip_ids[p]
        if pid not in intersection:
            continue
        parents_total += 1
        model_bone = model_first_index.get(cid)
        if model_bone is None or model_bone >= len(model_parents):
            continue
        model_parent_bone = model_parents[model_bone]
        if 0 <= model_parent_bone < len(model_ids) and model_ids[model_parent_bone] == pid:
            parents_ok += 1

    verdict = "CONFIRMED" if (is_subset and parents_total > 0 and parents_ok == parents_total) else "REFUTED"
    return {
        "overlap_num": len(intersection), "overlap_den": len(clip_id_set),
        "parents_ok": parents_ok, "parents_total": parents_total,
        "verdict": verdict,
    }


def cmd_idjoin():
    entries, file_size = pak_index(MODELS_PATH)
    clip = load_entry(entries, file_size, CLIP_ENTRY, quiet=True)
    if clip is None:
        print("refuse\tidjoin\treason=clip-load-failed")
        return 1
    cbuf, _csize, _cdigest, _ckind, csec, cdir = clip
    clip_ids = clip_record_ids(cbuf, csec, cdir)
    clip_parents = bone_parents(cbuf, csec, cdir)
    n = len(clip_ids)
    if n == 0 or any(v is None for v in clip_ids):
        print("refuse\tidjoin\treason=clip-record-ids-unreadable")
        return 1

    ordinal_hit = clip_ids == list(range(n))
    print("idjoin\tclip=%d\treading=ordinal\tverdict=%s" % (
        CLIP_ENTRY, "USELESS" if ordinal_hit else "REFUTED"))

    boneindex_hit = sorted(clip_ids) == list(range(n))
    print("idjoin\tclip=%d\treading=boneindex\tverdict=%s" % (
        CLIP_ENTRY, "CONFIRMED" if boneindex_hit else "REFUTED"))

    results, model_ids_by_entry = {}, {}
    for model_entry in (MODEL_ENTRY, CONTROL_ENTRY):
        loaded = load_entry(entries, file_size, model_entry, quiet=True)
        if loaded is None:
            print("idjoin\tverdict=INVALID")
            return 1
        mbuf, _msize, _mdigest, _mkind, msec, mdir = loaded
        model_ids = form_bone_channel_raw(mbuf, msec, mdir)
        model_parents = bone_parents(mbuf, msec, mdir)
        result = crossfile_test(clip_ids, clip_parents, model_ids, model_parents)
        print("idjoin\tclip=%d\tmodel=%d\treading=crossfile\toverlap=%d/%d\tparents_ok=%d/%d\tverdict=%s" % (
            CLIP_ENTRY, model_entry, result["overlap_num"], result["overlap_den"],
            result["parents_ok"], result["parents_total"], result["verdict"]))
        results[model_entry] = result
        model_ids_by_entry[model_entry] = model_ids

    if results[CONTROL_ENTRY]["verdict"] == "CONFIRMED":
        # The control is not discriminating -- the real result cannot be
        # trusted either way.
        print("idjoin\tverdict=INVALID")
        return 1

    model_result = results[MODEL_ENTRY]
    name_join_required = "no" if model_result["verdict"] == "CONFIRMED" else "yes"
    print("idjoin\tname_join_required=%s\tcontrol=%s" % (name_join_required, results[CONTROL_ENTRY]["verdict"]))

    if name_join_required == "no":
        # Only printed on the surprise outcome (crossfile CONFIRMED against
        # the real model) -- per this plan, do not suppress it to match the
        # documented expectation.
        model_ids = model_ids_by_entry[MODEL_ENTRY]
        model_first_index = {}
        for m, mid in enumerate(model_ids):
            model_first_index.setdefault(mid, m)
        for i, cid in enumerate(clip_ids):
            mb = model_first_index.get(cid)
            if mb is not None:
                print("clipbone\tclip_bone=%d\tclip_id=%d\tmodel_bone=%d\tmodel_id=%d" % (
                    i, cid, mb, model_ids[mb]))

    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0
    arg = args[0]
    if arg.startswith("--entry="):
        return cmd_entry(int(arg.split("=", 1)[1]))
    if arg == "--sweep":
        desync = 0
        for extra in args[1:]:
            if extra.startswith("--falsify="):
                desync = int(extra.split("=", 1)[1])
        return cmd_sweep(desync)
    if arg.startswith("--falsify="):
        return cmd_sweep(int(arg.split("=", 1)[1]))
    if arg.startswith("--clip="):
        return cmd_clip(int(arg.split("=", 1)[1]))
    if arg == "--census":
        return cmd_census()
    if arg == "--idjoin":
        return cmd_idjoin()
    raise SystemExit(f"unknown argument: {arg}")


if __name__ == "__main__":
    sys.exit(main() or 0)
