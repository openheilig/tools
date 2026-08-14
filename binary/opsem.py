#!/usr/bin/env python3
"""Name script opcodes from BEHAVIOUR -- what the shipped scripts do with them.

The static levers are spent: 30 opcodes are named by strings in their handler
(row 723) and the RTTI/vtable lever added a subsystem for only 18 more and
nothing for the other 73 (row 724). This reads the corpus instead. For every
opcode, over all 16 script files:

  * TAG SIGNATURE -- the tag bytes of its operands, in order. Two opcodes with
    the same signature take the same operand shape.
  * OPERAND NAMESPACE -- shipped names are prefixed by kind (res:, cpos:,
    pos_, POOL_, DQ_, Dialog:, TYPE_NPC_, SOUND_, trg_, ...), so the prefix
    histogram says what the operand IS.
  * RESOLVED TEXT -- `res:N` operands index install/scripts/us/global.res, so
    an opcode's actual English strings are readable. A quest-log line and a
    tooltip look nothing alike.
  * CONTEXT -- which opcodes immediately precede and follow it in the stream.

Usage:  opsem.py [--md analysis/script-opcodes-behaviour.md]
"""
import collections
import glob
import re
import struct
import sys

sys.path.insert(0, 'analysis/tools/formats')
import startcode                                             # noqa: E402

RES = 'install/scripts/us/global.res'


def resource_strings():
    """slot -> English text, from global.res.

    Layout, read off the file: u32 'SZ' magic, then 16-byte index entries
    [id, offset, 0, size], then the data. The text is UTF-16LE at offset+4
    (the u32 at `offset` itself is not the size) and runs `size` bytes.
    `res:N` in the scripts is the SLOT INDEX, not the id field -- the id field
    is not even monotonic in the low range and runs past 2^31.
    Checks: slot 49 'Seraphim', 50 'Gladiator', 18101 'Settler',
    19554 'Save... Vilya...'.
    """
    d = open(RES, 'rb').read()
    first, = struct.unpack_from('<I', d, 8)                  # entry 0's offset
    out = []
    for i in range(4, first, 16):
        _id, off, _z, size = struct.unpack_from('<4I', d, i)
        out.append(d[off + 4:off + 4 + size].decode('utf-16-le', 'replace')
                   if off + 4 + size <= len(d) else '')
    return out


