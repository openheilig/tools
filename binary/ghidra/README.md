# ghidra — headless decompilation of the LGP Linux binary

**Status:** Working
**Purpose:** Reach the pre-analysed Ghidra project from the shell, so a handler
can be read as C instead of guessed at from control flow.

The sibling tools in `../` recover structure the linker could not strip. These
read the *code* — Ghidra's decompiler, its function boundaries, and its
resolved computed jumps — against the same binaries.

The project lives at `analysis/ghidra/` (`sacred-re`) and holds two programs:

| Program | Binary | Use |
|---|---|---|
| `sacred_orig` | `install/sacred_orig` | **the citation standard** — every address in `research/` is this one |
| `sacred-1.0.02-final` | `analysis/lgp-2010/sacred-1.0.02-final` | a second build, for cross-checking a finding |

Read `../README.md` § *Which binary* before you copy an address anywhere. The
two are the same source and their `.text` layouts differ; there is no
mechanical translation between them.

## Running

```sh
analysis/tools/binary/ghidra/run.sh sacred_orig Dis.java 0x0826de28 48
cat /tmp/gh/out.txt
```

Every script writes `/tmp/gh/out.txt` unless it takes an output path.

| Script | What |
|---|---|
| `Decomp.java <addr>...` | Decompiled C for the function containing each address. |
| `Dis.java <addr> <n>` | `n` instructions from `addr`, annotated with referenced strings and symbol names. |
| `Tbl.java <addr> <n>` | `n` little-endian `u32`s — for reading a jump table by hand. |
| `Str.java <addr>...` | The NUL-terminated string at each address. |
| `Impl2.java <table> <n> <depth> <maxcallers> <out>` | For each entry of a jump table, the single function its trampoline calls, and every string reachable from it within `depth` calls — skipping any callee with more than `maxcallers` callers, which is what keeps a shared utility from drowning the signal. |
| `ImportNames.java <tsv>` | Apply an `addr/name/class/slot` TSV to the program. Never overwrites a name that is not `FUN_*`. |
| `CheckNames.java <tsv>` | Dry run for the above: how many addresses are exact function entries. **Run this before `ImportNames`** — a TSV from the wrong binary scores near zero and says so. |
| `vmeth.py <binary> [out]` | Emit that TSV from `../vtables.py`, for whichever binary you name. |
| `FindStr.java <substring>` | Defined strings containing a substring, each with its xrefs and the function they sit in. The usual way in to an unknown subsystem. |
| `Info.java <addr>...` | What is at an address: memory block, containing function, and everything that references it. |
| `Sw.java <func>...` | Every computed jump in a function, with its resolved targets -- finds a switch's real table when a document disagrees. |
| `BalanceMap.java <addr-in-parser> <out>` | Walk the balance key parser and emit `key -> destination global`. |
| `LabelGlobals.java <balmap.tsv>` | Label those globals `bal_<Key>`, so decompiled arithmetic reads with the tunables' names in it. |
| `Consumers.java <balmap.tsv> <out> <parser-addr>` | For each global, the functions that read it, and the inverse index -- which function reads the most keys. That inverse index is what identifies a formula. |

## Seeding a program with names

A fresh program has almost nothing named, which makes decompiled output
unreadable. `vtables.py` already knows 2000-odd virtual methods by class and
slot:

```sh
python3 analysis/tools/binary/ghidra/vmeth.py install/sacred_orig /tmp/vm.tsv
analysis/tools/binary/ghidra/run.sh sacred_orig CheckNames.java /tmp/vm.tsv
analysis/tools/binary/ghidra/run.sh sacred_orig ImportNames.java /tmp/vm.tsv
```

`CheckNames` on `sacred_orig` reports 2186 of 2189 addresses landing exactly on
function entries Ghidra found by itself, from `.eh_frame` and flow. The vtable
walk and the disassembler agree without having consulted each other, which is
the only reason the import is trustworthy. The same TSV scores 29 of 2413
against the wrong binary — that is the check working.

`vmeth.py` is deliberately conservative: it drops any address more than one
class claims, so it emits fewer rows than `analysis/rtti/lgp_linux_vmethods.tsv`
and is not a reproduction of it. It is a readability aid, not a finding.

## The balance bridge

`FindStr` -> `BalanceMap` -> `Consumers` is the chain that turned the balance
table into a map of the combat code, and it generalises: any subsystem
configured by a named key table can be entered the same way. See
[research/engine/combat-formulas.md](../../../research/engine/combat-formulas.md)
for what it produced and
[research/formats/generated/balance-globals.tsv](../../../research/formats/generated/balance-globals.tsv)
for the table.

The check on `BalanceMap`'s output is not an assertion, it is arithmetic: every
key must satisfy `global = 0x08b8d29c + its balance.bin file offset` against
`balance_keymap.py`'s independently recovered offsets. A single mis-associated
key breaks the constant. 343 of 343 shared keys hold it.

---
Verified by: `CheckNames.java` against the binary a TSV was generated from, and
against one it was not -- see `research/method/naming-oracle.md`.
