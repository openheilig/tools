# OpenHeilig — tools

The analysis and extraction tools written for this project: format parsers,
binary-analysis helpers, parity harnesses, and `LD_PRELOAD` shims for driving
the retail game.

All of them operate on a Sacred Gold install you already own. None of them
contain or redistribute game data.

## Running them

These scripts locate the retail install relative to their own path:

```sh
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
```

So they expect to sit at `<workspace>/analysis/tools/`, with the install at
`<workspace>/install/`. Clone this repo there, or symlink it in — running a
script from an arbitrary checkout path will resolve `ROOT` to the wrong place.

## Format parsers

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

## Binary analysis

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

## Live process

| Tool | What |
|---|---|
| `p6_memscan.py` | Live memory scan and patch against the running retail process. |
| `save_patch.py` | Patch the hero position in a save (`game01.pak`). |
| `patch_1002.py` | Re-derive the install **compatibility** patches (GL capability scan, VRAM cache, launcher dialog) for LGP 1.0.02 by anchor search. See the note below. |
| `gdb_run.sh` | Run the game under gdb and sample its stacks. |
| `shortread_watch.sh` | Report every short read out of the engine's save/world stream. |
| `log_timeline.sh` | Launch once and sample the debug log on an interval. |

## Parity harnesses

The project's rule is that a format is understood only when two independently
written decoders agree. These are the gates that enforce it:

| Tool | Gate |
|---|---|
| `verify_ref.py` | Python reference output for the engine's `verify.gd` — the two are diffed byte for byte. |
| `grn_parity.sh` | Cross-check of the two independently written `.GRN` tag walkers. |
| `replay_diff.sh` | The record/replay harness's determinism gate. |
| `follow_parity.sh` | Two pixel gates comparing port output against retail. |
| `swap_walk.sh` | Supported-building interior/exterior swap gate. |
| `loggia_sweep.sh` | The roofed-overhang crossing case. |
| `png_delta.py` | Percentage of pixels differing between two PNGs — the primitive under the pixel gates. |
| `p6_classify.py` | Translation-vs-content verdict for a pair of frames. |
| `p6_cells.py` | Dump region cell classes in world coordinates around a point. |
| `pax_diff.py` | Census one PAX section type across the eight-hero corpus. |
| `race_sweep.sh` | Measure how reliably the game loads a world. ⚠️ This instrument was invalidated four times before being rewritten — read `research/REPORT.md` before trusting a number it produces. |

## Driving the game

`shim/` — 32-bit `LD_PRELOAD` shims built by `shim/build.sh`:

- `autopilot.c` — scripted input, so the game can be driven headlessly and
  reproducibly.
- `xshim.c` — X11 interposition.
- `filetrace.c`, `localetrace.c` — call tracing, used to answer "is this
  mechanism actually used?" by measurement rather than by grep.

Front-ends: `shot.sh` (drive with a script, capture the framebuffer),
`look.sh` (see what either engine is drawing without stealing your display),
`probe_ui.sh` (fire an autopilot script at the menu blind and report back),
`extract_video_frames.py`.

## `granny_oracle/`

C probes that call the **retail Granny 2.x runtime** to ground-truth our own
`.GRN` reader — `granny_probe.c`, `granny_dump_skeleton.c`,
`granny_dump_geometry.c`, plus `grn_extract.py` for identity-verified
extraction of a single `models.pak` entry. This is the oracle the parity
harnesses check against; it needs the runtime from your own install and
distributes nothing.

## Not here

Third-party binaries (Ghidra, innoextract) are **not** in this repo. Compiled
output (`altest`, `sacredtrace.so`) is regenerable and untracked.

## Licence

MIT — see [LICENSE](LICENSE). Covers this source only; it grants no rights in
Sacred or Sacred Gold.

## A deliberate omission in `patch_1002.py`

The LGP Linux build needs two unrelated kinds of patch to run today. This
repository carries only one of them.

**Included — compatibility.** A 2005 binary against modern glvnd, Wayland and
X: the GL extension block, the eighteen capability-check sites that read a
now-NULL `glGetString`, the failure branch that follows, the VRAM cache that
parses an `Xorg.0.log` Wayland does not produce, and the launcher dialog.

**Not included — activation.** The sites that defeat a technological
protection measure are kept outside this repository. Distributing a tool
primarily designed to circumvent such a measure is prohibited in its own
right, separately from copyright — US DMCA §1201(a)(2)/(b)(1), EU InfoSoc
Directive Art. 6(2) — and the interoperability carve-outs do not clearly
reach access-control bypass.

`patch_1002.py` loads those sites from a private module if it is present and
prints `(activation sites not present -- compatibility patches only)` if it is
not. On an already-activated install the compatibility patches alone produce a
working binary.