# Read off the corpus, NOT off the engine -- these are inferences from what the
# shipped scripts do with each opcode, and every one is falsifiable from the
# table below. Opcodes the engine names outright live in opcodes.py NAMES.
BEHAVIOUR = {
    3: 'say: (res:TEXT, dialogue label) -- 2nd operand is NPC_Dialog_*, '
       'Dlg*, ziel*; res text is sentences',
    20: 'quest-scoped, quest id only (0b <u32>, values like 99/2001)',
    21: 'quest-scoped, quest id only (same shape as 20)',
    22: 'reference by name (monster2002, Audio632) -- one string, nothing else',
    23: 'named position table: (pos_NAME, x, y); 49% of them are followed by '
        'another 23. Median x/y 1762/1753 -- world range -- but some are huge '
        'u32, i.e. NEGATIVE, so at least some pairs are deltas, not absolutes',
    26: 'label / entry point: one 0x1e string, quest-procedure names like '
        'HQ_3_1_4_glad_NPC_Auftrag_Qoffen',
    48: 'declare trigger: (NAME, u16, marker). Followed by a 50 in 31265 of '
        '31265 records -- an exceptionless pairing',
    50: 'trigger payload: (NAME, 12-byte blob) -- runs of them after one 48',
    53: 'quest-log line: (quest id, index, res:*_Log_Title/Header/Qstart)',
    58: 'IF: the TAG BYTE selects the predicate. 0x52/0x7d/0x8f take '
        'TYPE_NPC_*, 0x47 takes quest vars and PoolEmpty, 0x40 takes res: '
        'text, and the NUMSTR tags 0x48/0x49/0x4a/0x6d/0x6e take a '
        '(value, variable name) PAIR -- which is literally the handler\'s own '
        'format string, "if IsNotVarBit:%s=%d"',
    59: 'block marker, no operands; followed by 62 in 87% of records',
    62: 'block marker, no operands; the usual partner of 59',
    66: 'second conditional family -- same tag-selects-predicate shape as 58, '
        'dominated by TYPE_NPC_* operands',
    67: 'set variable: (name, u32); names are quest vars (dq_belohnung, '
        'dq_belohnung_typ, dq_belohnung_level)',
    68: 'set variable: (name, u32); non-quest names (Teleporter_WP, "40")',
    86: 'set variable: (name, u32); dialogue names (MP_Romata_99, ziel2201)',
    100: 'RANDOM-SPAWN SUPPORT: its handler collects every 0x0b operand into '
         'a 10-slot global at 0x8bb7340, resolves the object at the current '
         'sector (globals 0x879a080/0x879a084 << 6) and writes three u16 into '
         'it at +0xd1/+0xd3/+0xd5. Operands are percent-shaped (50, 41, 70)',
    115: 'SPAWN GROUP DECLARATION, 22,762 records: a list of 1..20 creature '
         'ids (tag 0x02) plus three (id, percent) pairs (0x87/0x88/0x89). '
         'ALL 184 distinct ids are creature.pak ids -- 184 of 184. The handler '
         'fills a 160-byte struct and appends it to the table at 0x8bb732c, '
         'which only opcode 51 reads',
    # --- second pass, after the NUMSTR fix (row 726) made the operands
    # trustworthy. Each entry states the SHAPE that was measured; where the
    # semantics are a reading rather than a fact, the wording says so.
    2: 'named world marker + int (HQ_MINE_01_NEBENEINGANG, HELLGATE_DOWN1); '
       'handler touches cObject3D/cObjectFX/cEventFX; always sits between 20 '
       'and 21 records',
    4: 'area with geometry: (trg_/omo_ NAME, two 12-byte fields) -- in 65 '
       'records the same slots hold two pos_ NAMES instead, so the 12-byte '
       'fields are two inline positions',
    5: 'trigger by name only (same trg_/omo_ namespace as 4), 88% one string',
    7: 'place resource at coordinates: (res:N, x, y), x/y in world range; '
       'handler references cItemBase',
    14: 'no operands, 32 records, 78% adjacent to a 22',
    15: 'id only, or empty; SHARES handler 0x8299b8a with 54',
    17: 'magnitude on the hero: (Hero, 10000/5000/1000)',
    18: 'signed magnitude on the hero: (HERO, 3000 and -3000 as u32); '
        'handler names cEvent_engine',
    25: 'small counter; preceded by 58 (IF) in 198 of 198 records, followed '
        'by 22',
    31: 'DQ template chain, step 2: (0, DQ1_BRINGE_NPC) -- the template name',
    32: 'DQ template chain, step 4: (0, 1, 2)',
    33: 'DQ template chain, step 6: (0, n); closes the cycle back to 118',
    35: 'same handler as 51 (0x827afb6, cItemBase); 12-byte fields, sometimes '
        'two pos names (posMascarellSoldatenRG1P1/P2)',
    36: '(hero, -8) x10',
    39: 'bind id to trigger name: (id, trg_/omo_ NAME); runs interleaved with 4',
    40: 'NOT a tag stream: the fixed 80-byte ffffffff struct of row 712, '
        '10,047 records, mostly in runs of itself',
    41: 'operand-less marker; 43 -> 42 -> 41 is a fixed chain',
    42: 'operand-less marker with NO CASE in the dispatcher -- 4,950 records '
        'the engine reads and ignores',
    43: 'operand-less marker; always followed by 42',
    45: '(x, y) coordinate pair, 9 records',
    49: 'trigger by name or id; handler string "Trg", class cObject3D',
    51: 'THE RANDOM SPAWN ROLL, 5,309 records. Tag 0x36 is NOT a type code -- '
        'the handler writes it straight into creature field +0x255 (default '
        '0x12c = 300 when absent), and its two values split the records by '
        'POPULATION: 100 = ambient wildlife (12 ids, all RABBIT/CROW/DEER/'
        'RED_DEER/BAT/COW) and 310 = hostiles (239 ids, SKEL_WARRIOR, '
        'ORC_WARRIOR, WOLF, ZOMBIE, THIEF, DARKELVENPC). CreateNPC passes 350. '
        'Wildlife records carry 1..4 entries and no 0x34/0x33; hostile records '
        'carry exactly 4 entries and always both. Field +0x255 is the '
        'GROUP-ALERT ENABLE: the only code that reads it tests it > 0, in the '
        'sweep that walks a creature\'s group member list (group id at '
        '+0x249) and sends every idle member cEvent_creature(0x100), which '
        'sets state +0xfc to 4/8 and target +0x104. Its magnitude is stored '
        'and serialised but never compared anywhere in the binary. The body is a '
        'repeated 0x19 triple (CREATURE ID, PERCENT, 0/1 flag): all 251 '
        'distinct ids are creature.pak ids, 251 of 251, and the percents sum '
        'to exactly 100 in 3,906 of 5,309 records (median 100). Its handler '
        '(0x827afb6, 23 KB, the largest in the set) calls rand() 44 TIMES and '
        'is the only other user of both globals 0x8bb732c and 0x8bb7340',
    52: '(res:TEXT, small number) applied to the hero',
    54: 'id (2604..); SHARES handler 0x8299b8a with 15',
    55: 'one name: object, res: or effect (obj_UW12_Door, buble210)',
    56: 'timer: (id, kind, TIMER NAME) -- timer_hq_1501, WegIstBaur2',
    57: 'id only (55550, 500202..)',
    69: 'hero quest-bit: (name or id, small value); handler strings are res, '
        'HeroQBit and HERO -- the same three as 68, which shares its shape',
    70: 'one name, hero/HERO/res:; handler strings hero and HERO',
    71: '(res:TEXT, HERO, auftrag2002) -- text plus a quest-task name',
    72: '(res:TEXT, pos_ or cpos:hero) -- text bound to a position; handler '
        'names cEvent_creature and the string HERO',
    73: 'id plus optional extras; handler names cEventFX, string "nix"',
    74: '(id 76131, 12-byte field); cEvent_creature + cEventFX',
    79: '(res:TEXT, small id); handler names cEvent_engine',
    87: 'small int (1, 5); usually preceded by 20 and followed by 53',
    88: 'no operands; handler 0x83b00a6 is shared with 134',
    89: 'no operands; handler names cEvent_engine, string HERO',
    90: '(HERO, small) or (res:, res:, negative u32)',
    93: '(res:TEXT, door name R16NQ02_Tuer_1); cEvent_creature + cObject3D',
    95: 'one label name (dlg_UW12, 11104_ok, Meister_Ende)',
    96: 'u32 LIST behind a 0x69 header: (count, id, id, ...) in runs',
    97: '(x, y, 1) triples; immediately precedes runs of 23 in 3,050 of 3,838',
    99: '(-1, -1, res:TEXT, 0xffffff, 1) -- the 0xffffff is a COLOUR; '
        'handler names cEventFX',
    103: '(res:TEXT, small, magnitude) on the hero',
    106: '(dialogue id, NPC_Dialog_* NAME) in runs of 1,270 -- an id-to-'
         'dialogue-name table',
    107: 'eight small u32, identical in all 10 records',
    111: 'no operands; 990 of 1,044 follow a 22',
    112: 'pool rectangle: (POOL_NAME, x1,y1, x2,y2, x3,y3); always between 113s',
    113: 'pool by name; pairs with 112',
    114: '(0, ~3800) pairs in runs of 9,050 -- a table, not a statement',
    116: 'longer u32 LIST behind the same 0x69 header as 96',
    117: 'small int (30, 31, 22); 80 of 98 are followed by 64 '
         '(QuestkompassOBJ)',
    118: 'DQ template chain, step 1: (n, 1); followed by 31 in 16,830 of '
         '16,830',
    120: 'small int; all 9 followed by 132',
    121: 'autosave/checkpoint name (uw_autosave_01, tag 0x1d); handler names '
         'cEvent_engine',
    122: 'DQ template chain, step 3: (0, 1440) -- 1440 = minutes in a day',
    123: 'DQ template chain, step 5: (0, 1, 2), same shape as 32',
    124: 'small int; preceded by 58 (IF) in 240 of 240 records',
    125: 'three small u32; handler names cEvent_engine',
    126: 'small int (0), 20 records',
    129: 'small int (0/1); 128 of 286 are followed by 127 (SOUND_FX_)',
    131: 'small int; all 27 followed by 58 (IF)',
    132: '(0, res:TEXT); handler names cCommand_armaStop -- the only opcode '
         'the RTTI lever named outright',
    134: 'no operands; shares handler 0x83b00a6 with 88',
    135: '(id, small, ok_/sam1_tot NAME)',
    136: '(id, small, oc_/ot_ NAME)',
    137: '(id, small, 3904) -- same family as 136, which precedes it',
}


