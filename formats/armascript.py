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
FUNCTION: a 32-byte NUL-padded name, a `u32` code length IN WORDS, then that
many words of code.

The header is PROVEN here, not read off a hex dump: `entries()` asserts
`payload_bytes == 4 * codelen` for all 59 entries, and that identity holds at
NAMELEN 32 and at no other value (24, 28, 36 and 40 all score 0/59). The same
number is what the debug build prints as `sid[N] func[...] size[N]` in
DEBUG.LOG.

CODE. The code is a flat `u32` stream.

  * `0xff` introduces a CALL and the next word is the script API id -- the same
    id space as `research/builds/armalion-script-api.tsv`.
  * `33 0 0 0 <cond> <target>` is a six-word BRANCH. `target` is a word index
    into the same function (the function length means "jump to the end").
    `cond` is 16 to jump when the test was false -- a plain `if (x)` -- and 17
    to jump when it was true -- `if (!x)`. Nothing else was seen in this
    container.
  * Inline strings are NUL-terminated and PADDED TO A WORD, so the `u32` walk
    stays in phase across them. A call carrying one emits its argument count
    first, then the scalar arguments in source order, then the string last:
    `item_createOnPatch ("TYPE_FX_MAGICMARKER",4022,6173,0)` is
    `ff 26 | 4 | 4022 6173 0 | "TYPE_FX_MAGICMARKER\0\0"`. A call with no
    string emits its arguments flat with no count word:
    `trigger_setState(1,2)` is `ff 39 01 02`.

Remaining words are the VM's own operations -- the `asm mov`/`movi`/`rsp` the
source writes inline, and whatever `33`'s three zero operands select. This
reader does not decode those and does not pretend to.

THERE IS NO COMPILER PREAMBLE. An earlier version of this tool reported that
every function opens with one call no source line asks for, "usually id 77".
That was an artefact of counting only source names already present in the API
table: the table has gaps, so a real leading call to an untabled name looked
like an unexplained extra. Counting every call in the source removes it, and
the comparison is now EQUALITY rather than a suffix.

WHAT THE CHECKS PIN. Mutating the `0xff` marker, the word size, the id base or
NAMELEN each scramble the result immediately. 58 of the 59 functions match
their source call-for-call -- the exception is `invalid_function`, the
interpreter's own error stub, which has no source.

script03.txt IS EXCLUDED. It redefines `init`, `spTrigger40` and `spTrigger41`
with different bodies, and DEBUG.LOG shows the engine compiled SCRIPT00,
SCRIPT01, SCRIPT02 and SCRIPT04 only. Including it makes those three functions
appear to disagree with a bytecode that was never compiled from them.

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
BRANCH = 33
JMP_IF_FALSE, JMP_IF_TRUE = 16, 17
# The engine's own compile list, from the prerelease's DEBUG.LOG. script03.txt
# is on disk but was not compiled; see the docstring.
COMPILED = ('script00.txt', 'script01.txt', 'script02.txt', 'script04.txt')
# Words that take a parenthesis but are not engine calls.
KEYWORDS = {'if', 'else', 'while', 'for', 'switch', 'return', 'asm', 'sizeof'}

# Ratchets. Never lower these; a drop means the decoding regressed.
MIN_CALLS = 58    # functions matching their source call-for-call
MIN_BRANCH = 57   # functions whose branch condition codes match the source


def api_names(path=API):
    """-> {id: name} from the table recovered from the Armalion binary."""
    out = {}
    for line in open(path, encoding='utf-8').read().split('\n')[1:]:
        f = line.split('\t')
        if len(f) > 1 and f[0].isdigit():
            out[int(f[0])] = f[1]
    return out


def entries(path):
    """-> (ver, [(name, code_words)]). Same blob layout pak.py reads.

    Asserts the header: the u32 after the 32-byte name is the code length in
    words, and it must account for the payload exactly.
    """
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
        nwords = struct.unpack_from('<I', blob, NAMELEN)[0]
        if size - NAMELEN - 4 != 4 * nwords:
            raise ValueError(
                f'{path}: {name}: payload {size - NAMELEN - 4} bytes is not '
                f'4 * {nwords} words -- the header layout is wrong')
        out.append((name, struct.unpack_from(f'<{nwords}I', blob, NAMELEN + 4)))
    return ver, out


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


def branches(words):
    """-> [(pos, cond, target)] for each six-word `33 0 0 0 cond target`."""
    return [(i, words[i + 4], words[i + 5])
            for i in range(len(words) - 5)
            if words[i] == BRANCH and words[i + 1:i + 4] == (0, 0, 0)]


