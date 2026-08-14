#!/usr/bin/env python3
"""Port the install/ modernization patches from LGP sacred 1.0.01 to 1.0.02.

The 2010 rebuild is a full relink (92% of bytes differ), so nothing could be
applied at a fixed offset.  Every site below was re-located in the 1.0.02
binary by anchor search and cross-verified against the 1.0.01 original:

  1 launcher-dialog skip   by `mov edx,1; mov eax,[X]; cmp byte [eax+0x1e],0`
  2 GL extension block     by the GL_EXT_texture_filter_anisotropic string
  3 18 cap-check sites     by `ff 35 <extptr>`, 18 in each binary, 1:1
  4 nulled GL-fail branch  by `mov edx,[X]; xor eax,eax; test edx,edx; jne`
  5 VRAM cache init        by the /var/log/Xorg.0.log parser function

This file carries the COMPATIBILITY patches only -- the ones that make a 2005
binary run on a modern Linux/Wayland/glvnd system. Sites that defeat a
technological protection measure are deliberately NOT here; they live outside
this repository and are loaded at run time if present. Without them this
script still produces a correct binary for an already-activated install.

Patches are read off the 1.0.01 pair (install/sacred_orig vs the preserved
install/sacred.1.0.01) and re-applied to the 1.0.02 binary; the result is
written next to its source and copied into install/ by hand.

Usage: python3 analysis/tools/patch_1002.py          # -> sacred-1.0.02-patched
       python3 analysis/tools/patch_1002.py --check  # re-derive, verify, no write
"""
import re
import struct
import sys
from pathlib import Path

# absolute(), not resolve(): this file is reached through a symlink from the
# workspace, and resolving it would land ROOT outside the workspace entirely.
ROOT = Path(__file__).absolute().parents[2]
SRC = ROOT / "analysis/lgp-2010/sacred-1.0.02-final"
REF_ORIG = ROOT / "install/sacred_orig"        # pristine 1.0.01
REF_PATCHED = ROOT / "install/sacred.1.0.01"   # patched 1.0.01 (was live pre-2026-08-06)
OUT = ROOT / "analysis/lgp-2010/sacred-1.0.02-patched"

TEXT_BASE = 0x8048000    # vaddr - file offset for .text/.rodata
DATA_BASE = 0x8049000    # vaddr - file offset for .data

GL_ANCHOR = b"GL_EXT_texture_filter_anisotropic"
GL_BLOCK_END = b"GL_NV_register_combiners\x00"


def die(msg):
    sys.exit(f"patch_1002: {msg}")


def only(matches, what):
    """Require exactly one match; anything else means the anchor went stale."""
    m = list(matches)
    if len(m) != 1:
        die(f"{what}: expected 1 match, got {len(m)}")
    return m[0]


def find_all(buf, pat):
    out, i = [], 0
    while True:
        i = buf.find(pat, i)
        if i < 0:
            return out
        out.append(i)
        i += 1


def gl_block(buf):
    """(start, end) file offsets of the GL extension token block."""
    s = only(find_all(buf, GL_ANCHOR), "GL block anchor")
    e = buf.find(GL_BLOCK_END, s)
    if e < 0:
        die("GL block end not found")
    return s, e + len(GL_BLOCK_END)






def launcher_jne(buf):
    """File offset of the jne gating the 'Launch Sacred' options dialog."""
    pat = rb"\xba\x01\x00\x00\x00\xa1....\x80\x78\x1e\x00\x0f\x85"
    return only([m.start() for m in re.finditer(pat, buf)], "launcher gate") + 14


def glfail_jne(buf):
    """File offset of the jne taken when the GL capability scan fails."""
    pat = rb"\x83\xc4\x10\x8b\x15....\x31\xc0\x85\xd2\x0f\x85....\x8d\x65\xf4\x5b\x5e\x5f\xc9\xc3"
    return only([m.start() for m in re.finditer(pat, buf)], "GL fail branch") + 13




def vram_slot(buf):
    """File offset of the .data VRAM cache, from the Xorg.0.log parser."""
    s = buf.find(b"/var/log/Xorg.0.log")
    if s < 0:
        die("Xorg.0.log string not found")
    push = only(find_all(buf, b"\x68" + struct.pack("<I", s + TEXT_BASE)),
                "Xorg.0.log push")
    # ... immediately preceded by `mov dword [slot], 0` zeroing the cache.
    if buf[push - 15:push - 13] != b"\xc7\x05":
        die("VRAM: expected `mov dword [slot],0` before the fopen path")
    return struct.unpack("<I", buf[push - 13:push - 9])[0] - DATA_BASE


