#!/usr/bin/env python3
"""Bone-index -> bone-name resolution probe for Granny 1.x `.GRN` entries
inside `models.pak`.

Personal-use interoperability work on legally-owned media. Output stays local.

WHAT THIS IS FOR. `godot-port/sacred.gd::bones()` decodes the 68-byte bone
record correctly but returns an honestly EMPTY `name` field: the record
itself carries no name, and a name must instead be resolved through a
separate object/string chain elsewhere in the entry. This probe walks that
chain against Sacred's own bytes and falsifies it with the bone hierarchy
itself as the oracle, rather than trusting it because it is documented
elsewhere.

WHAT IS ALREADY CONFIRMED AND NOT BEING RE-LITIGATED (findings row 583):
the string table (leaf tag 0xCA5E0200: dword numEntries, dword unknown, then
numEntries NUL-terminated strings) and the DataExtension object/property
chain (0xCA5E0F00 DataExtension -> 0xCA5E0F05 DataExtensionPropertySection
-> {0xCA5E0F01 key textid, 0xCA5E0F06 value-section, 0xCA5E0F02 value
textid} triples, both textids resolved through the string table) both
decode correctly against GLADIATOR.GRN -- object 0's __ObjectName already
resolves to 'Omni03'. This probe re-derives both from scratch (never reads
another module's decode of them) so it can be re-run standalone, but treats
neither as an open question.

WHAT IS DOCUMENTED BUT NOT YET MEASURED (findings row 585, D-22): the chain
from a BONE to the DataExtension that names it. Two hops, both indices
1-based: FormBoneChannels.TransformChannelIndices[i] selects a
TransformChannel node; that node's FIRST child is a DataExtensionReference
holding a DataExtensionIndex; DataExtensions[index]['__ObjectName'] is the
name. This is a HYPOTHESIS from an outside project until the four-predicate
harness below confirms or refutes it against Sacred's own bytes.

LICENCE BOUNDARY (D-21, D-23). Two outside sources are used here, on
identical terms: github.com/SiENcE/Iris1 `src/granny` (GPL v2), and
github.com/ptasev/Age-of-Mythology, the AoM Model Plugin (NO licence file at
all, which GitHub's own metadata reports as all-rights-reserved -- not
permissive). Both are read ONLY as documentation of the Granny 1.x `.grn`
container format: tag numbers, node-type names and record layouts are facts
about a file format and are used as such. Neither project's code, comments
or class structure is ported, translated or paraphrased here -- the walk
below is written flat, in this project's own idiom (see `grn_tagwalk.py`,
whose conventions this module reuses), not transcribed from either reader's
shape. `godot-port/` never imports this file and this file never imports
`godot-port/`.

Node-type names used throughout are the AoM Model Plugin's authoritative
table (row 585), which supersedes three names findings row 583 carried as
Iris1-derived GUESSES: 0xCA5E0B00 is TransformChannel (not "boneobject"),
and 0xCA5E0C02 / 0xCA5E0C05 are FormBoneChannels / FormPoseWeights, two
DISTINCT node types -- not, as Iris1 misread them, a start/end bracket
around one 272-byte span.

    ./grn_bonenames.py --entry=589     # one entry's directory census + bone-0 trace
    ./grn_bonenames.py --entry=2847
    ./grn_bonenames.py --harness       # 7 candidate arms + 1 control, both entries
    ./grn_bonenames.py --control       # the scrambled control arm alone
    ./grn_bonenames.py --report        # full verdict + bone tables

MESH-SKINNING CLASSIFIER (P3 scope only): mesh-skinning data (FormMeshBone/MeshWeights) is tested as a
name-independent, structural signal for narrowing which bones predicate P3
(the light-naming-convention check) judges. Authorised use is P3-scope-only
(Use A); it is NEVER authorised to drop a bone from a rig/skeleton (Use B),
regardless of verdict.

    ./grn_bonenames.py --skincensus=589   # per-bone mesh-influence census
    ./grn_bonenames.py --skinclass=589    # skinned/ancestral/skeletal partition + complement
    ./grn_bonenames.py --skincontrol      # inverted-narrowing counterfactual
"""
import hashlib
import os
import struct
import sys

from grn_tagwalk import pak_index3, derive_length, read_name, md5, GAME, KIND_MESH, KIND_MOTION

MODELS_PATH = os.path.join(GAME, "pak", "models.pak")

MAGIC = 0xCA5E0000

# magic_offset(kind) mirrors Sacred.Models.MAGIC_OFF_MESH / MAGIC_OFF_MOTION
# (godot-port/sacred.gd) and grn_tagwalk.py's MAGIC_OFFSET -- same numbers,
# re-declared here rather than imported so this probe's directory-section
# math is self-contained and legible on its own.
MAGIC_OFFSET = {KIND_MESH: 0x4EA, KIND_MOTION: 0x140}

# The flat node directory sits 376 bytes after the chunk-stream root tag, in
# BOTH kinds (godot-port/sacred.gd SECTION_OFF_MESH=1634, MAGIC_OFF_MESH=0x4EA
# =1258, 1634-1258=376; confirmed for kind=65 by direct measurement).
SECTION_DELTA = 376
DIR_OFF = 16
NODE_STRIDE = 12
MAX_NODES = 1 << 20

# Directory node tags this probe reads. Values from the AoM Model Plugin's
# GrnNodeType.cs (row 585); names likewise. Every one of these also appears,
# independently, on sacred.gd's own already-shipped geometry/skeleton decode
# (0505/0506/0507/0508/0702/0C09/0C0A), which row 585 notes as an
# independent confirmation of the tag table.
TAG_SKELETON_SECTION = 0xCA5E0507
TAG_BONE_SECTION = 0xCA5E0508
TAG_BONE = 0xCA5E0506
TAG_STRING_TABLE = 0xCA5E0200
TAG_DATA_EXTENSION = 0xCA5E0F00
TAG_DATA_EXTENSION_PROPERTY = 0xCA5E0F01          # key textid
TAG_DATA_EXTENSION_PROPERTY_VALUE = 0xCA5E0F02    # value textid
TAG_DATA_EXTENSION_REFERENCE = 0xCA5E0F04         # payload: 1-based DataExtensionIndex
TAG_DATA_EXTENSION_PROPERTY_SECTION = 0xCA5E0F05  # container of {F01,F06,F02} triples
TAG_DATA_EXTENSION_VALUE_SECTION = 0xCA5E0F06
TAG_TRANSFORM_CHANNEL = 0xCA5E0B00
TAG_FORM_BONE_CHANNELS = 0xCA5E0C02
TAG_FORM_POSE_WEIGHTS = 0xCA5E0C05

# Mesh-skinning tags (05-09 gap closure). Same AoM Model Plugin table (row
# 585) as every other tag above; independently confirmed by godot-port/
# sacred.gd's own already-shipped, zero-slack mesh_weights() decode (lines
# 1569-1708), which this module's mesh-side functions below re-derive from
# scratch in Python idiom -- never transliterated from that GDScript.
TAG_MESH = 0xCA5E0601
TAG_MESH_VERTICES = 0xCA5E0801
TAG_MESH_NORMALS = 0xCA5E0802
TAG_MESH_TRIANGLES = 0xCA5E0901
TAG_MESH_WEIGHTS = 0xCA5E0702
TAG_FORM_MESH_BONE_SECTION = 0xCA5E0C09
TAG_FORM_MESH_BONE = 0xCA5E0C0A

BONE_STRIDE = 68

