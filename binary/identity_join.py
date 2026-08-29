#!/usr/bin/env python3
"""Join every recovered identity for one binary into a single annotated table.

Inputs
- functions.tsv   the decompile_dump.py manifest: addr end size name demangled status chunk
- annotation TSVs: first column an 0x... address, remaining columns a value.
  `--name LBL=F`  value becomes a candidate NAME (label records the source).
  `--role LBL=F`  value becomes a ROLE note (function purpose, from prose docs).

Output: one row per function:
  addr end size ida_name best_name name_sources roles

best_name priority: assert/curated names (first --name source that has one)
> RTTI vtable method > the IDA name. Ties are listed, never silently dropped:
name_sources holds every `label=value` that fired, joined by `; `.

Usage:
  identity_join.py decomp/DIR/functions.tsv decomp/DIR/names.tsv \
      --name assert=decomp/DIR/assert-names.tsv \
      --name rtti=analysis/rtti/lgp_linux_vmethods.tsv \
      --role docs=curated-address-roles.tsv
"""

import argparse
import collections
import sys


def read_annotations(path, kind):
    """addr -> list of (value) for one annotation file."""
    out = collections.defaultdict(list)
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln or ln.startswith("#") or ln.startswith("addr\t"):
                continue
            parts = ln.split("\t")
            if not parts[0].startswith("0x"):
                continue
            try:
                addr = int(parts[0], 16)
            except ValueError:
                continue
            value = "\t".join(p for p in parts[1:] if p)
            if value:
                out[addr].append(value)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("functions_tsv")
    ap.add_argument("out_tsv")
    ap.add_argument(
        "--name", action="append", default=[], metavar="LBL=PATH",
        help="annotation file whose values are candidate names",
    )
    ap.add_argument(
        "--role", action="append", default=[], metavar="LBL=PATH",
        help="annotation file whose values are role notes",
    )
    args = ap.parse_args(argv)

    names = []  # (label, {addr: [values]}) in priority order
    for spec in args.name:
        label, path = spec.split("=", 1)
        names.append((label, read_annotations(path, "name")))
    roles = []
    for spec in args.role:
        label, path = spec.split("=", 1)
        roles.append((label, read_annotations(path, "role")))

    n_rows = n_named = 0
    with open(args.functions_tsv, encoding="utf-8") as fh, open(
        args.out_tsv, "w", encoding="utf-8"
    ) as out:
        out.write("addr\tend\tsize\tida_name\tbest_name\tname_sources\troles\n")
        for ln in fh:
            if ln.startswith("addr\t"):
                continue
            parts = ln.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            addr = int(parts[0], 16)
            end, size, ida_name = parts[1], parts[2], parts[3]
            n_rows += 1

            hits = []  # (label, value) for name candidates, in priority order
            for label, table in names:
                for value in table.get(addr, []):
                    hits.append((label, value))
            best = ""
            if hits:
                best = hits[0][1]
            elif ida_name and not ida_name.startswith("sub_") and not ida_name.startswith(
                "nullsub"
            ):
                best = ida_name
            sources = "; ".join(f"{label}={value}" for label, value in hits)

            role_hits = []
            for label, table in roles:
                for value in table.get(addr, []):
                    role_hits.append(f"{label}={value}")
            out.write(
                f"0x{addr:08x}\t{end}\t{size}\t{ida_name}\t{best}\t{sources}\t"
                f"{'; '.join(role_hits)}\n"
            )
            if best:
                n_named += 1
    print(
        f"identity_join: {n_rows} functions, {n_named} carry a best_name "
        f"({100.0 * n_named / max(n_rows, 1):.1f}%)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
