# shim — LD_PRELOAD interposers

32-bit shims loaded into the retail `sacred` process. The binary is stripped
and closed, but every mechanism these touch is a *dynamic import*, so plain
symbol interposition sees all of it — no recompilation, no instrumentation
that a 2005 binary would not survive.

| Source | What |
|---|---|
| `autopilot.c` | Scripted input, so the game can be driven headlessly and reproducibly. |
| `xshim.c` | X11 interposition. |
| `filetrace.c` | Trace file I/O — answers "is this mechanism actually used?" by measurement rather than by grep. |
| `localetrace.c` | Same, for locale calls. |
| `sacredtrace.c` | `sem`/`thread`/`io` tracing, for the async-load race hypothesis. |

## Building

```sh
sh shim/build.sh          # autopilot, xshim, filetrace, localetrace -> install/shim/
```

`build.sh` does **not** build `sacredtrace.c`; it is compiled by hand when a
run needs it. The built `.so` files stay in `install/shim/`, where `play.sh`'s
`LD_LIBRARY_PATH` picks them up — they are runtime artefacts and rebuildable
from here, so they are not tracked.

The sources live here rather than beside the retail binary because the install
tree is denied wholesale by the workspace `.gitignore` — it holds ~16 GB of
non-redistributable game data. These `.c` files ship nothing of the game's.

Front-ends that aim `autopilot.so` are in [../drive/](../drive/).