OBJECT_NAME_KEY = "__ObjectName"
ROOT_NAMES = {"__root", "root", "bip01"}
LEFT_HAND = "bip01 l hand"
RIGHT_HAND = "bip01 r hand"


# --------------------------------------------------------------------------
# Pak / entry-byte layer. Reuses grn_tagwalk.py's own idioms directly
# (pak_index3, derive_length, read_name) rather than re-deriving them.
# --------------------------------------------------------------------------

def pak_index(path):
    with open(path, "rb") as f:
        entries = pak_index3(f)
        file_size = os.fstat(f.fileno()).st_size
    return entries, file_size


def entry_bytes(path, entries, file_size, index):
    """(buf, size, md5hex) for one pak entry, read by the gap-to-next-entry
    length rule (never the pak index's own third field -- see
    grn_tagwalk.py's derive_length docstring)."""
    if not 0 <= index < len(entries):
        return None, 0, ""
    kind, offset, _field3 = entries[index]
    size = derive_length(entries, index, file_size)
    if size <= 0:
        return None, 0, ""
    with open(path, "rb") as f:
        f.seek(offset)
        buf = f.read(size)
    return buf, size, md5(buf)


def print_entry_report(path, entries, file_size, index):
    """The one-line report header every other line in a --report run traces
    back to: entry index, name, kind, size and md5 of the exact bytes read.
    Returns (buf, size, md5hex, kind) or (None, 0, '', -1) on refusal."""
    if not 0 <= index < len(entries):
        print(f"entry\t{index}\tname=\tkind=-1\tsize=0\tmd5=")
        return None, 0, "", -1
    kind, offset, _field3 = entries[index]
    buf, size, digest = entry_bytes(path, entries, file_size, index)
    name = read_name(open(path, "rb"), offset)
    print("entry\t%d\tname=%s\tkind=%d\tsize=%d\tmd5=%s" % (index, name, kind, size, digest))
    return buf, size, digest, kind


# --------------------------------------------------------------------------
# Directory section layer -- mirrors Sacred.Models._directory()/_span()/
# _direct_children() in godot-port/sacred.gd, reimplemented independently in
# Python idiom (never by reading that file's source into this one).
# --------------------------------------------------------------------------

