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

Two of these are deliberately redundant: `opcodes.py` names an opcode from the
handler it dispatches to, `opsem.py` names it from what the shipped scripts do
with it. Agreement between them is the evidence; a disagreement is a finding.
Naming rules are in
[research/method/naming-oracle.md](../../research/method/naming-oracle.md).

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
