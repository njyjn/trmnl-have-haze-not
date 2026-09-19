#!/usr/bin/env python3
"""Bake Singapore's coastline and a halftone dot lattice into src/shared.liquid.

The TRMNL device renders Liquid against a polled JSON payload and nothing else --
there is no server in this plugin, so every piece of geometry has to be a
constant in the template. This script turns two static inputs

    tools/data/sgp-adm0.geojson   coastline (geoBoundaries ADM0, ODbL)
    tools/data/psi-regions.json   NEA's five PSI reporting points

into three Liquid assigns that get written between markers in src/shared.liquid:

    map_coast     one SVG path covering every island
    map_layers    "region|x,y x,y ..." for each region, ";;"-separated
    map_labels    "region|x,y" for each region's label anchor

Each lattice dot is assigned to the nearest PSI reporting point, so the five
layers are the Voronoi cells of NEA's stations clipped to land. At render time
the template only has to pick a dot radius per layer from that region's PSI.

Run `python3 tools/build_map.py` after changing any input or tuning constant;
the generated block is committed so the plugin needs no build step to deploy.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEOJSON = ROOT / "tools" / "data" / "sgp-adm0.geojson"
REGIONS = ROOT / "tools" / "data" / "psi-regions.json"
SHARED = ROOT / "src" / "shared.liquid"

BEGIN = "{%- comment -%} BEGIN GENERATED MAP -- tools/build_map.py {%- endcomment -%}"
END = "{%- comment -%} END GENERATED MAP {%- endcomment -%}"

# Drawing box in TRMNL pixels. The aspect ratio is derived from the bounding
# box below so the island is never stretched; HEIGHT is computed, not chosen.
WIDTH = 430.0
PAD = 4.0

# Hex-packed lattice: alternate rows shift half a step, rows sit SPACING*sin(60)
# apart. Halftone dots read far better than grey fills on a 1-bit panel.
SPACING = 8.0
ROW_RATIO = math.sqrt(3) / 2


def load_polygons() -> list[list[list[tuple[float, float]]]]:
    """Return [[outer_ring, *hole_rings], ...] as (lon, lat) tuples."""
    geom = json.loads(GEOJSON.read_text())["features"][0]["geometry"]
    raw = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return [[[(float(x), float(y)) for x, y in ring] for ring in poly] for poly in raw]


def load_regions() -> list[tuple[str, float, float]]:
    data = json.loads(REGIONS.read_text())
    return [
        (r["name"], float(r["labelLocation"]["longitude"]), float(r["labelLocation"]["latitude"]))
        for r in data
    ]


def bounds(polys) -> tuple[float, float, float, float]:
    xs = [x for poly in polys for ring in poly for x, _ in ring]
    ys = [y for poly in polys for ring in poly for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def make_projection(polys):
    """Equirectangular lon/lat -> SVG pixels, scaled to fit WIDTH.

    Singapore sits at ~1.35 deg N where a degree of longitude is 99.97% of a
    degree of latitude, so the cosine correction is below half a pixel across
    the whole island. It is applied anyway to keep the maths honest.
    """
    lon0, lat0, lon1, lat1 = bounds(polys)
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    span_x = (lon1 - lon0) * kx
    span_y = lat1 - lat0
    scale = (WIDTH - 2 * PAD) / span_x
    height = span_y * scale + 2 * PAD

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (
            PAD + (lon - lon0) * kx * scale,
            PAD + (lat1 - lat) * scale,  # SVG y grows downward
        )

    def unproject(px: float, py: float) -> tuple[float, float]:
        return (lon0 + (px - PAD) / scale / kx, lat1 - (py - PAD) / scale)

    return project, unproject, height


def point_in_ring(x: float, y: float, ring) -> bool:
    """Even-odd ray cast along +x."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                inside = not inside
    return inside


def on_land(lon: float, lat: float, polys) -> bool:
    for poly in polys:
        if point_in_ring(lon, lat, poly[0]) and not any(
            point_in_ring(lon, lat, hole) for hole in poly[1:]
        ):
            return True
    return False


