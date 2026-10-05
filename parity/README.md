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
| `png_delta.py` | Percentage of pixels differing between two PNGs — the primitive under the pixel gates. `--mae` adds the mean absolute error beside it. |
| `start_scene_gate.sh` | **The milestone metric, with a verdict.** Drives a pair, measures world/taskbar/full, and ratchets against `start-scene-baseline.tsv`. The **world** band decides; the taskbar is reported, not gated. |
| `p6_classify.py` | Translation-vs-content verdict for a pair of frames. |
| `p6_cells.py` | Dump region cell classes in world coordinates around a point. |
| `pax_diff.py` | Census one PAX section type across the eight-hero corpus. |
| `race_sweep.sh` | Measure how reliably the game loads a world. |
| `sheet_match.py` | Which UI sheet rect a block of a retail frame came from. Not a gate — an identification tool, for interface art the gfx table does not lead to. Read the score bands and the three ways it answers confidently and WRONG before trusting it. |
| `static_next_check.py` | Pins `nextStaticId` at `static.pak` `+0x1f` by structure — a linked list has no record targeted twice, and a linked record is never a cell head. Runs against the Armalion prerelease too, whose `Static.PAK` is the same `OBJ v1` record. |

⚠️ `race_sweep.sh` was invalidated four times before being rewritten. Read
[research/method/discipline.md](https://github.com/openheilig/research/blob/main/method/discipline.md) before
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

## `log_check.py` — the findings log's own shape

`CLAUDE.md` states the four-field row contract and calls it "checked rather
than trusted". Nothing checked it, and 539 of its 853 rows did not have four
fields. `log_check.py` is that check. It began as a ratchet around those rows;
they have since been normalised into the contract without losing a character,
so the pin is gone and every row is enforced from the first.

One thing the normalisation could not recover: 492 rows never carried a date,
and the repo's first commit imported the whole log at once, so `git blame`
dates every legacy line to the import. Their dates are inferred from the
nearest dated row. The log's header comment says so; no gate can check it.

```sh
python3 analysis/tools/parity/log_check.py     # 0 pass, 1 fail
```

Mutation-tested: a fifth field, a third, `15-08-2026`, an `UPPERCASE_Slug`, a
duplicate id, an id that goes backwards, and an empty paragraph are each caught.

