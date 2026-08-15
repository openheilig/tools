# drive — playing the game headlessly

**Status:** Working
**Purpose:** Play the retail game from a script and capture what it drew, so runs can be
compared against each other rather than against memory.

A measurement is only worth something if it can be repeated. These drive the
retail game from a script and capture what it drew, so a run can be compared
against another run instead of against somebody's memory of it.

The input itself comes from `autopilot.so` in [../shim/](../shim/); these are
the front-ends that aim it.

| Tool | What |
|---|---|
| `shot.sh` | Drive with a script, capture the framebuffer at given milliseconds. |
| `look.sh` | See what either engine is drawing, without stealing your display. |
| `probe_ui.sh` | Fire an autopilot script at the menu blind and report back. |
| `extract_video_frames.py` | Pull frames out of a captured video. |

```sh
sh analysis/tools/drive/shot.sh "<label>" "<SACRED_AUTO>" "<ms,ms,...>" [seconds]
sh analysis/tools/drive/look.sh port     # or: retail
```

The frames these produce are what the pixel gates in [../parity/](../parity/)
consume.

---
Verified by: The captures themselves; a run that cannot be repeated is not evidence.