def nearest_region(lon: float, lat: float, regions, kx: float) -> str:
    best, best_d = regions[0][0], float("inf")
    for name, rlon, rlat in regions:
        d = ((lon - rlon) * kx) ** 2 + (lat - rlat) ** 2
        if d < best_d:
            best, best_d = name, d
    return best


def coast_path(polys, project) -> str:
    parts = []
    for poly in polys:
        for ring in poly:
            pts = [project(lon, lat) for lon, lat in ring]
            head = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
            tail = "".join(f"L{x:.1f},{y:.1f}" for x, y in pts[1:])
            parts.append(head + tail + "Z")
    return "".join(parts)


def ascii_preview(dots, height, regions) -> str:
    """Terminal sanity check -- the island should be recognisable."""
    cols, rows = 78, 22
    glyph = {name: ch for (name, *_), ch in zip(regions, "NSEWC")}
    grid = [[" "] * cols for _ in range(rows)]
    for name, x, y in dots:
        c = min(cols - 1, int(x / WIDTH * cols))
        r = min(rows - 1, int(y / height * rows))
        grid[r][c] = glyph[name]
    return "\n".join("|" + "".join(row) + "|" for row in grid)


def main() -> int:
    polys = load_polygons()
    regions = load_regions()
    project, unproject, height = make_projection(polys)
    lat0, lat1 = bounds(polys)[1], bounds(polys)[3]
    kx = math.cos(math.radians((lat0 + lat1) / 2))

    row_step = SPACING * ROW_RATIO
    layers: dict[str, list[str]] = {name: [] for name, _, _ in regions}
    dots: list[tuple[str, float, float]] = []

    row = 0
    y = PAD
    while y <= height - PAD:
        offset = (SPACING / 2) if row % 2 else 0.0
        x = PAD + offset
        while x <= WIDTH - PAD:
            lon, lat = unproject(x, y)
            if on_land(lon, lat, polys):
                name = nearest_region(lon, lat, regions, kx)
                layers[name].append(f"{x:.0f},{y:.0f}")
                dots.append((name, x, y))
            x += SPACING
        y += row_step
        row += 1

    empty = [name for name, pts in layers.items() if not pts]
    if empty:
        print(f"error: no land dots for region(s): {', '.join(empty)}", file=sys.stderr)
        return 1

    map_layers = ";;".join(f"{name}|{' '.join(layers[name])}" for name, _, _ in regions)
    map_labels = ";;".join(
        "{}|{:.0f},{:.0f}".format(name, *project(lon, lat)) for name, lon, lat in regions
    )

    block = "\n".join(
        [
            BEGIN,
            "{%- comment -%}",
            "  Coastline: geoBoundaries gbOpen SGP ADM0 (ODbL), simplified.",
            "  Dot lattice: land sampled on a hex grid, each dot assigned to its",
            "  nearest NEA PSI reporting point. Regenerate with tools/build_map.py.",
            "{%- endcomment -%}",
            "{{%- assign map_w = {} -%}}".format(round(WIDTH)),
            "{{%- assign map_h = {} -%}}".format(round(height)),
            "{{%- assign map_dot_spacing = {} -%}}".format(round(SPACING)),
            '{{%- assign map_coast = "{}" -%}}'.format(coast_path(polys, project)),
            '{{%- assign map_layers = "{}" | split: ";;" -%}}'.format(map_layers),
            '{{%- assign map_labels = "{}" | split: ";;" -%}}'.format(map_labels),
            END,
        ]
    )

    text = SHARED.read_text()
    if BEGIN not in text or END not in text:
        print(f"error: markers missing from {SHARED}", file=sys.stderr)
        return 1
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    SHARED.write_text(head + block + tail)

    counts = ", ".join(f"{name}={len(layers[name])}" for name, _, _ in regions)
    print(f"map {round(WIDTH)}x{round(height)}px  spacing={SPACING:g}px  dots={len(dots)}  ({counts})")
    print(f"coast path {len(coast_path(polys, project))} chars over {sum(len(p) for p in polys)} rings")
    print(ascii_preview(dots, height, regions))
    print(f"wrote generated block to {SHARED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
