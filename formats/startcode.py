#!/usr/bin/env python3
"""Parser for bin/TYPE_NPC_*/{Start,Funk}Code.bin -- the Sacred script bytecode.

Record framing: u16 OPCODE, u16 LENGTH (counting those four bytes), then a
tagged argument list. Confirmed by the engine itself, which reads the length as
`movsx eax, WORD PTR [ebx+0x2]` at 0x0826af24.

THE TAG TABLE BELOW IS DERIVED FROM THE INTERPRETER, NOT FITTED TO THE DATA
(row 720). The interpreter dispatches the tag byte through a 162-entry jump
table at 0x086f3fbc into 52 handlers; each handler's cursor advance was
recovered by FOLLOWING CONTROL FLOW from its entry to the shared epilogue
(analysis/tools/binary/tagwidths.py). Width = advance - 1, the one byte being the tag.

Three rules complete it, and each was worth several failed attempts:
  * 66 tags fall through to the DEFAULT handler at 0x0826e0bc, which is just
    `inc [esi]; jmp epilogue` -- so every unlisted tag below 0xa2 is a
    ZERO-WIDTH marker. Omitting these was what made an earlier engine-derived
    table score WORSE than a fitted one.
  * A tag >= 0xa2 fails the bounds check and exits the record.
  * VARIANT tags read a u32 and, when it is the sentinel 0xfffffffe, take a
    NUL-terminated string instead of their fixed payload.

A fifth class, NUMSTR, was added after the parse-rate metric was found to be
hollow: tags 0x48/0x49/0x4a/0x5d/0x5e/0x6d/0x6e (handler 0x0826cb0e) and 0x7a
(handler 0x0826de28) carry a u32 AND a NUL-terminated string. A CFG walk cannot
see that -- it reports the strcpy and stops -- so they were typed STR, the
u32's own bytes were eaten as the string, and the rest of the record was parsed
from the wrong offset. Nothing failed, because every unlisted tag is a
zero-width no-op, so the garbage was absorbed silently.

The SEVEN SIBLINGS take a SECOND string when their u32 is negative (row 838,
handler disassembled): the sentinel means "the operand is the variable named in
the string that follows", and the engine resolves that name and overwrites the
sentinel with the result. 22 records across all 16 files; before this they
absorbed their tail as garbage -- silently, which is the hollow metric again.

0x7a DOES NOT. Its handler is a separate case with no second-string branch;
what follows the string there is a strncasecmp against "res:" and a base-10
strtol of the remainder -- the `res:N` operand becoming a resource id. The
corpus cannot tell the two tails apart (0 of 2053 0x7a operands carry a
negative u32), so this distinction is read off the interpreter, not fitted.

The honest metric is therefore not "parses" but CONSUMES ITS BODY EXACTLY (or
stops on an END tag). Excluding opcode 40, whose 80-byte ffffffff struct is not
a tag stream at all: 95.6% before NUMSTR, 99.774% after (1,347,105/1,350,157
records over all 16 files).

Usage:  startcode.py <file> [--dump N] [--opcode N]
"""
import sys, struct, collections

STR, END, VARIANT, STR2, NUMSTR = -1, -2, -3, -4, -5
SENTINEL = 0xfffffffe
VARIANT_FIXED = {0x04: 12, 0x0c: 12, 0x0d: 12, 0x3c: 12, 0x37: 1, 0x4b: 1, 0x71: 0}
TAGS = {0x00: END, 0x01: STR, 0x02: 4, 0x03: 2, 0x04: VARIANT, 0x05: STR, 0x09: STR, 0x0a: 2, 0x0b: 4, 0x0c: VARIANT, 0x0d: VARIANT, 0x11: 4, 0x15: 8, 0x16: STR, 0x17: END, 0x18: END, 0x19: 12, 0x1c: 4, 0x1d: 4, 0x1e: STR, 0x1f: 3, 0x20: 12, 0x21: END, 0x22: END, 0x28: 1, 0x29: STR, 0x2a: 12, 0x33: 8, 0x34: 8, 0x35: 12, 0x36: 4, 0x37: VARIANT, 0x38: 4, 0x3a: STR2, 0x3b: 4, 0x3c: VARIANT, 0x3d: 16, 0x3e: STR, 0x40: STR, 0x41: STR, 0x47: STR, 0x48: NUMSTR, 0x49: NUMSTR, 0x4a: NUMSTR, 0x4b: VARIANT, 0x4d: 12, 0x52: STR, 0x53: 4, 0x54: 4, 0x55: 4, 0x56: 4, 0x57: 4, 0x5d: NUMSTR, 0x5e: NUMSTR, 0x5f: 4, 0x60: STR, 0x63: STR, 0x67: STR, 0x68: STR, 0x69: STR, 0x6a: STR, 0x6b: 2, 0x6c: 2, 0x6d: NUMSTR, 0x6e: NUMSTR, 0x6f: STR, 0x71: VARIANT, 0x73: 4, 0x75: 4, 0x76: END, 0x77: STR, 0x79: 8, 0x7a: NUMSTR, 0x7d: STR, 0x7e: 4, 0x7f: 4, 0x81: STR, 0x82: STR, 0x83: STR, 0x84: 4, 0x86: 4, 0x87: 8, 0x88: 8, 0x89: 8, 0x8b: 1, 0x8c: 4, 0x8f: STR, 0x90: 4, 0x92: STR, 0x93: 2, 0x94: END, 0x95: STR, 0x9b: 2, 0x9c: 2, 0x9d: STR, 0x9f: 3}


