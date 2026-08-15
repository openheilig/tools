# binary — static recovery

**Status:** Working
**Purpose:** Recover structure the linker could not strip: unwind tables, vtables,
relocations, opcode tables.

The shipped binaries are stripped: no symbols, no debug info. These tools
recover structure from what the linker could not remove — exception-unwind
tables, vtable layout, relocations, and the strings the code itself passes to
its handlers.

| Tool | What |
|---|---|
| `vtables.py` | Recover C++ vtables and the class hierarchy from the stripped LGP Linux binary. |
| `ehframe_funcs.py` | Recover function boundaries from `.eh_frame` in that same stripped binary. |
| `xrefs.py` | Every `call`/`jmp rel32` in `.text` targeting a given address. |
| `opcodes.py` | Map script opcodes to their engine handlers, and name them from handler strings. |
| `opsem.py` | Name opcodes from *behaviour* instead — what the shipped scripts do with them. |
| `tagwidths.py` | Derive script tag widths by following control flow in the interpreter. |
| `balance_keymap.py` | Recover the `balance.bin` field map from `Sacred.exe`. |
| `eiphist.py` | Resolve the autopilot EIP sampler's output against the same run's memory maps. |
| [`ghidra/`](ghidra/) | Headless decompilation of the same binaries: read a handler as C, dump a jump table, seed a program with the vtable names. |

Two of these are deliberately redundant: `opcodes.py` names an opcode from the
handler it dispatches to, `opsem.py` names it from what the shipped scripts do
with it. Agreement between them is the evidence; a disagreement is a finding.
Naming rules are in
[research/method/naming-oracle.md](../../research/method/naming-oracle.md).

## Which binary — read this before trusting an address

There are **three** LGP Linux binaries in this workspace and they are *not*
interchangeable. Every address in `research/` is meaningless without knowing
which one it came from.

| File | md5 prefix | Used by |
|---|---|---|
| `install/sacred_orig` | `1e888a38` | `opcodes.py`, `tagwidths.py`, **and every address in `research/`** |
| `install/sacred` = `lgp-2010/sacred-1.0.02-patched` | `a1230334` | `vtables.py`'s default argument |
| `lgp-2010/sacred-1.0.02-final` | `952920ab` | the Ghidra project `sacred-re` |

`sacred_orig`'s `.rodata` sits exactly **`0x6ca0` higher** than the other two,
so a `.rodata` address transplanted between them lands on plausible-looking
data and fails silently -- `0x086f4298` is the opcode jump table in
`sacred_orig` and 88 sane-looking entries of nothing in the other two.
`.text` is **not** a uniform shift, so there is no mechanical translation at
all: the same handler is `0x0826de28` in `sacred_orig` and `0x0826cf35` in
`-final`.

`analysis/rtti/lgp_linux_vmethods.tsv` carries no binary in its name and is for
`install/sacred`: 2413 of 2413 of its addresses are exact function entries
there and 29 of 2413 are in `sacred_orig`. **`sacred_orig` is the citation
standard.** Verify a finding there before writing it down, whatever tool found
it.

## Running them

They are cwd-relative: run from the workspace root, where `install/` is
visible.

```sh
python3 analysis/tools/binary/vtables.py install/sacred
python3 analysis/tools/binary/ehframe_funcs.py install/sacred 0x8210b91
```

`opcodes.py` shells out to `ehframe_funcs.py` beside it and imports
`startcode.py` from [`../formats/`](../formats/).

---
Verified by: Its output is checked against a second binary before any claim is made --
see `research/method/naming-oracle.md`.
