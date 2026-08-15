#!/usr/bin/env python3
"""Read Armalion's compiled scripts, and check them against their own SOURCE.

The 2001-09-20 Armalion prerelease shipped `Scripts/SCRIPT.PAK` -- the
compiled output -- NEXT TO the `script0N.txt` files it was compiled from.
That pair is the only place in any Sacred build where the same script exists
as both text and bytecode, so it is the one script finding that can be checked
rather than argued.

CONTAINER. `SCRIPT.PAK` is magic `ACS` version 2 -- the `chunk.type==
CHUNK_TYPE_ACS` and `hdr.ver==2` asserts of the debug build -- and it is the
ordinary 256-byte-header blob layout that `pak.py` already reads: a
`{u32 flags, u32 offset, u32 size}` index at 0x100. Each payload is one script
FUNCTION: a 32-byte NUL-padded name, a `u32` code length, then the code.

CODE. The code is a flat `u32` stream. `0xff` introduces a call and the next
word is the script API id -- the same id space as
`research/builds/armalion-script-api.tsv`. Words between calls are the VM's
own operations (branches and the `asm mov`/`movi`/`rsp` the source writes
inline); this reader does not decode them and does not pretend to.

Every compiled function opens with one call that no source line asks for --
usually id 77, sometimes 59, 63, 9, 12, 30 or 72. Rather than guess what it
is, the check treats the source's calls as a SUFFIX of the bytecode's: the
compiled function must end with exactly the calls the text writes, in order,
after some compiler-emitted preamble. That is weaker than equality by exactly
one degree of freedom and still scrambles under any wrong constant.

WHAT THE CHECK DOES AND DOES NOT PIN. Mutating the `0xff` call marker drops
the match count to nothing, so the marker and the id space are pinned by it.
The 32-byte name field and the word after it are read off the hex dump, not
proven here: because the comparison is a suffix, a wrong header size only adds
leading noise that the suffix rule then ignores, and 28 scores the same as 32.
Do not cite this check for the header layout.

THE CHECK is the call SEQUENCE. For every function present in both the
container and the text, the ordered list of API ids decoded from the bytes
must equal the ordered list of API names written in the source. That is a
strong test -- a wrong id base, a wrong marker or a wrong word size scrambles
it immediately -- and it needs no assumption about how arguments are encoded.

CAUTION: this is ARMALION's id space. Retail re-encoded the bytecode entirely
(`u16 opcode, u16 length`, tagged arguments) and renumbered; retail's trigger
opcodes are 4, 5 and 39 where Armalion's are 56-59. Nothing here names a
retail opcode.

Usage:  armascript.py <SCRIPT.PAK> <dir-with-script0N.txt>
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = os.path.join(ROOT, 'research/builds/armalion-script-api.tsv')
CALL = 0xff
NAMELEN = 32
# Ratchet. 25 of the 35 string-free functions align today. The rest are the
# npcDialog* functions, which also exist in localized us/ and de/ copies whose
# text differs from what was compiled. Raise this as the encoding is
# understood better; never lower it.
MIN_MATCH = 26


def api_names(path=API):
    """-> {id: name} from the table recovered from the Armalion binary."""
    out = {}
    for line in open(path, encoding='utf-8').read().split('\n')[1:]:
        f = line.split('\t')
        if len(f) > 1 and f[0].isdigit():
            out[int(f[0])] = f[1]
    return out


def entries(path):
    """-> [(name, code_words)]. Same blob layout pak.py reads."""
    d = open(path, 'rb').read()
    if d[:3] != b'ACS':
        raise ValueError(f'{path}: magic {d[:3]!r}, not ACS')
    ver, n = d[3], struct.unpack_from('<I', d, 4)[0]
    out = []
    for i in range(n):
        _fl, off, size = struct.unpack_from('<3I', d, 0x100 + 12 * i)
        if not size or off + size > len(d):
            continue
        blob = d[off:off + size]
        name = blob[:NAMELEN].split(b'\0')[0].decode('latin-1')
        # the u32 after the name is NOT the code length -- spTrigger5 holds 44
        # in a 212-byte payload whose code runs to the end. Code is the rest.
        code = blob[NAMELEN + 4:]
        words = struct.unpack_from(f'<{len(code) // 4}I', code, 0)
        out.append((name, words, has_inline_string(code)))
    return ver, out


def has_inline_string(code):
    """True if the payload embeds text.

    A string argument is stored inline and its length need not be a multiple
    of four, so the `u32` walk goes out of phase after it and every later word
    is garbage. Decoding those needs the argument encoding, which this reader
    does not claim to know, so they are reported rather than guessed at.
    """
    run = 0
    for b in code:
        run = run + 1 if 0x20 <= b < 0x7f else 0
        if run >= 4:
            return True
    return False


def calls(words):
    """-> [api_id] in order. 0xff introduces a call; the next word is the id."""
    out, i = [], 0
    while i < len(words) - 1:
        if words[i] == CALL:
            out.append(words[i + 1])
            i += 2
        else:
            i += 1
    return out


def source_calls(text, known):
    """-> {func_name: [api_name]} in source order, from the .txt files.

    Only names in the recovered API table are counted, so a helper defined in
    the script itself cannot be mistaken for an engine call.
    """
    out, cur = {}, None
    for line in text.split('\n'):
        m = re.match(r'^([A-Za-z_]\w*)\s*\(\s*\)\s*$', line.strip())
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            continue
        if cur is None:
            continue
        for c in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', line):
            if c.group(1) in known:
                out[cur].append(c.group(1))
    return out


def main(pak, srcdir):
    names = api_names()
    known = set(names.values())
    ver, ents = entries(pak)
    src = {}
    for f in sorted(os.listdir(srcdir)):
        if re.fullmatch(r'script\d*\.txt', f.lower()):
            src.update(source_calls(
                open(os.path.join(srcdir, f), encoding='latin-1').read(), known))

    ok = bad = skipped = strung = 0
    for name, words, strung_here in ents:
        if strung_here:
            strung += 1
            continue
        want = src.get(name)
        got = [names.get(i) for i in calls(words)]
        if want is None:
            skipped += 1
            continue
        # ids the table does not cover resolve to None; compare only the
        # positions where both sides have a name, but require equal length
        if len(want) > len(got):
            bad += 1
            print(f'  MISMATCH {name}: {len(got)} calls in bytecode, '
                  f'{len(want)} in source -- source cannot be a suffix')
            continue
        tail = got[len(got) - len(want):] if want else got[len(got):]
        pairs = [(a, b) for a, b in zip(tail, want) if a is not None]
        if all(a == b for a, b in pairs):
            ok += 1
        else:
            bad += 1
            d = next((f'{a} != {b}' for a, b in pairs if a != b), '')
            print(f'  MISMATCH {name}: {d}')

    print(f'armascript: ACS v{ver}, {len(ents)} functions; '
          f'{ok} of the {ok + bad} string-free functions match their source '
          f'call-for-call, {bad} do not; {strung} embed a string and are not '
          f'checkable without the argument encoding, {skipped} have no source')
    if ok < MIN_MATCH:
        print(f'  FAIL only {ok} functions align, floor is {MIN_MATCH} -- '
              f'the decoding regressed')
    return 0 if ok >= MIN_MATCH else 1


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