def section_offset(kind):
    off = MAGIC_OFFSET.get(kind)
    if off is None:
        return -1
    return off + SECTION_DELTA


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
    whole read (returns []) if any node's high 16 bits are not 0xCA5E or if
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
    Sacred.Models._span()."""
    r = dir_[j]["rel"]
    for k in range(j + 1, len(dir_)):
        nr = dir_[k]["rel"]
        if nr > r:
            return nr - r
    return buf_size - sec - r


def direct_children(dir_, j):
    """Direct (one-level) children of node j, reached by skipping each
    previous child's whole subtree -- mirrors Sacred.Models._direct_children().
    'children' is the count of ALL descendants, not just direct ones."""
    out = []
    last = min(j + 1 + dir_[j]["children"], len(dir_))
    k = j + 1
    while k < last:
        out.append(k)
        k += 1 + dir_[k]["children"]
    return out


def child_with_tag(dir_, j, tag):
    """First node carrying `tag` anywhere in j's declared descendant span
    (NOT one-level-only -- mirrors sacred.gd::_child_with_tag(), which
    deliberately searches the whole subtree because a Mesh's vertices/
    normals/triangles/weights children sit at varying depths beneath it,
    unlike direct_children()'s one-level walk used for RenderPass-shaped
    trees where the same tag recurs at several depths)."""
    last = min(j + 1 + dir_[j]["children"], len(dir_))
    for k in range(j + 1, last):
        if dir_[k]["tag"] == tag:
            return k
    return -1


def node_u32(buf, sec, dir_, j):
    """The single u32 payload word at node j's own rel -- the shape every
    leaf-scalar node here uses (DataExtensionReference's index,
    DataExtensionProperty/PropertyValue's textid)."""
    off = sec + dir_[j]["rel"]
    if off + 4 > len(buf):
        return None
    return struct.unpack_from("<I", buf, off)[0]


# --------------------------------------------------------------------------
# String table.
# --------------------------------------------------------------------------

def strings(buf, sec, dir_):
    """StringTable (0xCA5E0200): dword numEntries, dword unknown, then
    numEntries NUL-terminated byte strings. Index 0 is the empty string and
    is a valid, decodable result -- not a sentinel for 'missing'."""
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_STRING_TABLE:
            continue
        off = sec + dir_[j]["rel"]
        if off + 8 > len(buf):
            return []
        n = struct.unpack_from("<I", buf, off)[0]
        pos = off + 8
        out = []
        for _ in range(n):
            end = buf.find(b"\x00", pos)
            if end == -1:
                break
            out.append(buf[pos:end].decode("latin1", "replace"))
            pos = end + 1
        return out
    return []


def resolve_textid(strs, textid):
    if textid is None or not 0 <= textid < len(strs):
        return None
    return strs[textid]


# --------------------------------------------------------------------------
# DataExtension objects (already-confirmed chain, re-derived independently).
# --------------------------------------------------------------------------

def data_extensions(buf, sec, dir_, strs):
    """Every 0xCA5E0F00 DataExtension node in directory order. For each,
    walk its direct children to the 0xCA5E0F05 DataExtensionPropertySection,
    then that section's DIRECT children, each an 0xCA5E0F01
    DataExtensionProperty (key textid). Measured nesting (NOT a sibling
    triple, despite the tag family reading like one): each F01 key node's
    OWN subtree contains exactly one 0xCA5E0F06 DataExtensionValueSection,
    which in turn contains exactly one 0xCA5E0F02 DataExtensionPropertyValue
    -- F01 wraps F06 wraps F02, three levels deep, not three siblings.

    Measured record layout (raw bytes, GLADIATOR.GRN entry 589, offsets
    16684-16696): one property is 12 bytes -- {key textid, u32 unknown,
    value textid}. F01's OWN rel is the key textid's offset (works
    directly). F06 and F02 both declare the SAME rel (F02 shares its
    wrapper's rel, the identical "zero-length nested leaf" convention
    Sacred.Models._span() already documents for BoneSection/Bone and
    Mesh/first-child) -- so F02's declared rel is NOT where its dword is.
    The value textid is the SECOND dword of F06's 8-byte payload, i.e. at
    F06's own rel + 4. Confirmed: rel 16700 (F06 wrapping __ObjectName's
    F02) + 4 = 16704, whose dword resolves to string index 5 = 'Omni03',
    matching findings row 583 exactly.

    Both textids resolve through `strs`. Returns a list of {'index': j,
    'props': {key_string: value_string}} in directory order -- directory
    order is what the documented chain's DataExtensionIndex (1-based) is
    claimed to index into; that claim is exactly what the harness below
    tests, never assumed silently here."""
    out = []
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_DATA_EXTENSION:
            continue
        props = {}
        for sk in direct_children(dir_, j):
            if dir_[sk]["tag"] != TAG_DATA_EXTENSION_PROPERTY_SECTION:
                continue
            for k_node in direct_children(dir_, sk):
                if dir_[k_node]["tag"] != TAG_DATA_EXTENSION_PROPERTY:
                    continue
                key = resolve_textid(strs, node_u32(buf, sec, dir_, k_node))
                value_section = None
                last = min(k_node + 1 + dir_[k_node]["children"], len(dir_))
                for vk in range(k_node + 1, last):
                    if dir_[vk]["tag"] == TAG_DATA_EXTENSION_VALUE_SECTION:
                        value_section = vk
                        break
                val = None
                if value_section is not None:
                    voff = sec + dir_[value_section]["rel"] + 4
                    if voff + 4 <= len(buf):
                        val = resolve_textid(strs, struct.unpack_from("<I", buf, voff)[0])
                if key is not None:
                    props[key] = val
        out.append({"index": j, "props": props})
    return out


# --------------------------------------------------------------------------
# Bone directory (already-shipped decode, re-derived independently so this
# probe needs no import from godot-port/).
# --------------------------------------------------------------------------

def bone_nodes(buf, sec, dir_):
    """0xCA5E0506 Bone nodes reached through 0xCA5E0507 SkeletonSection then
    0xCA5E0508 BoneSection, in directory order. Returns a list of
    {'index': j, 'parent': raw_parent, 'parent_effective': normalised}, the
    stored s32 parent index at the start of each 68-byte record, with a
    self-referential parent normalised to -1 (mirrors
    Sacred.Models.bones()'s parent_effective)."""
    bone_section = -1
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_SKELETON_SECTION:
            continue
        # Mirrors Sacred.Models._bone_section(): BoneSection is somewhere in
        # SkeletonSection's declared descendant span (SkeletonSection ->
        # Skeleton -> BoneSection is 2 levels deep on GLADIATOR.GRN), so this
        # searches the whole span, not just direct_children() one level.
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
    for i, k in enumerate(direct_children(dir_, bone_section)):
        if dir_[k]["tag"] != TAG_BONE:
            continue
        off = sec + dir_[k]["rel"]
        if off + 4 > len(buf):
            return []
        parent = struct.unpack_from("<i", buf, off)[0]
        idx = len(out)
        out.append({
            "index": k,
            "parent": parent,
            "parent_effective": -1 if parent == idx else parent,
        })
    return out


# --------------------------------------------------------------------------
# The two-hop bone-name chain's raw ingredients (hop 1 and hop 2's index
# array), returned RAW (both still 1-based) so both the documented chain and
# the deliberately-wrong harness arms can share one reading of the bytes and
# differ only in the arithmetic applied to them.
# --------------------------------------------------------------------------

def transform_channel_refs(buf, sec, dir_):
    """Hop 1's raw ingredient. For every 0xCA5E0B00 TransformChannel node in
    directory order, its FIRST direct child's payload dword if that child is
    a 0xCA5E0F04 DataExtensionReference, else None. Also returns how many of
    each -- a TransformChannel whose first child is something else is a
    structural disagreement with the documentation and is counted, not
    silently skipped."""
    refs = []
    matched = 0
    mismatched = 0
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_TRANSFORM_CHANNEL:
            continue
        kids = direct_children(dir_, j)
        if kids and dir_[kids[0]]["tag"] == TAG_DATA_EXTENSION_REFERENCE:
            refs.append(node_u32(buf, sec, dir_, kids[0]))
            matched += 1
        else:
            refs.append(None)
            mismatched += 1
    return refs, matched, mismatched


def form_bone_channel_raw(buf, sec, dir_, bone_count):
    """Hop 2's raw index array. The 0xCA5E0C02 FormBoneChannels node's
    payload, read as one 1-based TransformChannel index per bone (a flat u32
    array, no header word -- unlike StringTable/DataExtension, this node's
    payload IS its array). Reports the element count; a mismatch against
    bone_count is a structural disagreement and is surfaced, not hidden."""
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_FORM_BONE_CHANNELS:
            continue
        off = sec + dir_[j]["rel"]
        n_bytes = span(dir_, j, len(buf), sec)
        count = n_bytes // 4
        if off + count * 4 > len(buf):
            return [], 0
        return [struct.unpack_from("<I", buf, off + i * 4)[0] for i in range(count)], count
    return [], 0


def form_pose_weights_raw(buf, sec, dir_):
    """FormPoseWeights (0xCA5E0C05) read the SAME way as FormBoneChannels --
    a flat u32 array at the node's own rel. Used only by the `poseweights`
    harness arm, which deliberately misreads this as if it were the hop-2
    index array (the exact misreading `.continue-here.md` inherited from
    Iris1's start/end-bracket reading of 0C02..0C05). NOTE (0C02 vs 0C05,
    272 = 68*4): 272 is the FormBoneChannels array's OWN byte size for a
    68-bone entry, not a span bracketing two tags -- see the module
    docstring and the `poseweights` arm below."""
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_FORM_POSE_WEIGHTS:
            continue
        off = sec + dir_[j]["rel"]
        n_bytes = span(dir_, j, len(buf), sec)
        count = n_bytes // 4
        if off + count * 4 > len(buf):
            return [], 0
        return [struct.unpack_from("<I", buf, off + i * 4)[0] for i in range(count)], count
    return [], 0


# --------------------------------------------------------------------------
# Mesh-skinning census (05-09 gap closure). Structural, name-independent
# ingredients for the new hypothesis under test: a bone that carries real
# skin weight, or is an ancestor of one, is skeletal; nothing here reads a
# name, a string or a DataExtension. Reimplemented from sacred.gd's own
# measured mesh_weights() layout (lines 1569-1708), not transliterated.
# --------------------------------------------------------------------------

def form_mesh_bone_lists(buf, sec, dir_, bone_count):
    """One list per 0xCA5E0C09 FormMeshBoneSection, each entry the u32
    payload of an 0xCA5E0C0A FormMeshBone direct child (mesh-local bone
    index -> file bone index). A value outside 0..bone_count-1 is refused,
    not clamped -- prints a `refuse` line and returns None, mirroring
    sacred.gd::mesh_weights()'s own push_error-and-return-[] behaviour for
    the same condition."""
    out = []
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_FORM_MESH_BONE_SECTION:
            continue
        lst = []
        for k in direct_children(dir_, j):
            if dir_[k]["tag"] != TAG_FORM_MESH_BONE:
                continue
            g = node_u32(buf, sec, dir_, k)
            if g is None or not 0 <= g < bone_count:
                print("refuse\tform_mesh_bone\tvalue=%s\tbound=0..%d" % (g, bone_count - 1))
                return None
            lst.append(g)
        out.append(lst)
    return out


def mesh_weight_influence(buf, sec, dir_, lists):
    """Walks every 0xCA5E0601 Mesh node that also has vertices/normals/
    triangles children (the same accept test sacred.gd's mesh_arrays() and
    mesh_weights() already use, so mesh ordering can't drift), reads its
    0xCA5E0702 MeshWeights child as {count, highest, unknown} then count x
    {influences, influences x (local bone, weight)}, and pairs it to the
    unique FormMeshBone list whose length equals highest+1 -- refusing
    (returns None) rather than choosing when the pairing is not unique, or
    when reading a vertex's declared influence count would run past the
    node's own bytes.

    Returns (per_bone, meshes, slack_max, badsum, badlocal) where per_bone
    maps file-bone-index -> (influence_count, weight_sum), meshes is the
    count of Mesh nodes processed, slack_max is the largest |bytes consumed
    - derived span| seen on any one MeshWeights node, badsum counts vertices
    whose influence weights do not sum to 1.0 within 1e-4, and badlocal
    counts local bone indices seen above a mesh's own declared highest."""
    remaining = [list(lst) for lst in lists]
    per_bone = {}
    meshes = 0
    slack_max = 0
    badsum = 0
    badlocal = 0
    for j in range(len(dir_)):
        if dir_[j]["tag"] != TAG_MESH:
            continue
        if child_with_tag(dir_, j, TAG_MESH_VERTICES) == -1 \
                or child_with_tag(dir_, j, TAG_MESH_NORMALS) == -1 \
                or child_with_tag(dir_, j, TAG_MESH_TRIANGLES) == -1:
            continue
        wj = child_with_tag(dir_, j, TAG_MESH_WEIGHTS)
        if wj == -1:
            print("refuse\tmesh_weights\tnode=%d\treason=no-weights-child" % j)
            return None
        off = sec + dir_[wj]["rel"]
        sp = span(dir_, wj, len(buf), sec)
        if off < 0 or sp < 12 or off + sp > len(buf):
            print("refuse\tmesh_weights\tnode=%d\treason=unusable-span span=%d" % (wj, sp))
            return None
        count, highest = struct.unpack_from("<ii", buf, off)
        if count <= 0 or highest < 0:
            print("refuse\tmesh_weights\tnode=%d\treason=bad-header count=%s highest=%s" % (wj, count, highest))
            return None
        p = off + 12
        end = off + sp
        vertex_influences = []
        for v in range(count):
            if p + 4 > len(buf):
                print("refuse\tmesh_weights\tnode=%d\treason=truncated-past-buffer vertex=%d" % (wj, v))
                return None
            infl = struct.unpack_from("<i", buf, p)[0]
            p += 4
            if infl <= 0 or p + infl * 8 > len(buf):
                print("refuse\tmesh_weights\tnode=%d\treason=bad-influence-count vertex=%d influences=%s" % (wj, v, infl))
                return None
            infl_list = []
            weight_sum_v = 0.0
            for _s in range(infl):
                lb = struct.unpack_from("<i", buf, p)[0]
                w = struct.unpack_from("<f", buf, p + 4)[0]
                p += 8
                weight_sum_v += w
                infl_list.append((lb, w))
            if abs(weight_sum_v - 1.0) > 1e-4:
                badsum += 1
            vertex_influences.append(infl_list)
        slack = end - p
        slack_max = max(slack_max, abs(slack))

        want = highest + 1
        pick = -1
        hits = 0
        for li in range(len(remaining)):
            if len(remaining[li]) == want:
                hits += 1
                pick = li
        if hits != 1:
            print("refuse\tmesh_weights\tnode=%d\treason=ambiguous-pairing want=%d hits=%d" % (j, want, hits))
            return None
        bone_map = remaining.pop(pick)
        meshes += 1

        for infl_list in vertex_influences:
            for lb, w in infl_list:
                if lb < 0 or lb > highest:
                    badlocal += 1
                    continue
                fb = bone_map[lb]
                rec = per_bone.setdefault(fb, [0, 0.0])
                rec[0] += 1
                rec[1] += w
    return per_bone, meshes, slack_max, badsum, badlocal


def skin_census(census):
    """Assembles form_mesh_bone_lists()/mesh_weight_influence() into a
    per-file-bone record for every 0xCA5E0506 Bone record in the entry.
    Computed once in EntryCensus.__init__ (self.skin) alongside the other
    census fields. When the entry has no FormMeshBoneSection at all,
    records lists=0 and every bone in_map=False/influences=0/weight_sum=0.0
    -- `measured` distinguishes that genuine, successfully-measured zero
    from a refusal (which also gates the same way, lists=0, but with
    measured=False), since Task 3's P3-scope gate reads lists==0 either
    way as 'apply no narrowing here'."""
    bone_count = census.bone_count()
    lists = form_mesh_bone_lists(census.buf, census.sec, census.dir, bone_count)
    if lists is None:
        return {"ok": False, "measured": False, "lists": 0, "meshes": 0,
                "slack_max": 0, "badsum": 0, "badlocal": 0,
                "per_bone": {i: {"index": i, "in_map": False, "influences": 0, "weight_sum": 0.0}
                             for i in range(bone_count)}}
    if not lists:
        per_bone = {i: {"index": i, "in_map": False, "influences": 0, "weight_sum": 0.0}
                    for i in range(bone_count)}
        return {"ok": True, "measured": True, "lists": 0, "meshes": 0,
                "slack_max": 0, "badsum": 0, "badlocal": 0, "per_bone": per_bone}
    result = mesh_weight_influence(census.buf, census.sec, census.dir, lists)
    if result is None:
        return {"ok": False, "measured": False, "lists": len(lists), "meshes": 0,
                "slack_max": 0, "badsum": 0, "badlocal": 0,
                "per_bone": {i: {"index": i, "in_map": False, "influences": 0, "weight_sum": 0.0}
                             for i in range(bone_count)}}
    influence_map, meshes, slack_max, badsum, badlocal = result
    in_map_set = set()
    for lst in lists:
        in_map_set.update(lst)
    per_bone = {}
    for i in range(bone_count):
        infl, wsum = influence_map.get(i, (0, 0.0))
        per_bone[i] = {"index": i, "in_map": i in in_map_set, "influences": infl, "weight_sum": wsum}
    return {"ok": True, "measured": True, "lists": len(lists), "meshes": meshes,
            "slack_max": slack_max, "badsum": badsum, "badlocal": badlocal, "per_bone": per_bone}


# --------------------------------------------------------------------------
# Directory census for one entry: everything --entry=N, --harness and
# --report all build on.
# --------------------------------------------------------------------------

class EntryCensus:
    """Holds one entry's directory-derived facts, computed once. Not a
    port of any external reader's class shape -- a plain data holder so
    --harness and --report don't re-walk the directory per arm."""

    def __init__(self, path, entries, file_size, index, quiet=False):
        self.index = index
        self.ok = False
        buf, size, digest, kind = print_entry_report(path, entries, file_size, index) \
            if not quiet else self._silent_entry(path, entries, file_size, index)
        self.buf, self.size, self.md5, self.kind = buf, size, digest, kind
        if buf is None:
            return
        if not magic_ok(buf, kind):
            print(f"refuse\t{index}\treason=magic-check-failed at offset {MAGIC_OFFSET.get(kind, -1)}")
            return
        self.sec = section_offset(kind)
        self.dir = directory(buf, self.sec)
        if not self.dir:
            print(f"refuse\t{index}\treason=empty-or-malformed-directory")
            return
        self.strs = strings(buf, self.sec, self.dir)
        self.extensions = data_extensions(buf, self.sec, self.dir, self.strs)
        self.bones = bone_nodes(buf, self.sec, self.dir)
        self.tc_refs, self.tc_matched, self.tc_mismatched = transform_channel_refs(buf, self.sec, self.dir)
        self.fbc_raw, self.fbc_count = form_bone_channel_raw(buf, self.sec, self.dir, len(self.bones))
        self.pw_raw, self.pw_count = form_pose_weights_raw(buf, self.sec, self.dir)
        self.skin = skin_census(self)
        self.ok = True

    @staticmethod
    def _silent_entry(path, entries, file_size, index):
        if not 0 <= index < len(entries):
            return None, 0, "", -1
        kind, offset, _field3 = entries[index]
        buf, size, digest = entry_bytes(path, entries, file_size, index)
        return buf, size, digest, kind

    def object_name(self, ext_index):
        if not 0 <= ext_index < len(self.extensions):
            return None
        return self.extensions[ext_index]["props"].get(OBJECT_NAME_KEY)

    def bone_count(self):
        return len(self.bones)


# --------------------------------------------------------------------------
# The mesh-skinning classifier (05-09 gap closure). Pure functions of
# census.skin and census.bones only -- no name, no string table, no
# DataExtension. Use A (narrowing which records P3 judges) only; Use B
# (dropping a record from a rig) is never authorised regardless of verdict.
# --------------------------------------------------------------------------

def skinned_set(census):
    """Skinned set S: file bone indices with in_map True and influences > 0
    and weight_sum > 0.0. Pure function of census.skin."""
    out = set()
    for i, rec in census.skin["per_bone"].items():
        if rec["in_map"] and rec["influences"] > 0 and rec["weight_sum"] > 0.0:
            out.add(i)
    return out


def skeletal_set(census):
    """Skeletal set S union A: skinned_set() closed upward over
    parent_effective (every ancestor of every skinned bone), using the same
    seen-set cycle guard _has_ancestor() already uses. Pure function of
    census.skin and census.bones."""
    skinned = skinned_set(census)
    ancestral = set()
    n = len(census.bones)
    for s in skinned:
        seen = set()
        cur = census.bones[s]["parent_effective"]
        while cur != -1 and cur not in seen:
            seen.add(cur)
            ancestral.add(cur)
            if cur < 0 or cur >= n:
                break
            cur = census.bones[cur]["parent_effective"]
    return skinned | ancestral


def resolve_chain(census, bone_i, fbc_array, fbc_minus1, tc_array, ref_minus1, skip_fbc=False, ref_direct=False):
    """One resolution, parameterised so every harness arm shares this single
    implementation and differs only in its arguments -- never a copy-pasted
    variant.

    skip_fbc: hop 1 alone, `bone_i` indexes `tc_array` directly (channel_only).
    ref_direct: hop 2's raw value is used AS a DataExtension index directly,
        skipping the TransformChannel indirection entirely (fbc_only).
    Returns (name, detail-dict) -- detail carries every intermediate value
    for the trace line, even on failure.
    """
    detail = {"fbc_raw": None, "channel": None, "ref_raw": None, "ext": None}
    if ref_direct:
        if not 0 <= bone_i < len(fbc_array):
            return None, detail
        fbc_raw = fbc_array[bone_i]
        detail["fbc_raw"] = fbc_raw
        ext = fbc_raw - 1 if fbc_minus1 else fbc_raw
        detail["ext"] = ext
        return census.object_name(ext), detail

    if skip_fbc:
        channel = bone_i
        detail["channel"] = channel
    else:
        if not 0 <= bone_i < len(fbc_array):
            return None, detail
        fbc_raw = fbc_array[bone_i]
        detail["fbc_raw"] = fbc_raw
        channel = fbc_raw - 1 if fbc_minus1 else fbc_raw
        detail["channel"] = channel

    if not 0 <= channel < len(tc_array):
        return None, detail
    ref_raw = tc_array[channel]
    detail["ref_raw"] = ref_raw
    if ref_raw is None:
        return None, detail
    ext = ref_raw - 1 if ref_minus1 else ref_raw
    detail["ext"] = ext
    return census.object_name(ext), detail


def rotate(arr, k):
    if not arr:
        return arr
    k %= len(arr)
    return arr[k:] + arr[:k]


# --------------------------------------------------------------------------
# The documented chain and the deliberately-wrong arms, defined once here so
# --entry, --harness and --report all resolve bones the same way.
# --------------------------------------------------------------------------

ARMS = ["documented", "no_first_minus1", "no_second_minus1", "no_minus1",
        "channel_only", "fbc_only", "poseweights"]
CONTROL_ARM = "shuffled"


def arm_resolve(arm, census, bone_i):
    fbc = census.fbc_raw
    tc = census.tc_refs
    if arm == "documented":
        return resolve_chain(census, bone_i, fbc, True, tc, True)
    if arm == "no_first_minus1":
        return resolve_chain(census, bone_i, fbc, True, tc, False)
    if arm == "no_second_minus1":
        return resolve_chain(census, bone_i, fbc, False, tc, True)
    if arm == "no_minus1":
        return resolve_chain(census, bone_i, fbc, False, tc, False)
    if arm == "channel_only":
        # Hop 1 ALONE: TC[bone_i].ref - 1, skipping FormBoneChannels entirely.
        # Hop 1's own definition already includes "- 1" (see module docstring),
        # so this arm keeps that -1 and only omits hop 2's indirection -- this
        # is the reading .continue-here.md recorded as reproducing `Omni01`
        # for bone 0 of entry 589 (both raw arrays happen to read 3 at index
        # 0; 3 - 1 = 2, which is Omni01's DataExtension position).
        return resolve_chain(census, bone_i, fbc, True, tc, True, skip_fbc=True)
    if arm == "fbc_only":
        return resolve_chain(census, bone_i, fbc, True, tc, True, ref_direct=True)
    if arm == "poseweights":
        return resolve_chain(census, bone_i, census.pw_raw, True, tc, True)
    if arm == CONTROL_ARM:
        rotated = rotate(fbc, max(1, len(fbc) // 3))
        return resolve_chain(census, bone_i, rotated, True, tc, True)
    raise ValueError(f"unknown arm {arm}")


# --------------------------------------------------------------------------
# --entry=N : directory census + counts + bone-0 trace.
# --------------------------------------------------------------------------

def cmd_entry(index):
    entries, file_size = pak_index(MODELS_PATH)
    census = EntryCensus(MODELS_PATH, entries, file_size, index)
    if not census.ok:
        return 1
    print("counts\tentry=%d\tbones=%d\tchannels=%d\tfbc=%d\textensions=%d\tstrings=%d" % (
        index, census.bone_count(), len(census.tc_refs), census.fbc_count,
        len(census.extensions), len(census.strs)))
    print("structure\tentry=%d\ttransform_channels_with_ref=%d\ttransform_channels_without_ref=%d" % (
        index, census.tc_matched, census.tc_mismatched))
    if census.extensions:
        print("check\tentry=%d\text=0\t__ObjectName=%s" % (index, census.object_name(0)))

    name, detail = arm_resolve("documented", census, 0)
    superseded_name, _ = arm_resolve("channel_only", census, 0)
    print("trace\tentry=%d\tbone=0\tfbc_raw=%s\tchannel=%s\tref_raw=%s\text=%s\tname=%s\tsuperseded_single_array=%s" % (
        index, detail["fbc_raw"], detail["channel"], detail["ref_raw"], detail["ext"], name, superseded_name))
    return 0


# --------------------------------------------------------------------------
# --skincensus=N : mesh-side per-bone influence census, name-independent.
# --------------------------------------------------------------------------

def cmd_skincensus(index):
    entries, file_size = pak_index(MODELS_PATH)
    census = EntryCensus(MODELS_PATH, entries, file_size, index)
    if not census.ok:
        return 1
    skin = census.skin
    bone_count = census.bone_count()
    for i in range(bone_count):
        rec = skin["per_bone"].get(i, {"in_map": False, "influences": 0, "weight_sum": 0.0})
        print("skinbone\tentry=%d\tbone=%d\tin_map=%d\tinfluences=%d\tweight_sum=%.6f" % (
            index, i, 1 if rec["in_map"] else 0, rec["influences"], rec["weight_sum"]))
    in_map_count = sum(1 for r in skin["per_bone"].values() if r["in_map"])
    weighted_count = sum(1 for r in skin["per_bone"].values() if r["influences"] > 0 and r["weight_sum"] > 0.0)
    print("skincensus\tentry=%d\tbones=%d\tmeshes=%d\tfmb_lists=%d\tslack_max=%d\tbadsum=%d\tbadlocal=%d\tin_map=%d\tweighted=%d" % (
        index, bone_count, skin["meshes"], skin["lists"], skin["slack_max"],
        skin["badsum"], skin["badlocal"], in_map_count, weighted_count))
    if not skin["ok"]:
        return 1
    if skin["slack_max"] != 0 or skin["badsum"] != 0 or skin["badlocal"] != 0:
        return 1
    return 0


# --------------------------------------------------------------------------
# --skinclass=N : skinned/ancestral/skeletal partition, the complement, and
# the attachment-point over-rejection check -- all name-independent EXCEPT
# the reporting itself (the `name` field on `complement` lines, and the
# `light_convention` split, are REPORTS downstream of the rule, never an
# input to it; skinned_set()/skeletal_set() above take no name).
# --------------------------------------------------------------------------

def cmd_skinclass(index):
    entries, file_size = pak_index(MODELS_PATH)
    census = EntryCensus(MODELS_PATH, entries, file_size, index)
    if not census.ok:
        return 1

    skinned = skinned_set(census)
    skeletal = skeletal_set(census)
    ancestral = skeletal - skinned
    bone_count = census.bone_count()
    complement = set(range(bone_count)) - skeletal

    print("skinclass\tentry=%d\tbones=%d\tskinned=%d\tancestral=%d\tskeletal=%d\tcomplement=%d" % (
        index, bone_count, len(skinned), len(ancestral), len(skeletal), len(complement)))

    documented_names = {}
    for i in range(bone_count):
        n, _ = arm_resolve("documented", census, i)
        documented_names[i] = n

    children_count = {}
    for b in census.bones:
        p = b["parent_effective"]
        if p != -1:
            children_count[p] = children_count.get(p, 0) + 1

    for i in sorted(complement):
        parent = census.bones[i]["parent_effective"]
        print("complement\tentry=%d\tbone=%d\tparent=%d\tchildren=%d\tname=%s" % (
            index, i, parent, children_count.get(i, 0), documented_names.get(i)))

    light_convention = 0
    other = 0
    for i in sorted(complement):
        if light_convention_hit(documented_names.get(i)):
            light_convention += 1
        else:
            other += 1
    attachment_risk = "yes" if other > 0 else "no"
    print("overreject\tentry=%d\tcomplement=%d\tlight_convention=%d\tother=%d\tattachment_risk=%s" % (
        index, len(complement), light_convention, other, attachment_risk))

    # Attachment-point failure mode, tested up front by string-table `bone_`
    # prefix (case-insensitive) -- independent of the skin-derived sets,
    # named here so a legitimately-zero-skin-weight attachment bone (e.g.
    # Bone_weapon_01) is checked, never discovered after the fact.
    attach_names = [s for s in census.strs if s.lower().startswith("bone_")]
    if not attach_names:
        print("attachpoint\tentry=%d\tnone" % index)
    else:
        for name in attach_names:
            bone_idx = None
            for i in range(bone_count):
                if documented_names.get(i) == name:
                    bone_idx = i
                    break
            if bone_idx is None:
                print("attachpoint\tentry=%d\tname=%s\tbone=unresolved" % (index, name))
                continue
            print("attachpoint\tentry=%d\tname=%s\tbone=%d\tin_skinned=%d\tin_ancestral=%d\tin_complement=%d" % (
                index, name, bone_idx,
                1 if bone_idx in skinned else 0,
                1 if bone_idx in ancestral else 0,
                1 if bone_idx in complement else 0))
    return 0


# --------------------------------------------------------------------------
# Four predicates. A candidate is REFUTED by failing any one.
# --------------------------------------------------------------------------

def predicate_root(census, names):
    root_bones = [i for i, b in enumerate(census.bones) if b["parent_effective"] == -1]
    if not root_bones:
        return "n/a"
    for i in root_bones:
        n = names.get(i)
        if n is None or n.strip().lower() not in ROOT_NAMES:
            return "FAIL"
    return "PASS"


def predicate_finger(census, names):
    applicable = False
    for i, n in names.items():
        if n is None:
            continue
        low = n.strip().lower()
        if low.startswith("bip01 l finger"):
            applicable = True
            if not _has_ancestor(census, names, i, LEFT_HAND):
                return "FAIL"
        elif low.startswith("bip01 r finger"):
            applicable = True
            if not _has_ancestor(census, names, i, RIGHT_HAND):
                return "FAIL"
    return "PASS" if applicable else "n/a"


def _has_ancestor(census, names, bone_i, ancestor_name_lower):
    seen = set()
    cur = census.bones[bone_i]["parent_effective"]
    while cur != -1 and cur not in seen:
        seen.add(cur)
        n = names.get(cur)
        if n is not None and n.strip().lower() == ancestor_name_lower:
            return True
        if cur >= len(census.bones):
            return False
        cur = census.bones[cur]["parent_effective"]
    return False


def predicate_no_light(names, scope):
    """Unchanged condition (the 'omni' prefix test), now iterating only the
    bone indices in `scope` -- 05-09's narrowing changes which records this
    predicate JUDGES, never the condition itself."""
    for i, n in names.items():
        if i not in scope:
            continue
        if n is not None and n.strip().lower().startswith("omni"):
            return "FAIL"
    return "PASS"


def light_convention_hit(name):
    """True iff `name` matches the light-naming convention predicate_no_light()
    tests -- calls that one function (on a single-bone dict/scope) rather
    than duplicating its string match, so the light-name prefix literal
    appears in exactly one place in this file: inside predicate_no_light()
    itself."""
    return predicate_no_light({0: name}, {0}) == "FAIL"


def predicate_no_property_key(names):
    banned = {"__objectname", "__filename", "__description", "__standard"}
    for n in names.values():
        if n is not None and n.strip().lower() in banned:
            return "FAIL"
    return "PASS"


def evaluate_arm(arm, census, invert=False):
    """`invert` is used only by --skincontrol's counterfactual: when true and
    mesh data exists, P3's scope becomes the COMPLEMENT of the narrowing
    instead of the skeletal set, to prove the narrowing is doing
    discriminating work rather than trivially widening P3's PASS rate."""
    names = {}
    resolved = 0
    for i in range(census.bone_count()):
        n, _ = arm_resolve(arm, census, i)
        names[i] = n
        if n is not None:
            resolved += 1
    p1 = predicate_root(census, names)
    p2 = predicate_finger(census, names)
    full_scope = set(range(census.bone_count()))
    if census.skin["lists"] == 0:
        # No FormMeshBoneSection at all (or the mesh census could not be
        # measured) -- same fail-safe rationale as the under-resolution gate
        # below: P3 gets the FULL bone set, unnarrowed, rather than silently
        # narrowing to nothing.
        p3_scope_set = full_scope
        p3_mode = "unnarrowed"
    elif invert:
        p3_scope_set = full_scope - skeletal_set(census)
        p3_mode = "inverted"
    else:
        p3_scope_set = skeletal_set(census)
        p3_mode = "narrowed"
    p3 = predicate_no_light(names, p3_scope_set)
    p4 = predicate_no_property_key(names)
    results = [p1, p2, p3, p4]
    if all(r == "n/a" for r in results):
        verdict = "UNTESTED"
    elif any(r == "FAIL" for r in results):
        verdict = "REFUTED"
    elif resolved < census.bone_count():
        # A candidate that leaves most bones unresolved cannot be confirmed by
        # predicates that only ever inspect the bones it DID resolve -- an
        # arm resolving 1/68 bones and getting lucky on that one is not
        # evidence, it is the row-496 "a check that cannot fail proves
        # nothing" failure mode in a different shape. Every predicate must
        # have had the full bone set to check before a PASS means anything.
        verdict = "REFUTED"
    else:
        verdict = "CONFIRMED"
    return {
        "arm": arm, "P1": p1, "P2": p2, "P3": p3, "P4": p4,
        "resolved": resolved, "total": census.bone_count(),
        "verdict": verdict, "names": names,
        "p3_mode": p3_mode, "p3_scope": len(p3_scope_set),
    }


# --------------------------------------------------------------------------
# --harness : documented + 6 wrong arms + control, on entries 2847 and 589.
# --------------------------------------------------------------------------

HARNESS_ENTRIES = [2847, 589]


def run_harness(quiet=False):
    entries, file_size = pak_index(MODELS_PATH)
    censuses = {}
    for idx in HARNESS_ENTRIES:
        censuses[idx] = EntryCensus(MODELS_PATH, entries, file_size, idx, quiet=quiet)

    per_entry_results = {idx: {} for idx in HARNESS_ENTRIES}
    for idx in HARNESS_ENTRIES:
        census = censuses[idx]
        if not census.ok:
            continue
        for arm in ARMS + [CONTROL_ARM]:
            r = evaluate_arm(arm, census)
            per_entry_results[idx][arm] = r
            print("bonename\tentry=%d\tarm=%s\tP1=%s\tP2=%s\tP3=%s\tP4=%s\tresolved=%d/%d\tverdict=%s\tp3_mode=%s\tp3_scope=%d/%d" % (
                idx, arm, r["P1"], r["P2"], r["P3"], r["P4"], r["resolved"], r["total"], r["verdict"],
                r["p3_mode"], r["p3_scope"], r["total"]))

    documented_confirmed = all(
        per_entry_results[idx].get("documented", {}).get("verdict") == "CONFIRMED"
        for idx in HARNESS_ENTRIES if censuses[idx].ok
    ) and all(censuses[idx].ok for idx in HARNESS_ENTRIES)

    wrong_arms = [a for a in ARMS if a != "documented"]
    wrong_total = 0
    wrong_refuted = 0
    any_wrong_confirmed = False
    for idx in HARNESS_ENTRIES:
        if not censuses[idx].ok:
            continue
        for arm in wrong_arms + [CONTROL_ARM]:
            wrong_total += 1
            v = per_entry_results[idx].get(arm, {}).get("verdict")
            if v == "REFUTED":
                wrong_refuted += 1
            if v == "CONFIRMED":
                any_wrong_confirmed = True

    control_refuted = all(
        per_entry_results[idx].get(CONTROL_ARM, {}).get("verdict") == "REFUTED"
        for idx in HARNESS_ENTRIES if censuses[idx].ok
    ) and all(censuses[idx].ok for idx in HARNESS_ENTRIES)

    if any_wrong_confirmed:
        harness_verdict = "INVALID"
    elif documented_confirmed and wrong_refuted == wrong_total:
        harness_verdict = "CONFIRMED"
    else:
        harness_verdict = "REFUTED"

    print("bonename\tdocumented=%s\twrong_arms_refuted=%d/%d\tcontrol=%s\tharness verdict=%s" % (
        "CONFIRMED" if documented_confirmed else "REFUTED",
        wrong_refuted, wrong_total,
        "REFUTED" if control_refuted else "NOT-REFUTED",
        harness_verdict))

    return censuses, per_entry_results, harness_verdict, documented_confirmed


def cmd_harness():
    _censuses, _results, verdict, documented_confirmed = run_harness()
    return 0 if verdict == "CONFIRMED" else 1


# --------------------------------------------------------------------------
# The full verdict: run_harness()'s mechanical CONFIRMED/REFUTED, PLUS
# the p3_mode gate and the inverted-narrowing counterfactual. Either of
# those failing REFUTES the whole classifier -- there is no partial credit
# ("nearly passes" is REFUTED).
#
# attachment_risk is measured and reported separately (entry_attachment_risk()
# below) but does NOT gate this verdict. Scope resolution (human decision,
# 2026-08-10, recorded in full in findings log row 603):
# over-rejection only matters for Use B (dropping a bone from a rig), which
# is NEVER authorised by this classifier regardless of verdict. For Use A
# (narrowing which bones P3 JUDGES), an over-rejected bone such as
# Bone_weapon_01/02 is inert -- P3 only ever fires on a light-convention
# name, and a weapon-bone name was never going to trip it whether or not P3
# was handed that bone to judge. The executor's first pass folded
# attachment_risk into this verdict directly (a stricter reading than the
# plan's own halt_contract, applied per an explicit dispatch-prompt rule
# that did not distinguish Use A from Use B); the human reviewing that
# result identified the distinction and corrected it. No measured number
# changed between the two passes -- only which measured fact gates the
# overall verdict.
# --------------------------------------------------------------------------

def entry_attachment_risk(census):
    """attachment_risk for one census: 'yes' iff the complement (bones the
    narrowing would exclude from P3's scope) contains any bone whose
    resolved name does NOT match the light convention -- i.e. a legitimate
    zero-skin-weight bone (an attachment point, a mesh-piece root, ...)
    the classifier cannot structurally distinguish from a light helper.
    Only meaningful when the entry carries mesh data (skin lists != 0)."""
    if census.skin["lists"] == 0:
        return "n/a"
    skeletal = skeletal_set(census)
    complement = set(range(census.bone_count())) - skeletal
    for i in complement:
        n, _ = arm_resolve("documented", census, i)
        if not light_convention_hit(n):
            return "yes"
    return "no"


def full_verdict():
    """Every halt-contract condition, checked as a number, folded into one
    overall CONFIRMED/REFUTED, scoped to Use A (narrow which bones P3
    judges) per the plan's own halt_contract. CONFIRMED requires ALL of:
    run_harness()'s own mechanical verdict CONFIRMED (documented arm passes
    both entries, 14/14 wrong arms + control REFUTED); the p3_mode gate held
    correctly (unnarrowed wherever an entry carries no mesh data); and the
    inverted-narrowing counterfactual REFUTES the documented arm on every
    entry that DOES carry mesh data. attachment_risk is measured and
    returned (see entry_attachment_risk()) but does NOT gate this verdict --
    it is inert for Use A (P3 only ever fires on a light-convention name; a
    non-light bone excluded from P3's scope changes no P3 outcome) and
    matters only for Use B (dropping a bone from a rig), which this
    classifier never authorises regardless of verdict. See the module
    docstring's classifier section, and findings log row 603, for the full
    Use A/Use B boundary and the decision that scoped this function."""
    censuses, per_entry_results, harness_verdict, documented_confirmed = run_harness()

    gate_ok = True
    for idx in HARNESS_ENTRIES:
        census = censuses[idx]
        if not census.ok:
            gate_ok = False
            continue
        if census.skin["lists"] == 0:
            r = per_entry_results[idx].get("documented", {})
            if r.get("p3_mode") != "unnarrowed":
                gate_ok = False

    inverse_refutes = True
    inverse_applicable = False
    for idx in HARNESS_ENTRIES:
        census = censuses[idx]
        if not census.ok or census.skin["lists"] == 0:
            continue
        inverse_applicable = True
        r = evaluate_arm("documented", census, invert=True)
        if r["verdict"] != "REFUTED":
            inverse_refutes = False

    attachment_risk = "no"
    for idx in HARNESS_ENTRIES:
        census = censuses[idx]
        if not census.ok:
            continue
        if entry_attachment_risk(census) == "yes":
            attachment_risk = "yes"

    # attachment_risk is measured above and returned/printed below, but does
    # NOT gate `overall` -- see this function's docstring and the module-
    # level comment above entry_attachment_risk() for why it is inert for
    # Use A (the only authorised use) and only matters for Use B (never
    # authorised, gated separately and permanently, not by this verdict).
    overall = (
        harness_verdict == "CONFIRMED"
        and gate_ok
        and (not inverse_applicable or inverse_refutes)
    )
    return {
        "overall": "CONFIRMED" if overall else "REFUTED",
        "harness_verdict": harness_verdict,
        "documented_confirmed": documented_confirmed,
        "gate_ok": gate_ok,
        "inverse_applicable": inverse_applicable,
        "inverse_refutes": inverse_refutes,
        "attachment_risk": attachment_risk,
        "censuses": censuses,
        "per_entry_results": per_entry_results,
    }


def cmd_skincontrol():
    """Re-runs the documented arm with P3's scope INVERTED (the complement
    of the narrowing) on every entry that carries mesh data -- the exact
    inverse of Task 3's narrowing. Under the inverse, the documented arm
    must be REFUTED, or the narrowing is not doing discriminating work.
    Always exits non-zero, following cmd_control()'s convention: exit 0 is
    reserved for --harness alone, in the single fully-CONFIRMED state."""
    entries, file_size = pak_index(MODELS_PATH)
    any_applicable = False
    all_refuted = True
    for idx in HARNESS_ENTRIES:
        census = EntryCensus(MODELS_PATH, entries, file_size, idx)
        if not census.ok or census.skin["lists"] == 0:
            continue
        any_applicable = True
        r = evaluate_arm("documented", census, invert=True)
        print("bonename\tentry=%d\tarm=documented\tP1=%s\tP2=%s\tP3=%s\tP4=%s\tresolved=%d/%d\tverdict=%s\tp3_mode=%s\tp3_scope=%d/%d" % (
            idx, r["P1"], r["P2"], r["P3"], r["P4"], r["resolved"], r["total"], r["verdict"],
            r["p3_mode"], r["p3_scope"], r["total"]))
        if r["verdict"] != "REFUTED":
            all_refuted = False
    if any_applicable and all_refuted:
        print("narrowing\tresult=inverse-refutes-documented")
    else:
        print("narrowing\tverdict=REFUTED\treason=lost-discrimination-inverse-also-confirms")
    return 1


def cmd_control():
    """Runs the control arm alone, outside --harness, so it is independently
    reachable for debugging. Follows the same exit-code convention as
    --harness (0 only on the full CONFIRMED-and-all-wrong-refuted state,
    which this standalone command never checks): it always exits non-zero,
    on both a correctly-REFUTED control (the expected case) and an
    unexpectedly-CONFIRMED one (an even worse case, but still not the
    all-clear state this tool reserves for exit 0)."""
    entries, file_size = pak_index(MODELS_PATH)
    for idx in HARNESS_ENTRIES:
        census = EntryCensus(MODELS_PATH, entries, file_size, idx)
        if not census.ok:
            continue
        r = evaluate_arm(CONTROL_ARM, census)
        print("bonename\tentry=%d\tarm=%s\tP1=%s\tP2=%s\tP3=%s\tP4=%s\tresolved=%d/%d\tverdict=%s" % (
            idx, CONTROL_ARM, r["P1"], r["P2"], r["P3"], r["P4"], r["resolved"], r["total"], r["verdict"]))
    return 1


def cmd_report():
    """Full verdict for 05-04 to act on without re-running anything. Prints
    the harness sweep (unchanged from --harness), the documented chain's
    formula and the authoritative tag names, then either the full bone
    tables (CONFIRMED) or nothing but the failure detail already printed by
    the harness (REFUTED) -- D-19: no bone-to-name table is ever printed
    when the chain is refused, regardless of how close it came."""
    fv = full_verdict()
    censuses, per_entry_results = fv["censuses"], fv["per_entry_results"]
    verdict = fv["overall"]

    print("formula\thop1=TransformChannel[channel].DataExtensionReference.DataExtensionIndex-1")
    print("formula\thop2=channel=FormBoneChannels[bone_i]-1")
    print("formula\tname=DataExtensions[hop1(hop2(bone_i))].__ObjectName resolved through StringTable")
    print("pairing\tTransformChannel's FIRST direct child must be a DataExtensionReference (0xCA5E0F04); "
          "a TransformChannel whose first child is anything else is a structural disagreement, not skipped")
    print("tags\t0xCA5E0B00=TransformChannel\t0xCA5E0C02=FormBoneChannels\t0xCA5E0C05=FormPoseWeights\t"
          "0xCA5E0200=StringTable\t0xCA5E0F00=DataExtension\t0xCA5E0F01=DataExtensionProperty\t"
          "0xCA5E0F02=DataExtensionPropertyValue\t0xCA5E0F04=DataExtensionReference\t"
          "0xCA5E0F05=DataExtensionPropertySection\t0xCA5E0F06=DataExtensionValueSection\t"
          "0xCA5E0505=Skeleton\t0xCA5E0506=Bone\t0xCA5E0507=SkeletonSection\t0xCA5E0508=BoneSection")

    inverse_str = ("REFUTED" if fv["inverse_refutes"] else "CONFIRMED") if fv["inverse_applicable"] else "n/a"
    print("narrowing\trule=unskinned-and-no-skinned-descendant\tverdict=%s\tinverse=%s\tattachment_risk=%s\tauthorised_use=p3-scope-only" % (
        verdict, inverse_str, fv["attachment_risk"]))

    if verdict == "CONFIRMED":
        for idx in HARNESS_ENTRIES:
            census = censuses[idx]
            names = per_entry_results[idx]["documented"]["names"]
            for i in range(census.bone_count()):
                print("bone\t%d\t%d\t%s" % (idx, i, names.get(i)))
        print("bonename\tverdict=CONFIRMED\tarms=%d\tconfirmed=%d" % (len(ARMS) + 1, len(HARNESS_ENTRIES)))
        return 0

    print("bonename\tverdict=REFUTED\tarms=%d\tconfirmed=0" % (len(ARMS) + 1))
    for idx in HARNESS_ENTRIES:
        for arm, r in per_entry_results.get(idx, {}).items():
            if r["verdict"] != "CONFIRMED":
                print("failure\tentry=%d\tarm=%s\tP1=%s\tP2=%s\tP3=%s\tP4=%s\tresolved=%d/%d\tverdict=%s" % (
                    idx, arm, r["P1"], r["P2"], r["P3"], r["P4"], r["resolved"], r["total"], r["verdict"]))
    return 1


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0
    arg = args[0]
    if arg.startswith("--entry="):
        return cmd_entry(int(arg.split("=", 1)[1]))
    if arg.startswith("--skincensus="):
        return cmd_skincensus(int(arg.split("=", 1)[1]))
    if arg.startswith("--skinclass="):
        return cmd_skinclass(int(arg.split("=", 1)[1]))
    if arg == "--harness":
        return cmd_harness()
    if arg == "--control":
        return cmd_control()
    if arg == "--skincontrol":
        return cmd_skincontrol()
    if arg == "--report":
        return cmd_report()
    raise SystemExit(f"unknown argument: {arg}")


if __name__ == "__main__":
    sys.exit(main() or 0)
