# drive — playing the game headlessly

**Status:** Working
**Purpose:** Play the retail game from a script and capture what it drew, so runs can be
compared against each other rather than against memory.

A measurement is only worth something if it can be repeated. These drive the
retail game from a script and capture what it drew, so a run can be compared
against another run instead of against somebody's memory of it.

The input itself comes from `autopilot.so` in [../shim/](../shim/); these are
the front-ends that aim it. Since 2026-08-16 the **port** takes the same
scripts, through `godot-port/drive.gd` — so one step list drives both engines
and `session.sh` runs it against both at once.

| Tool | What |
|---|---|
| `session.sh` | Run ONE script against BOTH engines and report what each drew at the same milliseconds. |
| `shot.sh` | Drive retail with a script, capture the framebuffer at given milliseconds. |
| `look.sh` | See what either engine is drawing, without stealing your display. |
| `menu.sh` | Emit the script that walks retail's main menu into a world. |
| `probe_ui.sh` | Fire an autopilot script at the menu blind and report back. |
| `extract_video_frames.py` | Pull frames out of a captured video. |

```sh
sh analysis/tools/drive/session.sh chapel "1000 key iso_right 1500" 0,2000,4000
sh analysis/tools/drive/shot.sh "<label>" "<SACRED_AUTO>" "<ms,ms,...>" [seconds]
sh analysis/tools/drive/look.sh port     # or: retail
```

The frames these produce are what the pixel gates in [../parity/](../parity/)
consume.

## The script grammar

`ms verb args`, semicolon-separated, defined by `autopilot.c` and implemented
a second time by `drive.gd`:

| Verb | Retail | Port |
|---|---|---|
| `move X Y` | yes | yes |
| `click X Y` | yes | yes |
| `hold X Y` / `release` | yes | yes |
| `wheel 4\|5 N` | yes | yes (4 = up, 5 = down) |
| `key NAME [MS]` | press+release, SDL keysym | Input Map action or key name; `MS` **holds** it |
| `text CHARS` | yes | refused — the port takes no typed input |

⚠️ **`key iso_*` looks like it does nothing in a default run.** The camera
follows the player every frame, so a pan is applied and then overwritten
before it is drawn — measured, 1200ms of `iso_right` moved 0.27% of pixels.
That is the port behaving correctly, not the driver failing. Pass `--noplayer`
to pan (it stops the follow; `--hideplayer` does not). Under `--noplayer` the
same script moves 95.24%, and `wheel 5 1` moves 93.64% with the follow left
on, which is how the input path was confirmed live rather than assumed.

`key` diverges because the port reads panning through `Input.get_vector`,
which samples *held* state: a press and release inside one frame pans by
nothing. The port takes Input Map action names (`iso_left`, `iso_right`,
`iso_up`, `iso_down`) rather than keycodes, so a rebind in `project.godot`
cannot make a script go stale.

## Two things `session.sh` refuses to paper over

**One size only.** Retail's grab is hard-coded to 1024×768 (`autopilot.c`
`shot_w`/`shot_h`), so the port is launched at `--resolution 1024x768` and
`drive.gd` **exits 1** rather than capture `--shots=` at any other size. Every
pair is re-measured with `magick identify` before comparison; a pair that is
not 1024×768 on both sides is reported as `NOT COMPARED` instead of being
handed to `png_delta.py`.

**Two clocks, one origin each.** The port's `t=0` is the first *settled*
frame. Retail's `t=0` is process start. `DRIVE_RETAIL_OFFSET` (default 8000)
shifts every retail timestamp for that reason. What the two columns share is
*the script and the elapsed time*, not the game state, so a delta here is a
look, not a verdict. The verdicts live in [../parity/](../parity/).

⚠️ **At the default offset retail is still on the main menu, so the delta is
~100% and means nothing.** `menu.sh` is the way past that: it writes the
`click` walk that gets retail into a world, and `--ready` gives the offset
that lands after the load. `session.sh` prepends the walk verbatim (never
shifted) when `DRIVE_RETAIL_PRELUDE` is set:

```sh
DRIVE_RETAIL_PRELUDE="$(sh analysis/tools/drive/menu.sh new)" \
DRIVE_RETAIL_OFFSET=$(sh analysis/tools/drive/menu.sh new --ready) \
sh analysis/tools/drive/session.sh sera "" 0,4000 20
```

Two routes, both measured 2026-08-16 at 1024×768:

| Route | Where it lands | Ready |
|---|---|---|
| `new` | Ancaria → **Seraphim** → Start Game, tutorial skipped: Silver Creek cathedral, 0 `CalcResults FAILED`. | 34000 |
| `load` | `./SAVE/GAME01.PAK` → Valor's Fortress. Faster (world at 20 s) but its state is a savegame, not a fresh world. | 60000 |

`new` is the parity route — a fresh campaign is the same world on both
engines, a savegame is not. Its first use found the camera bug: the port and
retail were drawing the *same* room and `png_delta.py` still called it an 85.8%
mismatch, because the port's view sat one world unit off (row 975, fixed in
`iso_camera.gd`'s `VIEW_ORIGIN`). **Run `../parity/p6_classify.py` on a pair
before believing a delta** — it separates a translation from a content
difference, and a one-pixel translation reads exactly like total disagreement.

**Retail cannot be launched into a world directly.** Its argv parser
(`0x809302A`) accepts exactly `-h -v -w -f -s -n -d -g` and refuses to start
on anything else, and no key in the `Settings.cfg` table names a savegame or
a map. The menu walk is not a convenience; it is the only door.

---
Verified by: The captures themselves; a run that cannot be repeated is not evidence.
