# OpenHeilig — tools

The analysis and extraction tools written for this project: format parsers,
binary-analysis helpers, parity harnesses, and `LD_PRELOAD` shims for driving
the retail game.

All of them operate on a Sacred Gold install you already own. None of them
contain or redistribute game data.

## Start here

| I want to… | Read |
|---|---|
| read a `.pak`, a save, or the script bytecode | [formats/](formats/) |
| pull something out of a stripped binary | [binary/](binary/) |
| watch, patch or trace the running game | [live/](live/) |
| prove a decoder is right | [parity/](parity/) |
| play the game headlessly and capture it | [drive/](drive/) |
| interpose on the retail process | [shim/](shim/) |
| ground-truth `.GRN` against the retail runtime | [granny_oracle/](granny_oracle/) |

Nothing here forms a verdict on its own. What the tools *found* is written up
in [research](../research); the rule that decides when a finding counts is
[research/method/discipline.md](../research/method/discipline.md).

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

## Running them

These scripts locate the retail install relative to their own path:

```sh
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
```

So they expect to sit at `<workspace>/analysis/tools/<group>/`, with the
install at `<workspace>/install/`. Clone this repo at
`<workspace>/analysis/tools`, or symlink it in — running a script from an
arbitrary checkout path will resolve `ROOT` to the wrong place.

Two escape hatches, for when it is checked out somewhere else: `SACRED_INSTALL`
and `SACRED_PORT` override the guess in the Python tools that take one.

## Not here

Third-party binaries (Ghidra, innoextract) are **not** in this repo. Compiled
output (`live/altest`, `shim/*.so`) is regenerable and untracked.

## Related

This is one of three repositories:

- [engine](../engine) — the reimplementation: an open Sacred Gold engine on
  Godot 4.7 that reads your own retail install.
- [research](../research) — what the formats are, and how each finding was
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
