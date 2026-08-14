#!/usr/bin/env python3
"""Identity-verified extraction of one `models.pak` entry to a standalone file.

The only sanctioned way a pak entry becomes a file for the granny oracle to
open. Exists because two prior sessions fed the oracle scratch files that
were never checked against the real pak bytes and got misleading, later
retracted, results (findings rows 581, 584).

    grn_extract.py --entry=N --out=PATH [--bare] [--expect-md5=HEX] [--expect-size=N]

Length comes from grn_tagwalk.derive_length -- the gap to the next entry by
ascending offset -- imported, never restated. field3 (the raw pak directory
"size") is untrustworthy for kind=64 and is not used here at all.

The bytes are written to --out, then the file is re-read from disk and the
`extract` line is printed from what is actually on disk, never from the
in-memory buffer. --expect-md5 / --expect-size, when given, are checked
against those on-disk values; on any mismatch the output file is deleted and
the tool exits non-zero -- nothing wrong is ever left behind.

--bare additionally slices from the kind-scoped magic offset so the file on
disk begins exactly at 0xCA5E0000, and OVERWRITES --out with that slice
after the full-entry identity check above has already passed. Its md5 is a
separate identity, printed alongside the full-entry md5 on one line; it
never inherits --expect-md5 (there is no --expect-bare-md5 flag).

An entry that fails the magic check (grn_tagwalk.classify) is refused by
name: nothing is read past the check, nothing is written.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from grn_tagwalk import (  # noqa: E402
    GAME, ROOT_TAG, classify, derive_length, md5, pak_index3, read_name,
)


def models_path():
    return os.path.join(GAME, "pak", "models.pak")


def parse_args(argv):
    args = {"entry": None, "out": None, "bare": False,
            "expect_md5": None, "expect_size": None}
    for a in argv:
        if a.startswith("--entry="):
            args["entry"] = int(a.split("=", 1)[1])
        elif a.startswith("--out="):
            args["out"] = a.split("=", 1)[1]
        elif a == "--bare":
            args["bare"] = True
        elif a.startswith("--expect-md5="):
            args["expect_md5"] = a.split("=", 1)[1].lower()
        elif a.startswith("--expect-size="):
            args["expect_size"] = int(a.split("=", 1)[1])
        else:
            raise SystemExit(f"unknown argument: {a}")
    if args["entry"] is None or args["out"] is None:
        raise SystemExit(__doc__)
    return args


def main():
    args = parse_args(sys.argv[1:])
    idx = args["entry"]
    out_path = args["out"]

    with open(models_path(), "rb") as f:
        entries = pak_index3(f)
        file_size = os.fstat(f.fileno()).st_size
        if not 0 <= idx < len(entries):
            print(f"extract\tentry={idx}\tERROR out of range (0..{len(entries) - 1})")
            raise SystemExit(1)
        kind, offset, field3 = entries[idx]
        true_len = derive_length(entries, idx, file_size)
        name = read_name(f, offset)
        ok, magic_off, reason = classify(f, kind, offset, true_len)
        if not ok:
            print(f"extract\tentry={idx}\tname={name}\tkind={kind}\t"
                  f"REFUSED reason={reason}")
            raise SystemExit(1)
        f.seek(offset)
        full_bytes = f.read(true_len)

    # Write the full entry, then re-read from disk -- everything reported or
    # checked from here on comes from the file, never the buffer above.
    with open(out_path, "wb") as o:
        o.write(full_bytes)
    with open(out_path, "rb") as o:
        disk_bytes = o.read()
    disk_size = len(disk_bytes)
    disk_md5 = md5(disk_bytes)

    print("extract\tentry=%d\tname=%s\tkind=%d\tsize=%d\tmd5=%s\tout=%s" % (
        idx, name, kind, disk_size, disk_md5, out_path))

    mismatch = False
    if args["expect_size"] is not None and disk_size != args["expect_size"]:
        print(f"extract\tentry={idx}\tMISMATCH expect_size={args['expect_size']} got={disk_size}")
        mismatch = True
    if args["expect_md5"] is not None and disk_md5 != args["expect_md5"]:
        print(f"extract\tentry={idx}\tMISMATCH expect_md5={args['expect_md5']} got={disk_md5}")
        mismatch = True
    if mismatch:
        os.remove(out_path)
        print(f"extract\tentry={idx}\tDELETED {out_path} -- identity check failed, nothing left behind")
        raise SystemExit(1)

    if args["bare"]:
        bare_bytes = disk_bytes[magic_off:]
        magic_word = struct.unpack_from("<I", bare_bytes, 0)[0]
        if magic_word != ROOT_TAG:
            print(f"extract\tentry={idx}\tbare REFUSED magic mismatch 0x{magic_word:08x}")
            raise SystemExit(1)
        with open(out_path, "wb") as o:
            o.write(bare_bytes)
        with open(out_path, "rb") as o:
            bare_disk = o.read()
        bare_md5 = md5(bare_disk)
        print("extract\tentry=%d\tbare=true\tfull_md5=%s\tbare_md5=%s\tbare_size=%d\tout=%s" % (
            idx, disk_md5, bare_md5, len(bare_disk), out_path))

    raise SystemExit(0)


if __name__ == "__main__":
    main()
