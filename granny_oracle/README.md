# granny_oracle — probing granny2.dll for ground-truth GRN geometry

Clean-room posture: this harness only **calls exported functions and reads
their output**. Nothing here is decompiled, disassembled, or derived from
RAD's SDK source. Same stance as the retail autopilot oracle.

**No third-party binaries are stored in this repo.** `granny2.dll`,
`gr2_viewer.exe` and `SacredMdlExtr.exe` come from SonicMouse's
`SacredMdlExtr.rar` (sacred-tribute.com community archive) and are kept in
`/tmp/smdl` only.

## Build (no mingw required)

The system has no 32-bit Wine dev libs, so `winegcc -m32` fails. Instead build
a freestanding 32-bit PE with LLVM only:

```sh
llvm-dlltool -m i386 -d kernel32.def -l kernel32.lib
clang --target=i686-pc-windows-msvc -c -O1 -ffreestanding \
      -fno-stack-protector -o gp.obj granny_probe.c
lld-link -subsystem:console -entry:mainCRTStartup -nodefaultlib \
      -out:gp.exe gp.obj kernel32.lib
WINEPREFIX=/tmp/smdl/wp WINEDEBUG=-all wine gp.exe FILE.GRN
```

The `.def` must carry stdcall decorations (`Name@N == Name`), otherwise
lld-link cannot resolve `_GetProcAddress@8` etc.

## What it establishes (superseded history — see the 05-03 Task 2 correction below)

- granny2.dll loads under Wine and reports version **2.5.0.11**
- `GrannySetLogCallback` works and yields real diagnostics
- On a Sacred `.GRN` it reports:
  `granny_file.cpp(351): File is not a Granny file`

## Known blocker

granny2 **2.5 cannot read Granny 1.x `.GRN`**. The GRN reader lives in
`gr2_viewer.exe`, which exports exactly two functions:

```
?GRN2GR2ConvertGRNFile@@YGXPBD0_N0@Z   void __stdcall (char const*, char const*, bool, char const*)
?GRN2GR2DumpFile@@YGXPBD@Z             void __stdcall (char const*)
```

`LoadLibraryA("gr2_viewer.exe")` succeeds and both symbols resolve, but calling
either faults reading the *same* address — the EXE's CRT and C++ static
initializers never run when it is mapped as a library, so a module global stays
uninitialized. Argument shape is not the problem: a 1-arg and a 4-arg entry
point fault identically.

Next options: run `gr2_viewer.exe` as a real process and drive its open dialog
(it writes `ViewerConvertTemp.gr2`), or locate RAD's standalone `grn2gr2`.

**Correction (05-03 Task 2), replacing both paragraphs above.** `granny2.dll`
in `/tmp/smdl/g27` is actually **2.7.0.30** (renamed from `granny2_27.dll`),
not 2.5.0.11. The real GRN converter is `grn2gr2.dll` itself, not
`gr2_viewer.exe` — `?GRN2GR2ConvertGRNFile@@YGXPBD0_N0@Z` resolves and can be
called directly; no dialog-driving or `gr2_viewer.exe`-as-a-process workaround
is needed to reach it. The "faults reading the same address regardless of
argument shape" observation was correct as an observation but wrong about the
cause — it is not an uninitialized CRT global from being mapped as a library,
it is `grn2gr2.dll` itself null-dereferencing partway through parsing a real
Sacred Gold `.GRN` object, as the next two sections establish.

## 2026-08-10 — Tracer: crash reproduced on identity-verified bytes (05-03 Task 1)

`analysis/tools/granny_oracle/grn_extract.py` now extracts a `models.pak`
entry with a checked identity (on-disk size + md5, deleting the output on any
mismatch) instead of trusting an unverified scratch file — see findings rows
581/584 for why that mattered. Two variants of pak entry 589
(`GLADIATOR.GRN`, kind=64 mesh) were extracted and fed to the existing
`granny_dump_geometry.c` harness's unpaired, single-argument
`Conv("GLADIATOR.GRN","out.gr2",0,"")` call (same call shape as the earlier
crash in row 584 — this tracer characterises it, it does not yet fix it):

| Variant | md5 | Result |
|---|---|---|
| Full pak entry (186,842 bytes, `--expect-size=186842 --expect-md5=778e237626e568662237798388654ce0`) | `778e237626e568662237798388654ce0` | **CRASH**, identical signature below |
| `--bare` slice from the kind-64 magic offset (185,584 bytes, begins `0xCA5E0000`) | `ae4cb6bf83eb7c11ee191cf6eadaf687` | **CRASH**, identical signature |

Both variants fault identically:

```
wine: Unhandled page fault on read access to 00000000 at address 100061BF
Backtrace: =>0 0x100061bf in grn2gr2 (+0x61bf) (0xffffffff)
0x100061bf grn2gr2+0x61bf: cmpl $0xca5e0103, (%eax)
EAX:00000000 EBX:0022fe00 ECX:00000000 EDX:00000000
```

