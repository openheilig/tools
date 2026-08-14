#!/bin/bash
# Phase 2 UAT Test 2 extension -- the roofed-overhang crossing case.
#
# Walks the --sortcube= marker across the THRONSAAL castle (sector 36,30), the
# densest multi-storey family in the placement census, with the camera CENTRED
# ON THE CUBE at every step. Centring is the control for TSV row 380, where an
# apparent "partial occlusion" turned out to be camera-frustum clipping at the
# frame border: a cube at screen centre cannot be border-clipped, so any
# partial magenta count here is geometry, not framing.
#
# Prints one row per position: cell, magenta pixel count, and whether the
# magenta region touches the image border (must be 0 for the run to count).
set -u
OUT=/tmp/p2/loggia
mkdir -p "$OUT"
cd "$(dirname "$0")/../../godot-port" || exit 1

CX=${CX:-2320}
for CY in $(seq "${FROM:-1922}" "${STEP:-2}" "${TO:-1948}"); do
  timeout 300 xvfb-run -a godot --path . -- \
    --at=$CX,$CY --zoom=4 --sortcube=$CX,$CY \
    --shot="$OUT/sweep_${CX}_${CY}.png" >/dev/null 2>&1
  /usr/bin/python3 - "$OUT/sweep_${CX}_${CY}.png" "$CX" "$CY" <<'PY'
import sys, zlib, struct
path, cx, cy = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = open(path, 'rb').read()
except OSError:
    print(f"{cx},{cy}\tNOSHOT"); sys.exit()
# minimal PNG reader: assumes 8-bit RGB/RGBA, the only thing save_png emits here
pos, w, h, bd, ct, idat = 8, 0, 0, 0, 0, b''
while pos < len(d):
    ln = struct.unpack('>I', d[pos:pos+4])[0]; typ = d[pos+4:pos+8]
    if typ == b'IHDR':
        w, h, bd, ct = struct.unpack('>IIBB', d[pos+8:pos+18])
    elif typ == b'IDAT':
        idat += d[pos+8:pos+8+ln]
    elif typ == b'IEND':
        break
    pos += 12 + ln
nch = {0:1, 2:3, 4:2, 6:4}[ct]
raw = zlib.decompress(idat)
stride = w * nch
prev = bytearray(stride); out = []
o = 0
for _ in range(h):
    f = raw[o]; o += 1
    line = bytearray(raw[o:o+stride]); o += stride
    if f == 1:
        for i in range(nch, stride): line[i] = (line[i] + line[i-nch]) & 255
    elif f == 2:
        for i in range(stride): line[i] = (line[i] + prev[i]) & 255
    elif f == 3:
        for i in range(stride):
            a = line[i-nch] if i >= nch else 0
            line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
    elif f == 4:
        for i in range(stride):
            a = line[i-nch] if i >= nch else 0
            b = prev[i]; c = prev[i-nch] if i >= nch else 0
            p = a + b - c
            pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = (line[i] + pr) & 255
    out.append(bytes(line)); prev = line
# the sortcube is pure magenta; allow a small tolerance for filtering
n = 0; border = 0; minx = miny = 1 << 30; maxx = maxy = -1
for y, line in enumerate(out):
    for x in range(w):
        i = x * nch
        r, g, b = line[i], line[i+1], line[i+2]
        if r > 200 and g < 60 and b > 200:
            n += 1
            if x == 0 or y == 0 or x == w-1 or y == h-1: border += 1
            minx = min(minx, x); maxx = max(maxx, x)
            miny = min(miny, y); maxy = max(maxy, y)
if n == 0:
    print(f"{cx},{cy}\t0\tborder=0\tbbox=-")
else:
    fill = n / float((maxx-minx+1) * (maxy-miny+1))
    print(f"{cx},{cy}\t{n}\tborder={border}\tbbox={maxx-minx+1}x{maxy-miny+1}\tfill={fill:.3f}")
PY
done
