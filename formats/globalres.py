#!/usr/bin/env python3
"""Reader for scripts/<lang>/global.res -- the engine's whole text resource tree.

The file is one container read TWO ways, and conflating them is the trap:

  BY SLOT.  `res:N` in the script bytecode is the SLOT INDEX, the N'th 16-byte
  index entry. This is what opcodes' res: operands mean.

  BY NAME.  Everything in the engine reaches the same tree through a HASH of a
  resource's NAME, which is the entry's first u32. Callers holding a number
  print it to decimal first, so resource 9400 is the entry whose name hashes
  like the four characters "9400" -- 'Heavenly Magic'.

The hash is `FUN_080ae4d2`, verbatim:

    h = 0
    for c in name: h = (h*0x71 + toupper(c)) % 0x3b9ac9f7
    return h & 0x7fffffff

0x3b9ac9f7 is 999999991, prime. **The modulus is unverified by the data**: it
is read off the disassembly, but `h` only exceeds it at five characters or
more, no non-numeric name in the shipped `global.res` resolves at all, and no
numeric id above 9999 does either -- so nothing in the file ever wraps.
Changing it does not break the self-check below. That is a property of the
corpus, not a hole in the check; changing the MULTIPLIER does break it.

The mask is why callers can pass a NEGATIVE id
(`FUN_084c2e06`): a value with the sign bit set is an ALREADY-HASHED key and is
used directly after `& 0x7fffffff`, while a non-negative one is a number to be
stringified and hashed. That is the two namespaces, in one branch.

The tree itself is loaded at startup by `main` (0x0809af0d), which sprintfs
".\\SCRIPTS\\%s\\global.res" with the language and hands it to 0x080ae09e.
`FUN_084c2d6c` builds its wrapper with the literal ".\\SCRIPTS\\RESOURCE.PAK",
but retail ships no such file -- it is an Armalion-era container that retail
dropped, and the wrapper reads the tree main already loaded. See
research/formats/global-res.md.

Layout, read off the file: u32 'SZ' magic, then 16-byte index entries
[name_hash, offset, 0, size], then the data. Text is UTF-16LE at offset+4 (the
u32 at `offset` is not the size) and runs `size` bytes.

Checks (run by `globalres.py` with no arguments, not merely asserted here):
slot 0 'Seraphim', slot 1 'Gladiator', slot 18101 'Settler', by_id(9400)
'Heavenly Magic', by_id(1100) 'Attack Speed', and a negative id resolving to
the same entry as its positive form.

Usage:  globalres.py <id>...            resolve numeric resource ids
        globalres.py --slot <n>...      resolve slot indices
        globalres.py --hash <name>...   print the hash of a name
"""
import struct
import sys

DEFAULT = 'install/scripts/us/global.res'
MOD = 0x3b9ac9f7


def name_hash(name):
    """FUN_080ae4d2: the key every by-name lookup in the engine uses."""
    h = 0
    for c in name:
        h = (h * 0x71 + ord(c.upper())) % MOD
    return h & 0x7fffffff


def load(path=DEFAULT):
    """-> (slots, by_hash). slots[i] is the i'th entry's text, for res:N."""
    d = open(path, 'rb').read()
    if d[:2] != b'SZ':
        raise ValueError(f'{path}: not a global.res ({d[:4]!r})')
    first, = struct.unpack_from('<I', d, 8)          # entry 0's data offset
    slots, by_hash = [], {}
    for i in range(4, first, 16):
        h, off, _z, size = struct.unpack_from('<4I', d, i)
        t = (d[off + 4:off + 4 + size].decode('utf-16-le', 'replace')
             if off + 4 + size <= len(d) else '')
        slots.append(t)
        by_hash.setdefault(h, t)                     # first wins, as the tree does
    return slots, by_hash


def by_id(rid, by_hash):
    """Resolve a numeric resource id the way the engine does."""
    if rid < 0:
        return by_hash.get(rid & 0x7fffffff)
    return by_hash.get(name_hash(str(rid)))


def _demo():
    slots, by_hash = load()
    assert slots[0] == 'Seraphim', slots[0]
    assert slots[1] == 'Gladiator', slots[1]
    assert slots[18101] == 'Settler', slots[18101]
    assert by_id(9400, by_hash) == 'Heavenly Magic'
    assert by_id(1100, by_hash) == 'Attack Speed'
    # the mask is not decorative: a NEGATIVE id is a key that is already
    # hashed, and must resolve to the same entry without being hashed again
    k = name_hash('9400')
    assert by_id(k - (1 << 31), by_hash) == 'Heavenly Magic'
    assert by_id(9400, by_hash) != by_id(9401, by_hash)
    print('globalres: self-check ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        _demo()
    elif a[0] == '--hash':
        for n in a[1:]:
            print(f'{n} -> {name_hash(n)}')
    elif a[0] == '--slot':
        s, _ = load()
        for n in a[1:]:
            print(f'slot {n}: {s[int(n, 0)]!r}')
    else:
        _, bh = load()
        for n in a:
            i = int(n, 0)
            print(f'{i} (0x{i & 0xffffffff:x}): {by_id(i, bh)!r}')