def source_functions(text):
    """-> {func: ([call_name], [negated])} in source order.

    Every identifier applied to a parenthesis counts as a call, not only the
    ones the recovered API table already knows -- the table has gaps, and
    filtering by it is what invented the phantom compiler preamble. `negated`
    records one bool per `if`, True when the condition opens with `!`.
    """
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    out, cur = {}, None
    for line in text.split('\n'):
        m = re.match(r'^([A-Za-z_]\w*)\s*\(\s*\)\s*$', line.strip())
        if m:
            cur = m.group(1)
            out.setdefault(cur, ([], []))
            continue
        if cur is None:
            continue
        for c in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', line):
            if c.group(1) not in KEYWORDS:
                out[cur][0].append(c.group(1))
        for c in re.finditer(r'\bif\s*\(\s*(!?)', line):
            out[cur][1].append(c.group(1) == '!')
    return out


def main(pak, srcdir):
    names = api_names()
    ver, ents = entries(pak)
    src = {}
    for f in COMPILED:
        p = os.path.join(srcdir, f)
        if os.path.exists(p):
            src.update(source_functions(open(p, encoding='latin-1').read()))

    ok = bad = nosrc = 0
    pin = {}
    for name, words in ents:
        want = src.get(name)
        if want is None:
            nosrc += 1
            continue
        got = calls(words)
        if len(got) != len(want[0]):
            bad += 1
            print(f'  MISMATCH {name}: {len(got)} calls in bytecode, '
                  f'{len(want[0])} in source')
            continue
        # Case-insensitively: the source writes `dialogMgr_Reset` where the
        # table, recovered from the binary's own strings, holds
        # `dialogMgr_reset`. It still compiled to id 10, so the compiler's
        # name lookup ignores case. Reported below, not failed on.
        wrong = [(i, b) for i, b in zip(got, want[0])
                 if i in names and names[i].lower() != b.lower()]
        if wrong:
            bad += 1
            print(f'  MISMATCH {name}: id {wrong[0][0]} is '
                  f'{names[wrong[0][0]]} in the table, {wrong[0][1]} in source')
            continue
        ok += 1
        for i, b in zip(got, want[0]):
            pin.setdefault(i, set()).add(b)

    # Branch condition codes against the source's own `!`.
    bok = bbad = bskip = 0
    for name, words in ents:
        want = src.get(name)
        if want is None:
            continue
        got = [c for _p, c, _t in branches(words)]
        if len(got) != len(want[1]):
            bskip += 1
            continue
        pred = [JMP_IF_TRUE if neg else JMP_IF_FALSE for neg in want[1]]
        if got == pred:
            bok += 1
        else:
            bbad += 1
            print(f'  BRANCH {name}: {got} but source predicts {pred}')

    # Branch targets must land inside the function.
    stray = [(n, t) for n, w in ents for _p, _c, t in branches(w) if t > len(w)]

    ambiguous = {i: sorted(v) for i, v in pin.items() if len(v) > 1}
    solid = {i: sorted(v)[0] for i, v in sorted(pin.items()) if len(v) == 1}
    agree = {i: b for i, b in solid.items()
             if i in names and names[i].lower() == b.lower()}
    new = {i: b for i, b in solid.items() if i not in names}
    clash = {i: (names[i], b) for i, b in solid.items()
             if i in names and names[i] != b}

    print(f'  {len(solid)} ids pinned to exactly one name; '
          f'{len(agree)} agree with the recovered table')
    print(f'  {len(new)} ids the table lacks: '
          + ', '.join(f'{i}={b}' for i, b in sorted(new.items())))
    if clash:
        print(f'  {len(clash)} differ from the table in case only '
              f'(the compiler matched them anyway): '
              + ', '.join(f'{i}: table {a!r} vs source {b!r}'
                          for i, (a, b) in sorted(clash.items())))
    if ambiguous:
        print(f'  FAIL an id maps to two names: {ambiguous}')
    if stray:
        print(f'  FAIL branch target outside its function: {stray[:4]}')

    print(f'armascript: ACS v{ver}, {len(ents)} functions; '
          f'{ok} match their source call-for-call, {bad} do not, '
          f'{nosrc} have no source; branch condition codes match in {bok} '
          f'functions, disagree in {bbad}, {bskip} not comparable')
    fail = False
    if ok < MIN_CALLS:
        print(f'  FAIL only {ok} functions align, floor is {MIN_CALLS}')
        fail = True
    if bok < MIN_BRANCH:
        print(f'  FAIL only {bok} branch sets align, floor is {MIN_BRANCH}')
        fail = True
    return 1 if fail or ambiguous or stray else 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
