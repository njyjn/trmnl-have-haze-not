#!/usr/bin/env python3
"""Render the plugin icon from the same coastline the map uses.

The icon should look like the screen, so it is drawn from
tools/data/sgp-adm0.geojson rather than traced by hand -- the outline is the
real one, and the halftone is the same idea the map uses to encode PSI.

    python3 tools/build_icon.py            # write docs/icon-*.png
    python3 tools/build_icon.py --variant panel --out docs/icon.png

Pure stdlib: the rasteriser supersamples point-in-polygon tests and the PNG
is written by hand, so there is no image library to install and the output is
byte-identical on any machine.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_map as bm  # noqa: E402

SIZE = 512
SS = 3  # supersampling factor per axis


# --------------------------------------------------------------------------
# PNG output (grayscale + alpha, so the icon sits on any background)
# --------------------------------------------------------------------------

def write_png(path: pathlib.Path, gray: bytearray, alpha: bytearray, size: int) -> None:
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter type 0
        base = y * size
        for x in range(size):
            rows.append(gray[base + x])
            rows.append(alpha[base + x])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 4, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def prepare_polys(min_area_frac: float = 0.0):
    """Polygons with bounding boxes, largest first, tiny islands dropped.

    Below roughly 100px the outlying islands stop reading as land and start
    reading as dirt, so the icon keeps only what survives being small.
    """
    polys = bm.load_polygons()
    scored = []
    for poly in polys:
        ring = poly[0]
        area = abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
                       - ring[(i + 1) % len(ring)][0] * ring[i][1]
                       for i in range(len(ring)))) / 2
        xs = [c[0] for c in ring]
        ys = [c[1] for c in ring]
        scored.append((area, poly, (min(xs), min(ys), max(xs), max(ys))))
    scored.sort(key=lambda s: -s[0])
    biggest = scored[0][0]
    return [(poly, bbox) for area, poly, bbox in scored
            if area >= biggest * min_area_frac]


def on_land_fast(lon: float, lat: float, prepared) -> bool:
    for poly, (x0, y0, x1, y1) in prepared:
        if lon < x0 or lon > x1 or lat < y0 or lat > y1:
            continue
        if bm.point_in_ring(lon, lat, poly[0]) and not any(
            bm.point_in_ring(lon, lat, hole) for hole in poly[1:]
        ):
            return True
    return False


def island_projection(size: int, margin: float, prepared):
    """Fit the island into the canvas, centred, preserving its true shape."""
    polys = [poly for poly, _ in prepared]
    lon0, lat0, lon1, lat1 = bm.bounds(polys)
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    span_x = (lon1 - lon0) * kx
    span_y = lat1 - lat0
    scale = (size - 2 * margin) / span_x
    drawn_h = span_y * scale
    off_y = (size - drawn_h) / 2

    def unproject(px: float, py: float):
        return (lon0 + (px - margin) / scale / kx, lat1 - (py - off_y) / scale)

    return unproject, drawn_h


def rounded_rect_alpha(x: float, y: float, size: int, radius: float) -> bool:
    if radius <= 0:
        return True
    lo, hi = radius, size - radius
    cx = lo if x < lo else (hi if x > hi else x)
    cy = lo if y < lo else (hi if y > hi else y)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


# --------------------------------------------------------------------------
# Variants
# --------------------------------------------------------------------------

SPACING = 13.0          # halftone lattice pitch, in canvas px
ROW_RATIO = math.sqrt(3) / 2


def halftone_ink(x: float, y: float, r: float, pitch: float = SPACING) -> bool:
    """Is this sample inside a dot of the hex lattice?"""
    if r <= 0:
        return False
    row = round(y / (pitch * ROW_RATIO))
    for dr in (-1, 0, 1):
        ry = (row + dr) * pitch * ROW_RATIO
        offset = (pitch / 2) if (row + dr) % 2 else 0.0
        col = round((x - offset) / pitch)
        for dc in (-1, 0, 1):
            cx = (col + dc) * pitch + offset
            if (x - cx) ** 2 + (y - ry) ** 2 <= r * r:
                return True
    return False


def make(variant: str, size: int = SIZE):
    """Return (gray, alpha) buffers for one design."""
    # Halftone inside the island dissolves into noise below ~100px. Putting
    # it in the air instead leaves the coastline as a solid silhouette, which
    # is the part that has to survive being shown at thumbnail size -- and
    # haze belongs in the sky rather than on the land anyway.
    detail = {"haze": 0.02, "panel": 0.0, "disc": 0.02, "solid": 0.02}[variant]
    prepared = prepare_polys(detail)

    margin = size * (0.065 if variant == "haze" else 0.085)
    unproject, drawn_h = island_projection(size, margin, prepared)
    corner = size * 0.18
    disc_r = size * 0.46
    centre = size / 2.0
    pitch = size / 17.0 if variant == "haze" else SPACING

    gray = bytearray(size * size)
    alpha = bytearray(size * size)

    for py in range(size):
        for px in range(size):
            ink = 0
            bg = 0
            for sy in range(SS):
                for sx in range(SS):
                    fx = px + (sx + 0.5) / SS
                    fy = py + (sy + 0.5) / SS

                    if variant == "disc":
                        inside = (fx - centre) ** 2 + (fy - centre) ** 2 <= disc_r * disc_r
                    else:
                        inside = rounded_rect_alpha(fx, fy, size, corner)
                    if not inside:
                        continue
                    bg += 1

                    lon, lat = unproject(fx, fy)
                    land = on_land_fast(lon, lat, prepared)

                    if variant in ("solid", "disc"):
                        if land:
                            ink += 1
                    elif variant == "panel":
                        if land:
                            t_ = min(1.0, max(0.0, (fx - margin) / (size - 2 * margin)))
                            if halftone_ink(fx, fy, pitch * (0.16 + 0.42 * t_), pitch):
                                ink += 1
                    elif variant == "haze":
                        if land:
                            ink += 1
                        else:
                            # Haze thickens downward, the way it sits over a
                            # skyline. Clear sky at the top, dense at the foot.
                            t_ = min(1.0, max(0.0, fy / size))
                            r = pitch * (0.04 + 0.30 * t_ * t_)
                            if halftone_ink(fx, fy, r, pitch):
                                ink += 1
                    else:
                        raise SystemExit("unknown variant: %s" % variant)

            i = py * size + px
            if bg == 0:
                alpha[i] = 0
                gray[i] = 0
                continue

            a = int(round(255 * bg / (SS * SS)))
            coverage = ink / bg
            value = 255 * coverage if variant == "disc" else 255 * (1.0 - coverage)
            alpha[i] = a
            gray[i] = max(0, min(255, int(round(value))))

    return gray, alpha


def downscale(gray: bytearray, alpha: bytearray, size: int, target: int):
    """Box filter, for judging legibility at directory thumbnail size."""
    factor = size // target
    g = bytearray(target * target)
    a = bytearray(target * target)
    for y in range(target):
        for x in range(target):
            gs = as_ = 0
            for dy in range(factor):
                row = (y * factor + dy) * size
                for dx in range(factor):
                    i = row + x * factor + dx
                    gs += gray[i] * alpha[i]
                    as_ += alpha[i]
            j = y * target + x
            a[j] = as_ // (factor * factor) // 255 * 255 if as_ else 0
            a[j] = min(255, as_ // (factor * factor))
            g[j] = (gs // as_) if as_ else 0
    return g, a


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=["haze", "panel", "solid", "disc"])
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--size", type=int, default=SIZE)
    args = ap.parse_args()

    variants = [args.variant] if args.variant else ["haze", "panel", "solid", "disc"]
    if args.out and len(variants) > 1:
        ap.error("--out takes a single --variant; otherwise every variant would "
                 "overwrite the same file")

    for v in variants:
        gray, alpha = make(v, args.size)
        # Resolve before reporting: a relative --out is relative to the caller's
        # cwd, not to the project, and relative_to() raises on anything outside.
        out = (args.out or (ROOT / "docs" / ("icon-%s.png" % v))).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        write_png(out, gray, alpha, args.size)
        try:
            shown = out.relative_to(ROOT)
        except ValueError:
            shown = out
        print("%-6s -> %s (%dx%d)" % (v, shown, args.size, args.size))

        if not args.out:
            sg, sa = downscale(gray, alpha, args.size, 64)
            small = ROOT / "docs" / ("icon-%s-64.png" % v)
            write_png(small, sg, sa, 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
