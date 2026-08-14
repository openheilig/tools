# live — the running process

What the static tools cannot answer: whether a mechanism is *used*, what the
engine actually reads, and what it does when a read comes up short. These
attach to the running retail game — or, in `altest.c`'s case, to the machine
the game has to run on.

| Tool | What |
|---|---|
| `p6_memscan.py` | Live memory scan and patch against the running retail process. |
| `save_patch.py` | Patch the hero position in a save (`game01.pak`). |
| `patch_1002.py` | Re-derive the install **compatibility** patches (GL capability scan, VRAM cache, launcher dialog) for LGP 1.0.02 by anchor search. |
| `gdb_run.sh` | Run the game under gdb and sample its stacks. |
| `shortread_watch.sh` | Report every short read out of the engine's save/world stream. |
| `log_timeline.sh` | Launch once and sample the debug log on an interval. |
| `altest.c` | Can the bundled OpenAL open an output device on this machine? Asks the library directly, outside the engine. |

`patch_1002.py` ships the compatibility patches only. The activation sites are
kept out of this repository on purpose — see the note at the end of
[../README.md](../README.md).

`altest` is compiled output and untracked:

```sh
gcc -m32 -o analysis/tools/live/altest analysis/tools/live/altest.c \
    -Iinstall/include -Linstall/lib/lib1 -lopenal
```

To drive the game while these watch it, see [../drive/](../drive/) and
[../shim/](../shim/).
