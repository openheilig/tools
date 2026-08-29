#!/usr/bin/env python3
"""Export MSVC vftable layouts from an already-analyzed PE via idalib.

    <venv-python> extract_vftables_idalib.py <binary> <out.tsv>

Walks every name IDA recognized (its own RTTI parser names `??_7Class@@6B@`
vftables in stripped binaries), reads slot dwords until the table ends, and
writes:  class  slot  target_addr  target_name

The database is closed without saving. Run AFTER decompile_dump.py so the
database is warm.
"""

import idapro  # isort: skip

import sys

import ida_bytes
import ida_funcs
import ida_name
import idautils


def demangled_class(name):
    d = ida_name.demangle_name(name, ida_name.MNG_LONG_FORM)
    if not d:
        return ""
    # "Class::`vftable'" -> Class ; "Class::`RTTI Complete Object Locator'" skip
    if "Locator" in d:
        return ""
    for marker in ("::`vftable'", "::`vftable"):
        if marker in d:
            return d.split("::`vftable")[0]
    return ""


def main():
    if len(sys.argv) != 3:
        print("usage: extract_vftables_idalib.py <binary> <out.tsv>", file=sys.stderr)
        return 2
    target, out_path = sys.argv[1], sys.argv[2]
    idapro.open_database(target, True)
    n_tables = n_slots = 0
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("class\tslot\ttarget_addr\ttarget_name\n")
        for ea, name in idautils.Names():
            cls = demangled_class(name)
            if not cls:
                continue
            n_tables += 1
            slot = 0
            cur = ea
            while True:
                tgt = ida_bytes.get_dword(cur)
                if tgt == 0xFFFFFFFF or tgt == 0:
                    break
                f = ida_funcs.get_func(tgt)
                if f is None or f.start_ea != tgt:
                    break  # not a function pointer -> end of table
                fname = ida_name.get_name(tgt) or ""
                out.write(f"{cls}\t{slot}\t0x{tgt:08x}\t{fname}\n")
                n_slots += 1
                slot += 1
                cur += 4
    print(f"[vftables] {n_tables} tables, {n_slots} slots -> {out_path}", flush=True)
    idapro.close_database(False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
