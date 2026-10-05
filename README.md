# OpenHeilig — tools

**Purpose:** The programs this project runs against a Sacred Gold install:
parsers, binary-analysis helpers, parity gates, harnesses and shims.

The analysis and extraction tools written for this project: format parsers,
binary-analysis helpers, parity harnesses, and `LD_PRELOAD` shims for driving
the retail game.

All of them operate on a Sacred Gold install you already own. None of them
contain or redistribute game data.

Public development tools, not a bundled retail runtime or a completed 1:1
verification system. Portable explicit-input readers coexist with historical
private-corpus scripts. See the
[tooling audit](https://github.com/openheilig/engine/blob/main/docs/tooling.md)
and [0.0.1 contract](https://github.com/openheilig/engine/blob/main/docs/milestone-0.0.1.md)
for supported entrypoints and proof limits. Capture/patch/profiling drivers can
launch, terminate or mutate local processes/files; read their headers first.

## Start here

| I want to… | Read |
|---|---|
| read a `.pak`, a save, or the script bytecode | [formats/](formats/) |
| pull something out of a stripped binary | [binary/](binary/) |
| watch, patch or trace the running game | [live/](live/) |
| prove a decoder is right | [parity/](parity/) |
| play the game headlessly and capture it | [drive/](drive/) |
| interpose on the retail process | [shim/](shim/) |
| ground-truth `.GRN` against the retail runtime | [granny_oracle/](granny_oracle/) — **blocked**, read its README first |

Nothing here forms a verdict on its own. What the tools *found* is written up
in [research](https://github.com/openheilig/research); the rule that decides when a finding counts is
[research/method/discipline.md](https://github.com/openheilig/research/blob/main/method/discipline.md).

Every directory README opens with a **Status** and a **Purpose** line and ends
with the gate that keeps it honest — the same shape the research repo uses,
described in [research/README.md](https://github.com/openheilig/research). A tools README says
what its programs do and how to run them; the *investigation* a tool was built
for belongs in research, not here.

## Layout

```
formats/         one parser per file format the game ships
binary/          static recovery from the stripped binaries: vtables, functions, opcodes
live/            the running process, and the machine it runs on
parity/          the gates: two independent decoders must agree
drive/           front-ends that play the game and capture what it drew
shim/            32-bit LD_PRELOAD interposers
granny_oracle/   C probes that call the retail Granny 2.x runtime
```

## Running them from a fresh clone — read this first

Some scripts honor these variables; they are not universal overrides:

```sh
export SACRED_INSTALL=/path/to/your/sacred/install
export SACRED_PORT=/path/to/the/engine/checkout   # only the tools that drive it
```

**Correction, 2026-10-05:** the earlier promise that these two variables made
every fresh-clone script work was false. Several drivers still call through
the private `analysis/tools` layout; binary/corpus helpers can retain fixed
workspace paths. The engine itself uses `--install=PATH`, then remembered
configuration, not `SACRED_INSTALL`. Check both the entrypoint and its invoked
helpers before running a tool outside the private workspace.

Start with explicit-input readers such as `formats/pak.py`,
`formats/startcode.py`, `formats/parse_trg.py`, `binary/vtables.py`,
`binary/ehframe_funcs.py` and `binary/xrefs.py`; read each usage/header and
supply your own files. Do not copy our private install, launcher, captures or
databases to make a corpus-specific recipe run.

The retail capture chain still includes hardcoded `/tmp` paths inside the C
shim, shared-output cleanup and process termination. Setting `TMPDIR` alone
does not isolate it. Those legacy recipes are experimental, not a safe
read-only health check or a standalone 0.0.1 acceptance gate.

`parity/start_scene_gate.sh` is a world-only regression ratchet that can
update its baseline. It is not zero-difference retail equality and does not
gate the HUD. Independent decoder checks, simulation replay and actual
visible/audio/player-route acceptance remain separate proof channels.

## Not here

Third-party binaries (Ghidra, innoextract) are **not** in this repo. Compiled
output (`live/altest`, `shim/*.so`) is regenerable and untracked.

## Related

This is one of three repositories:

- [engine](https://github.com/openheilig/engine) — the reimplementation: an open Sacred Gold engine on
  Godot 4.7 that reads your own retail install.
- [research](https://github.com/openheilig/research) — what the formats are, and how each finding was
  established.

## Licence

MIT — see [LICENSE](LICENSE). Covers this source only; it grants no rights in
Sacred or Sacred Gold.

## A deliberate omission in `live/patch_1002.py`

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

`live/patch_1002.py` loads those sites from a private module if it is present
and prints `(activation sites not present -- compatibility patches only)` if it
is not. On an already-activated install the compatibility patches alone produce
a working binary.