NS = re.compile(r'^(res|cres|cpos|pos|CPOS|Res|LRes|POOL|DQ|HQ|MP|TYPE_NPC|'
                r'TYPE_OBJECT|TYPE|SOUND|Dialog|dlg|trg|tr|ou|ok|oc|NPC|Talk|'
                r'UI_WND|ECS|Versteck|versteck|monster|leave|nogo|wegweiser|'
                r'atmo|grvar|Q|DQ1)[_:]', re.A)


def namespace(s):
    m = NS.match(s)
    if m:
        return m.group(1).lower() + ':'
    return '<plain>' if s else '<empty>'


def main():
    res = resource_strings()
    n = collections.Counter()
    tags = collections.defaultdict(collections.Counter)
    ns = collections.defaultdict(collections.Counter)
    texts = collections.defaultdict(list)
    nums = collections.defaultdict(collections.Counter)
    prv = collections.defaultdict(collections.Counter)
    nxt = collections.defaultdict(collections.Counter)
    for f in sorted(glob.glob('install/bin/*/*ode.bin')):
        seq = [(op, args, tg) for _o, op, _l, args, ok, tg
               in startcode.parse(open(f, 'rb').read(), with_tags=True) if ok]
        for i, (op, args, tg) in enumerate(seq):
            n[op] += 1
            tags[op][tg] += 1
            if i:
                prv[op][seq[i - 1][0]] += 1
            if i + 1 < len(seq):
                nxt[op][seq[i + 1][0]] += 1
            for a in args:
                if isinstance(a, str):
                    ns[op][namespace(a)] += 1
                    m = re.match(r'^c?(?:res|Res|LRes):(\d+)$', a, re.I)
                    if m and int(m.group(1)) < len(res):
                        t = res[int(m.group(1))].replace('\n', ' ').strip()
                        if t:
                            texts[op].append(t)
                elif isinstance(a, int):
                    nums[op]['small' if a < 1000 else
                             'id' if a < 100000 else 'big'] += 1
    rows = []
    for op in sorted(n):
        sig, _ = tags[op].most_common(1)[0]
        # `res:N` is NOT one namespace: the same prefix addresses global.res
        # text AND object/creature resources. The length of what it resolves to
        # separates them -- a sentence is displayed text, a short name is a
        # reference. Median length says which kind an opcode takes.
        tt = sorted(texts[op], key=len)
        med = len(tt[len(tt) // 2]) if tt else 0
        rows.append(dict(
            op=op, n=n[op],
            sig=' '.join(f'{t:02x}' for t in sig) or '(none)',
            sigshare=round(tags[op].most_common(1)[0][1] / n[op], 2),
            ns=', '.join(f'{k}x{v}' for k, v in ns[op].most_common(3)),
            nums=', '.join(f'{k}x{v}' for k, v in nums[op].most_common(3)),
            prev=', '.join(str(k) for k, _ in prv[op].most_common(3)),
            next=', '.join(str(k) for k, _ in nxt[op].most_common(3)),
            reslen=med, guess=BEHAVIOUR.get(op, ''),
            text=(tt[-1][:110] if tt else '')))
    if '--md' in sys.argv:
        path = sys.argv[sys.argv.index('--md') + 1]
        with open(path, 'w') as o:
            o.write('# Sacred script opcodes -- behavioural profile\n\n'
                    'Generated by `analysis/tools/binary/opsem.py`. Companion to '
                    '`script-opcodes.md`, which carries the static side '
                    '(handler address, strings, RTTI classes).\n\n'
                    '`tag sig` is the most common operand tag sequence and '
                    'the share of records that use it -- 1.0 means the opcode '
                    'has exactly one shape. `res text` is the English text its '
                    '`res:N` operands resolve to in `global.res`.\n\n'
                    'NINE OPCODES ARE ABSENT HERE ON PURPOSE: 10, 11, 12, 13, '
                    '19, 47, 61, 77 and 110 have live cases in the dispatcher '
                    'but ZERO records in the shipped scripts, so the corpus '
                    'says nothing about them. Opcode 42 is the mirror image -- '
                    '4,950 records, no case.\n\n'
                    'CAVEAT ON `res:`: the same prefix addresses BOTH global.res '
                    'text slots and object/creature resources, so a short or '
                    'nonsensical resolution on a spawn opcode (1, 8) means the '
                    'operand was never text. Median length separates the two.\n\n'
                    'TAGS 0x48/0x49/0x4a/0x5d/0x5e/0x6d/0x6e/0x7a WERE FIXED: '
                    'their handlers (0x0826cb0e, 0x0826de28) store a u32 in '
                    'the numeric slots and THEN strcpy a string, so they carry '
                    'BOTH. They had been typed STR, which ate the u32 as the '
                    'string and parsed the rest of the record from the wrong '
                    'offset. Records consuming their body exactly went from '
                    '95.6% to 99.774% (opcode 40 excluded -- its 80-byte '
                    'struct is not a tag stream).\n\n'
                    '| op | n | reading (inferred from the corpus) | tag sig | share | operand namespaces | numbers | prev | next | res median len | longest res text |\n'
                    '|---|---|---|---|---|---|---|---|---|---|---|\n')
            for r in rows:
                o.write('| {op} | {n} | {guess} | `{sig}` | {sigshare} | {ns} | {nums} '
                        '| {prev} | {next} | {reslen} | {text} |\n'
                        .format(**{k: str(v).replace('|', '/')
                                   for k, v in r.items()}))
    for r in rows:
        print('{op:<4} n={n:<7} sig={sig:<20} {sigshare:<5} rl={reslen:<4} {ns:<40} '
              '{text}'.format(**r)[:200])


if __name__ == '__main__':
    main()
