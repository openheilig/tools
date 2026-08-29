#!/usr/bin/env python3
"""Bulk Hex-Rays decompilation dump for one binary, via idalib.

Run with the idalib-enabled interpreter (the ida-pro-mcp venv python):

    <venv-python> decompile_dump.py <binary-or-i64> <outdir>

Outputs, under <outdir>:
  functions.tsv   one row per function: addr end size name demangled status chunk
  chunks/NNNN.c   decompiled pseudocode, CHUNK_FUNCS per file, each function
                  introduced by a `// ==== addr=... name=... status=...` banner
  summary.json    totals: functions, decompiled, failed, timeouts

Notes
- The database is opened read-only in spirit: nothing is renamed here and the
  database is closed WITHOUT saving, so an existing .i64 is adopted but never
  modified by a dump run.
- `idapro` must be the first import (idalib requirement).
- Per-function hard timeout (DECOMP_TIMEOUT_SEC, default 120 s) so one
  pathological function cannot stall the whole dump; the function is recorded
  as `timeout` and the dump continues.
- DECOMP_LIMIT caps the function count (smoke tests only).
- DECOMP_CHUNK_FUNCS overrides the 200-functions-per-chunk default.
"""

import idapro  # isort: skip -- must be the first import

import json
import os
import signal
import sys
import time

import ida_auto
import ida_funcs
import ida_hexrays
import ida_name
import idautils

CHUNK_FUNCS = int(os.environ.get("DECOMP_CHUNK_FUNCS", "200"))
FUNC_TIMEOUT = float(os.environ.get("DECOMP_TIMEOUT_SEC", "120"))
LIMIT = int(os.environ.get("DECOMP_LIMIT", "0"))


class FuncTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise FuncTimeout()


def demangle(name):
    try:
        flag = getattr(ida_name, "MNG_LONG_FORM", 0)
        if not flag:
            return ""
        d = ida_name.demangle_name(name, flag)
        return d if d else ""
    except Exception:
        return ""


def main():
    if len(sys.argv) != 3:
        print("usage: decompile_dump.py <binary-or-i64> <outdir>", file=sys.stderr)
        return 2
    target, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    chunks_dir = os.path.join(outdir, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    t0 = time.time()
    print(f"[dump] opening {target}", flush=True)
    try:
        idapro.open_database(target, True)
    except Exception as e:
        # Fall back to opening an adjacent .i64 directly.
        alt = target + (".i64" if not target.endswith(".i64") else "")
        if os.path.exists(alt):
            print(f"[dump] open({target!r}) failed ({e}); opening {alt!r}", flush=True)
            idapro.open_database(alt, True)
        else:
            raise
    ida_auto.auto_wait()
    if not ida_hexrays.init_hexrays_plugin():
        print("[dump] FATAL: Hex-Rays decompiler unavailable", flush=True)
        idapro.close_database(False)
        return 1
    print(f"[dump] analysis warm in {time.time()-t0:.1f}s", flush=True)

    tsv_path = os.path.join(outdir, "functions.tsv")
    summary_path = os.path.join(outdir, "summary.json")
    tsv = open(tsv_path, "w", encoding="utf-8")
    tsv.write("addr\tend\tsize\tname\tdemangled\tstatus\tchunk\n")

    chunk_idx = 0
    chunk_file = None
    in_chunk = 0
    n_total = n_ok = n_fail = n_timeout = 0

    def open_chunk():
        nonlocal chunk_file, chunk_idx, in_chunk
        if chunk_file:
            chunk_file.close()
        chunk_idx += 1
        chunk_file = open(
            os.path.join(chunks_dir, f"{chunk_idx:05d}.c"), "w", encoding="utf-8"
        )
        in_chunk = 0

    open_chunk()
    signal.signal(signal.SIGALRM, _alarm)

    for ea in idautils.Functions():
        if LIMIT and n_total >= LIMIT:
            break
        f = ida_funcs.get_func(ea)
        if f is None:
            continue
        name = ida_funcs.get_func_name(ea) or ""
        dem = demangle(name)
        size = f.size()
        n_total += 1
        status = "ok"
        text = None
        signal.setitimer(signal.ITIMER_REAL, FUNC_TIMEOUT)
        try:
            cf = ida_hexrays.decompile(ea)
            text = str(cf)
        except FuncTimeout:
            status = "timeout"
            n_timeout += 1
        except Exception as e:
            status = "fail"
            n_fail += 1
            text = f"// DECOMPILE FAILED: {type(e).__name__}: {e}"
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        if status == "ok":
            n_ok += 1
        if in_chunk >= CHUNK_FUNCS:
            open_chunk()
        chunk_file.write(
            f"// ==== addr=0x{ea:08x} end=0x{f.end_ea:08x} size={size} "
            f"name={name} status={status}\n"
        )
        if dem:
            chunk_file.write(f"// ==== demangled={dem}\n")
        if text is None:
            text = f"// DECOMPILE TIMEOUT after {FUNC_TIMEOUT}s"
        chunk_file.write(text.rstrip() + "\n\n")
        in_chunk += 1
        tsv.write(
            f"0x{ea:08x}\t0x{f.end_ea:08x}\t{size}\t{name}\t{dem}\t{status}\t{chunk_idx:05d}\n"
        )
        if n_total % 500 == 0:
            tsv.flush()
            chunk_file.flush()
            print(
                f"[dump] {n_total} functions | ok={n_ok} fail={n_fail} "
                f"timeout={n_timeout} | {time.time()-t0:.0f}s",
                flush=True,
            )

    if chunk_file:
        chunk_file.flush()
        chunk_file.close()
    tsv.close()
    summary = {
        "target": target,
        "functions": n_total,
        "decompiled": n_ok,
        "failed": n_fail,
        "timeout": n_timeout,
        "seconds": round(time.time() - t0, 1),
        "chunk_funcs": CHUNK_FUNCS,
        "chunks": chunk_idx,
    }
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"[dump] DONE {summary}", flush=True)
    idapro.close_database(False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