def width(tag):
    """Engine width for a tag: unlisted tags below 0xa2 hit the default
    handler and are zero-width markers."""
    if tag >= 0xa2:
        return END
    return TAGS.get(tag, 0)


def parse(buf, with_tags=False):
    """Yield (offset, opcode, length, args, ok) for every record.

    with_tags appends a sixth element: the tag byte each arg came from, which
    is what lets a caller read a record's SHAPE rather than just its values."""
    off, n = 0, len(buf)
    while off + 4 <= n:
        opcode, length = struct.unpack_from('<HH', buf, off)
        if length < 4 or off + length > n:
            yield (off, opcode, length, [], False) + ((),) * with_tags
            return
        body, p, args, ok = buf[off + 4:off + length], 0, [], True
        tg = []
        while p < len(body):
            tag = body[p]
            p += 1
            w = width(tag)
            if w == END:
                break
            if w == NUMSTR:
                # The handler at 0x0826cb0e reads a u32 into the NUMERIC slot
                # array (+0xa86c) and THEN strcpys a NUL-terminated string into
                # the string slots (+0xa46c). Read as a bare string -- which is
                # what a CFG walk reports, because the strcpy is the only thing
                # it can see -- the u32's own bytes get eaten as the string, and
                # the rest of the record is then parsed from the wrong offset.
                if p + 4 > len(body):
                    break
                args.append(int.from_bytes(body[p:p + 4], 'little'))
                tg.append(tag)
                p += 4
                end = body.find(b'\0', p)
                if end < 0:
                    break        # runs past the record: the engine reads on
                tg.append(tag)
                args.append(body[p:end].decode('latin-1'))
                p = end + 1
                # A SECOND string follows, behind two gates the handler applies
                # in this order (row 838): the u32 just stored must be NEGATIVE
                # -- `cmp DWORD PTR [slot],0 / jns epilogue` at 0x0826cb96 --
                # and the byte after the first string must be non-zero, at
                # 0x0826cba4. That second string is a '+'-joined variable
                # expression: the handler strstrs it for '+', resolves the name
                # against the symbol vector at +0x7550, and writes the RESULT
                # back over the sentinel in the SAME numeric slot. So a negative
                # u32 here is not a value, it is "the operand is the variable
                # named below". 22 records across all 16 files.
                # ...but NOT for 0x7a. Its handler 0x0826de28 is a separate
                # case and its tail is a different thing entirely: it
                # strncasecmps the string it just wrote against "res:"
                # (0x086f3d65, 4 chars) and, on a match, copies the remainder
                # and strtol's it base 10 -- this is where a `res:N` operand
                # becomes a resource id. There is no second-string branch in it
                # at all. The corpus cannot see the difference (0 of 2053 0x7a
                # operands carry a negative u32 against the siblings' 22), so
                # this gate is read off the interpreter, not fitted.
                if tag != 0x7a and args[-2] & 0x80000000 and p < len(body) and body[p]:
                    end = body.find(b'\0', p)
                    if end < 0:
                        break    # runs past the record: the engine reads on
                    tg.append(tag)
                    args.append(body[p:end].decode('latin-1'))
                    p = end + 1
            elif w in (STR, STR2):
                # STR2: the handler calls strcpy TWICE, so two NUL-terminated
                # strings follow with no tag byte between them (e.g. 0x3a,
                # "HERO" then "res:17562").
                for _ in range(1 if w == STR else 2):
                    end = body.find(b'\0', p)
                    if end < 0:
                        ok = False
                        break
                    tg.append(tag)
                    args.append(body[p:end].decode('latin-1'))
                    p = end + 1
                if not ok:
                    break
            elif w == VARIANT:
                fixed = VARIANT_FIXED[tag]
                if p + 4 <= len(body) and int.from_bytes(body[p:p + 4], 'little') == SENTINEL:
                    p += 4
                    end = body.find(b'\0', p)
                    if end < 0:
                        ok = False
                        break
                    tg.append(tag)
                    args.append(body[p:end].decode('latin-1'))
                    p = end + 1
                elif p + fixed <= len(body):
                    tg.append(tag)
                    args.append(int.from_bytes(body[p:p + fixed], 'little'))
                    p += fixed
                else:
                    break          # overruns: same tolerance as above
            else:
                if p + w > len(body):
                    break          # payload overruns: engine reads on, loop ends
                tg.append(tag)
                args.append(int.from_bytes(body[p:p + w], 'little') if w else None)
                p += w
        yield (off, opcode, length, args, ok) + ((tuple(tg),) if with_tags else ())
        off += length


def main():
    path = sys.argv[1]
    dump = int(sys.argv[sys.argv.index('--dump') + 1]) if '--dump' in sys.argv else 0
    want = int(sys.argv[sys.argv.index('--opcode') + 1]) if '--opcode' in sys.argv else None
    buf = open(path, 'rb').read()
    ops = collections.Counter()
    total = bad = shown = 0
    for off, opcode, length, args, ok in parse(buf):
        total += 1
        if not ok:
            bad += 1
            continue
        ops[opcode] += 1
        if dump and shown < dump and (want is None or opcode == want):
            print(f"  0x{off:06x} op={opcode:<5} len={length:<4} {args}")
            shown += 1
    print(f"{path}: {total} records, {bad} unparsed, {len(ops)} opcodes")
    for opcode, c in ops.most_common(10):
        print(f"  op {opcode:<6} x{c}")


if __name__ == '__main__':
    main()