Exact match to 05-RESEARCH.md's characterised crash. The faulting instruction
compares against the object tag `0xCA5E0103`, and `EAX=0` — the converter
dereferences a null pointer to a structure it expected to already have. The
crash does **not** depend on whether a pak/header preamble precedes the
`0xCA5E0000` root tag (both the full pak entry and the bare from-root-tag
slice fault at the same address), which rules out "extra leading bytes
confuse the parser" as the explanation and leaves D-24's documented
`.GRN`/`.GRN+` pairing requirement (the converter was only ever given the
mesh alone, never paired with its motion) as the leading hypothesis — tested
next, in order, by Task 2's `granny_dump_skeleton.c`.

`WineDbg`'s crash dialog was disabled for this and all later sessions:
`wine reg add "HKEY_CURRENT_USER\Software\Wine\WineDbg" /v ShowCrashDialog
/t REG_DWORD /d 0 /f` (persisted in the `/tmp/smdl/wp` prefix) — without it,
`wine` blocks waiting on an interactive debugger prompt instead of exiting.

## 2026-08-10 — Task 2: H1/H2/H3 tried in order, all crash identically — BLOCKED

`analysis/tools/granny_oracle/granny_dump_skeleton.c` is a general-purpose
harness (`conv`/`dump`/`control` modes, one hypothesis per process since a
crash takes the whole process down) built for this task. Its `conv` mode
truncates the destination `.gr2` to 0 bytes (via `CreateFileA`+`CREATE_ALWAYS`
— `kernel32.def` isn't in this plan's `files_modified`, so the check reuses
exports already declared instead of adding `DeleteFileA`) before calling
`Conv()`, and checks the file grew past 0 bytes afterward — added because a
**pre-existing, uncommitted
scratch probe** (`/tmp/smdl/g27/gh9.c`, not part of this project's tracked
history) reported a false "success" that turned out to be `md5`-identical to
a `.gr2` file a day older: `Conv()` had silently no-op'd on a 185,648-byte
`GLADIATOR.GRN` that didn't even parse as a valid GRN (no root tag at offset
0), and `GrannyReadEntireFile` picked up the stale leftover file instead.
Exactly the row-581/584 pattern, discovered live in this file's own history —
recorded here so nothing built on this harness repeats it silently.

**H1 (documented pairing, D-24).** Both `community/guide.docx` and the
in-repo `community/unpack-tools/AoM Model Plugin/AoM Model Plugin
7.3.0/ReadME.html` state that a viewer must be given the base model and its
animation together — an animation file alone shows nothing — so pairing is a
requirement here, not one hypothesis among several. Entry 589 (base, `--bare`, identity
`ae4cb6bf83eb7c11ee191cf6eadaf687`) and entry 2845 (motion, `--bare`,
identity `ab4d4cee39dc4a62f9cf2ce5bfe5b398`) passed as the two leading
`char const*` args to `GRN2GR2ConvertGRNFile`, real destination in the 4th
arg (the only unused slot in every prior call in this codebase):

| # | p1 | p2 | bool | Result |
|---|---|---|---|---|
| 1 | base (589) | motion (2845) | 0 | **CRASH**, `grn2gr2+0x61bf`, `cmpl $0xca5e0103,(%eax)`, `EAX=0` |
| 2 | base (589) | motion (2845) | 1 | **CRASH**, identical signature |
| 3 | motion (2845) | base (589) | 0 | **CRASH**, identical signature |
| 4 | motion (2845) | base (589) | 1 | **CRASH**, identical signature |

All 4 combinations fault at the exact same instruction. **H1 REFUTED.**

**H2 (pak-relative addressing, whole un-sliced entry).** Already tried in
Task 1's tracer against the full, identity-verified 186,842-byte pak entry
(`778e237626e568662237798388654ce0`), unpaired single-arg call — same crash,
same address. **H2 REFUTED**, not re-run here.

**H3 (buffer shape).** The `--bare` slice's declared object length (root
chunk field at `+0x10`) is 185,584 — exactly equal to the slice's own size —
and the slice is already a multiple of 16 bytes (185,584 % 16 = 0). Both H3
variants ("padded to 16-byte boundary", "truncated to the declared object
length") are no-ops on this data: there is no distinct byte sequence to test.
**H3 not applicable — nothing to vary.**

**A decisive control, before stopping:** the same `conv` call against two
nonexistent file paths returns cleanly (`NO_VALID_OUTPUT
reason=convert_did_not_write_p4`, no crash). So the fault is genuinely
triggered by real Sacred Gold `.GRN` content being parsed — not an
unconditional setup fault independent of input — yet its exact crash location
is completely insensitive to which real file is p1/p2, their order, the bool
flag, or whether a pak-prefix precedes the root tag. Six real-file
invocations (2 in Task 1, 4 here) all fault at the identical instruction. The
most consistent explanation is that `grn2gr2.dll` 's parser does not handle a
structural feature common to Sacred Gold's `.GRN` dialect at all (not a
pairing, addressing, or framing problem) — this build of the converter cannot
be driven past that point regardless of how it is called.

**Per the plan's halt_contract: H1-H3 all tried in order, none converts. Do
not open H4. Oracle status: BLOCKED.** No skeleton dump, no D-09
counterfactual, and no per-mesh vertex-count comparison were possible — there
is no converted `.gr2` to read. D-15 (head mesh 279-vs-280 vertex count)
stays open; it is not resolved by this plan.

As always: `granny2.dll` and `grn2gr2.dll` are never committed to this repo.
All copies used above live under `/tmp/smdl` only.
