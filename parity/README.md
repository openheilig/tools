# parity — the gates

**Status:** Working
**Purpose:** Return a verdict a human did not choose: two independent decoders agree, or
they do not.

The project's rule is that a format is understood only when two independently
written decoders agree, and that a port behaves correctly only when its output
matches retail pixel for pixel. Nothing here forms an opinion; each tool
returns a verdict that a human did not choose.

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
| `race_sweep.sh` | Measure how reliably the game loads a world. |

⚠️ `race_sweep.sh` was invalidated four times before being rewritten. Read
[research/method/discipline.md](../../research/method/discipline.md) before
trusting a number it produces — the failure mode was the instrument, not the
engine.


| Harness | Verdict | Has its own control |
|---|---|---|
| `verify_parity.sh` | exit 0/1 | yes — fails if the walkable sample degrades to the zero-region sectors |
| `grn_parity.sh` | exit 0/1 | the name digest, added when truncating every name still passed |
| `replay_diff.sh` | exit 0/1 | yes, and the best of them — a perturbation must change the outcome at the exact injected tick, and a missing recording must fail loudly |
| `race_sweep.sh` | prints, no exit code | no — its metric has been invalidated four times; never compare a new sweep to an old table |

Every harness here has been mutation-tested: a deliberate change to one side
must make it say FAIL. A parity gate that cannot detect a difference is worse
than no gate, because it is quoted as evidence.

## Running them

```sh
sh analysis/tools/parity/grn_parity.sh          # ~1 min, verdict=PASS/FAIL
sh analysis/tools/parity/replay_diff.sh
```

`verify_ref.py` imports `grn_tagwalk` and `grn_bonenames` from
[`../formats/`](../formats/), and carries a second hand-written walker of its
own besides. The header comment in that file says which half is which; the
independence claim rests on the corpus cross-check, not on the import graph.

---
Verified by: Itself -- this directory is what everything else is verified by.
