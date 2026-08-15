# formats — the parsers

**Status:** Working
**Purpose:** One parser per retail file format: read the bytes, print what was found,
write nothing into the install.

One tool per file format Sacred ships. Each reads bytes and prints what it
found; none of them writes into the install, and none carries game data.

Every parser here was written from direct byte reads, not from another
implementation — that independence is what makes the [parity](../parity/)
gates mean anything. Where two tools in this directory decode the same rule,
they re-derive it separately on purpose.

| Tool | What |
|---|---|
| `pak.py` | Sacred `.pak` reader, both container shapes. |
| `parse_trg.py` | `TRG v1` resource parser (what `Triggers.PAK` actually is). |
| `startcode.py` | `Start/FunkCode.bin` script bytecode parser. |
| `grn_tagwalk.py` | Independent tag walker for Granny 1.x `.GRN` entries in `models.pak`. |
| `grn_bonenames.py` | Bone index → bone name resolution across `.GRN` entries. |
| `grn_motion.py` | `kind=65` motion-entry probe — the animation data. |
| `export_terrain.py` | Export one world region for the Godot terrain viewer. |
| `preview_terrain.py` | Composite exported cells into a PPM — validates the pipeline without Godot. |
| `compare_world_resources.py` | Read-only census and comparison of world trigger/resource archives. |

The formats themselves are documented in
[research/formats/](../../research/formats/).

## Finding the install

The `grn_*` tools and `export_terrain.py` guess the install as
`../../../install` relative to this directory, and take `SACRED_INSTALL` (or
`--game`) when the guess is wrong.

---
Verified by: `parity/` -- each parser is diffed against the GDScript reader in
`engine/formats/`, and agreement is the evidence.
