# granny_oracle — calling RAD's Granny runtime

**Status:** Built, and the thing it was built to do is blocked
**Purpose:** Call the shipped Granny converter on a Sacred `.GRN` and read what
it produces, as an independent check on our own decoder.

Clean-room posture: this harness only **calls exported functions and reads
their output**. Nothing here is decompiled, disassembled, or derived from
RAD's SDK source.

**No third-party binaries are stored in this repo.** `granny2.dll`,
`grn2gr2.dll`, `gr2_viewer.exe` and `SacredMdlExtr.exe` come from SonicMouse's
`SacredMdlExtr.rar` (sacred-tribute.com community archive) and are kept in a
scratch directory only.

| File | What |
|---|---|
| `granny_probe.c` | Loads the DLL, reports version, installs the log callback. |
| `granny_dump_geometry.c` | Single-argument convert call — the first tracer. |
| `granny_dump_skeleton.c` | The general harness: `conv` / `dump` / `control` modes, one hypothesis per process because a crash takes the process down. `conv` truncates its destination first and checks the file grew, so a stale leftover cannot read as success. |
| `grn_extract.py` | Extracts a `models.pak` entry with a checked identity — size plus md5, output deleted on mismatch. |
| `kernel32.def` | Import definitions; must carry stdcall decorations (`Name@N == Name`) or `lld-link` cannot resolve `_GetProcAddress@8`. |

## Build (no mingw required)

The system has no 32-bit Wine dev libs, so `winegcc -m32` fails. Build a
freestanding 32-bit PE with LLVM only:

```sh
llvm-dlltool -m i386 -d kernel32.def -l kernel32.lib
clang --target=i686-pc-windows-msvc -c -O1 -ffreestanding \
      -fno-stack-protector -o gp.obj granny_probe.c
lld-link -subsystem:console -entry:mainCRTStartup -nodefaultlib \
      -out:gp.exe gp.obj kernel32.lib
WINEPREFIX=<prefix> WINEDEBUG=-all wine gp.exe FILE.GRN
```

Disable WineDbg's crash dialog first, or `wine` blocks on an interactive
debugger prompt instead of exiting:

```sh
wine reg add "HKEY_CURRENT_USER\Software\Wine\WineDbg" \
     /v ShowCrashDialog /t REG_DWORD /d 0 /f
```

## Before you run it again

The converter **crashes on every real Sacred `.GRN`**, at one instruction,
insensitive to pairing, ordering, slicing or flags — and returns cleanly on
nonexistent paths, which is what proves the fault is content-triggered. The
full investigation, its two corrections and the control that closed it are in
[research/engine/granny-runtime-oracle.md](https://github.com/openheilig/research/blob/main/engine/granny-runtime-oracle.md).
Read that before opening a new hypothesis; three were tried and closed.

---
Verified by: nothing — this harness produced no converted file. Its value is
the negative result written up in research.