def ext_refs(buf, blk_start, blk_end):
    """The 18 `push [extensions_ptr]` capability-check sites."""
    # Identify the pointer from the inline checks, which are unambiguous:
    # each is `push <token in the block>; push [extensions_ptr]; call strstr`.
    # (A second, unrelated one-arg wrapper shares the thunk prologue, so the
    # prologue alone is not enough to tell the two globals apart.)
    ptrs = set()
    for i in find_all(buf, b"\xff\x35"):
        if buf[i - 5] != 0x68:
            continue
        tok = struct.unpack("<I", buf[i - 4:i])[0]
        if blk_start + TEXT_BASE <= tok < blk_end + TEXT_BASE:
            ptrs.add(struct.unpack("<I", buf[i + 2:i + 6])[0])
    if len(ptrs) != 1:
        die(f"GL cap sites: expected 1 extensions pointer, got {len(ptrs)}")
    return sorted(find_all(buf, b"\xff\x35" + struct.pack("<I", ptrs.pop())))


def main():
    for p in (SRC, REF_ORIG, REF_PATCHED):
        if not p.exists():
            die(f"missing {p}")
    old = REF_ORIG.read_bytes()
    old_patched = REF_PATCHED.read_bytes()
    buf = bytearray(SRC.read_bytes())

    # Sanity: the reference pair must be the 1.0.01 original and its patched
    # twin, or the "known good" bytes we copy below are not what we think.
    if len(old) != len(old_patched):
        die("reference 1.0.01 pair differs in size")

    ob_s, ob_e = gl_block(old)
    nb_s, nb_e = gl_block(buf)
    if old[ob_s:ob_e] != bytes(buf[nb_s:nb_e]):
        die("GL block content differs between 1.0.01 and 1.0.02")
    patched_block = old_patched[ob_s:ob_e]
    if patched_block == old[ob_s:ob_e]:
        die("reference GL block is unpatched -- wrong install/sacred?")

    old_sites = ext_refs(old, ob_s, ob_e)
    new_sites = ext_refs(buf, nb_s, nb_e)
    if len(old_sites) != len(new_sites):
        die(f"GL cap sites: {len(old_sites)} in 1.0.01 vs {len(new_sites)} in 1.0.02")

    edits = []

    # Activation-bypass sites, if the private module is present beside the
    # workspace. Absent in a public checkout, and that is the intent.
    try:
        sys.path.insert(0, str(ROOT / "analysis/private"))
        import patch_1002_activation as _act
        _act._bind(die, only, find_all)
        edits.extend(_act.edits(buf))
    except ImportError:
        print("  (activation sites not present -- compatibility patches only)")



    # 3. "Launch Sacred" gtk dialog: jne -> jmp
    lj = launcher_jne(buf)
    rel = struct.unpack("<i", buf[lj + 2:lj + 6])[0]
    edits.append(("launcher skip", lj, bytes(buf[lj:lj + 6]),
                  b"\xe9" + struct.pack("<i", rel + 1) + b"\x90"))

    # 4. Merge the GL extension tokens into one fake glGetString result
    edits.append(("GL extension block", nb_s, bytes(buf[nb_s:nb_e]), patched_block))

    # 5. Point every capability check at that fake string instead of the
    #    (NULL on modern glvnd) real one:  push [ptr] -> push <block>; nop
    push_block = b"\x68" + struct.pack("<I", nb_s + TEXT_BASE) + b"\x90"
    for i, site in enumerate(new_sites):
        edits.append((f"GL cap site {i}", site, bytes(buf[site:site + 6]), push_block))

    # 6. Drop the branch taken when the capability scan reports failure
    gj = glfail_jne(buf)
    edits.append(("GL fail branch", gj, bytes(buf[gj:gj + 6]), b"\x90" * 6))

    # 7. VRAM cache: -1 (redetect, parses a log Wayland does not have) -> 256 MB
    vs = vram_slot(buf)
    if bytes(buf[vs:vs + 4]) != b"\xff\xff\xff\xff":
        die(f"VRAM slot at 0x{vs:x} is not -1")
    edits.append(("VRAM cache init", vs, b"\xff\xff\xff\xff",
                  struct.pack("<I", 262144)))


    for name, off, want, new in edits:
        if bytes(buf[off:off + len(want)]) != want:
            die(f"{name}: unexpected bytes at 0x{off:x}")
        if len(new) != len(want):
            die(f"{name}: length change")
        buf[off:off + len(new)] = new
        print(f"  {name:22s} 0x{off:07x}  {want.hex()[:24]:>26s} -> {new.hex()[:24]}")

    if "--check" in sys.argv:
        print("check only, not writing")
        return
    OUT.write_bytes(bytes(buf))
    OUT.chmod(0o755)
    print(f"wrote {OUT} ({len(buf)} bytes, {len(edits)} edits)")


if __name__ == "__main__":
    main()
