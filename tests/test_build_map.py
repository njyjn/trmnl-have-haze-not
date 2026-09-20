"""Geometry tests for tools/build_map.py and the block it writes.

The generated block is committed, so these tests guard two things: that the
generator's maths is right, and that what is currently in src/shared.liquid is
internally consistent with it.
"""

import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_map as bm  # noqa: E402

SHARED = (ROOT / "src" / "shared.liquid").read_text()


class TestPointInRing(unittest.TestCase):
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]

    def test_inside(self):
        self.assertTrue(bm.point_in_ring(5, 5, self.square))

    def test_outside(self):
        self.assertFalse(bm.point_in_ring(15, 5, self.square))
        self.assertFalse(bm.point_in_ring(-1, 5, self.square))
        self.assertFalse(bm.point_in_ring(5, 20, self.square))

    def test_hole_is_excluded(self):
        hole = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0)]
        polys = [[self.square, hole]]
        self.assertTrue(bm.on_land(1, 1, polys))
        self.assertFalse(bm.on_land(5, 5, polys))


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.polys = bm.load_polygons()
        self.project, self.unproject, self.height = bm.make_projection(self.polys)

    def test_round_trip(self):
        for lon, lat in [(103.8198, 1.3521), (103.70, 1.42), (104.02, 1.25)]:
            px, py = self.project(lon, lat)
            rlon, rlat = self.unproject(px, py)
            self.assertAlmostEqual(lon, rlon, places=6)
            self.assertAlmostEqual(lat, rlat, places=6)

    def test_fills_the_box(self):
        lon0, lat0, lon1, lat1 = bm.bounds(self.polys)
        left, _ = self.project(lon0, lat1)
        right, _ = self.project(lon1, lat0)
        self.assertAlmostEqual(left, bm.PAD, places=6)
        self.assertAlmostEqual(right, bm.WIDTH - bm.PAD, places=6)

    def test_north_is_up(self):
        _, y_north = self.project(103.82, 1.45)
        _, y_south = self.project(103.82, 1.25)
        self.assertLess(y_north, y_south)

    def test_aspect_ratio_is_undistorted(self):
        """A degree box must project to the same shape it occupies on the ground."""
        lon0, lat0, lon1, lat1 = bm.bounds(self.polys)
        x0, y0 = self.project(lon0, lat1)
        x1, y1 = self.project(lon1, lat0)
        import math

        kx = math.cos(math.radians((lat0 + lat1) / 2))
        ground = ((lon1 - lon0) * kx) / (lat1 - lat0)
        drawn = (x1 - x0) / (y1 - y0)
        self.assertAlmostEqual(ground, drawn, places=6)


class TestLandAndRegions(unittest.TestCase):
    def setUp(self):
        self.polys = bm.load_polygons()
        self.regions = bm.load_regions()

    def test_known_land_and_sea(self):
        self.assertTrue(bm.on_land(103.8198, 1.3521, self.polys), "central catchment")
        self.assertTrue(bm.on_land(103.8607, 1.2830, self.polys), "Marina Bay")
        self.assertFalse(bm.on_land(104.05, 1.30, self.polys), "open sea east of SG")
        self.assertFalse(bm.on_land(103.75, 1.10, self.polys), "open sea south of SG")

    def test_each_reporting_point_maps_to_itself(self):
        import math

        lat0, lat1 = bm.bounds(self.polys)[1], bm.bounds(self.polys)[3]
        kx = math.cos(math.radians((lat0 + lat1) / 2))
        for name, lon, lat in self.regions:
            self.assertEqual(name, bm.nearest_region(lon, lat, self.regions, kx))


class TestGeneratedBlock(unittest.TestCase):
    """The committed block must agree with its inputs."""

    def setUp(self):
        self.map_w = int(re.search(r"assign map_w = (\d+)", SHARED).group(1))
        self.map_h = int(re.search(r"assign map_h = (\d+)", SHARED).group(1))
        self.layers = re.search(r'assign map_layers = "([^"]*)"', SHARED).group(1)
        self.labels = re.search(r'assign map_labels = "([^"]*)"', SHARED).group(1)
        self.coast = re.search(r'assign map_coast = "([^"]*)"', SHARED).group(1)
        self.region_names = [r["name"] for r in json.loads((ROOT / "tools" / "data" / "psi-regions.json").read_text())]

    def test_every_region_has_a_layer(self):
        names = [chunk.split("|")[0] for chunk in self.layers.split(";;")]
        self.assertEqual(names, self.region_names)

    def test_every_region_has_a_label(self):
        names = [chunk.split("|")[0] for chunk in self.labels.split(";;")]
        self.assertEqual(names, self.region_names)

    def test_dots_are_inside_the_viewbox(self):
        total = 0
        for chunk in self.layers.split(";;"):
            points = chunk.split("|")[1].split()
            self.assertTrue(points, "region %s has no dots" % chunk.split("|")[0])
            for p in points:
                x, y = (int(v) for v in p.split(","))
                self.assertTrue(0 <= x <= self.map_w, "x %d out of range" % x)
                self.assertTrue(0 <= y <= self.map_h, "y %d out of range" % y)
                total += 1
        self.assertGreater(total, 400, "lattice looks too sparse to read as a map")

    def test_labels_are_inside_the_viewbox(self):
        for chunk in self.labels.split(";;"):
            x, y = (int(v) for v in chunk.split("|")[1].split(","))
            self.assertTrue(0 <= x <= self.map_w)
            self.assertTrue(0 <= y <= self.map_h)

    def test_coast_path_is_wellformed(self):
        self.assertTrue(self.coast.startswith("M"))
        self.assertEqual(self.coast.count("M"), self.coast.count("Z"))
        self.assertEqual(self.coast.count("Z"), 12, "one subpath per island ring")


def liquid_list(name):
    """Pull a `{%- assign name = 'a,b,c' | split: ',' -%}` list out of the Liquid."""
    m = re.search(r"assign %s = '([^']*)' \| split: '([^']*)'" % name, SHARED)
    if not m:
        return None
    return m.group(1).split(m.group(2))


def liquid_lists(name):
    """Every definition of a name -- the scales each define their own."""
    return [m.group(1).split(m.group(2)) for m in
            re.finditer(r"assign %s = '([^']*)' \| split: '([^']*)'" % name, SHARED)]


class TestBreakpointTables(unittest.TestCase):
    """The conversion tables are the whole basis of the derived numbers.

    EPA's values are the 2024 revision (Good tops at 9.0, not the 12.0 it used
    to) from aqs.epa.gov's published aqi_breakpoints table. NEA's PM2.5
    sub-index breakpoints are from their PSI computation document, and were
    checked against live readings: they reproduce NEA's own pm25_sub_index to
    within the rounding its API applies to the concentration.
    """

    def segments(self, name):
        raw = liquid_list(name)
        self.assertIsNotNone(raw, "%s table missing" % name)
        return [tuple(float(v) for v in seg.split(",")) for seg in raw]

    def test_epa_pm25_matches_the_published_table(self):
        self.assertEqual(self.segments("epa_pm25"), [
            (0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
            (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500),
        ])

    def test_nea_pm25_matches_the_published_table(self):
        self.assertEqual(self.segments("nea_pm25"), [
            (0, 12, 0, 50), (12, 55, 50, 100), (55, 150, 100, 200),
            (150, 250, 200, 300), (250, 500, 300, 500),
        ])

    def test_segments_are_contiguous_and_rising(self):
        for name in ("epa_pm25", "nea_pm25"):
            segs = self.segments(name)
            for (clo, chi, ilo, ihi) in segs:
                self.assertLess(clo, chi, "%s: empty concentration span" % name)
                self.assertLess(ilo, ihi, "%s: empty index span" % name)
            for a, b in zip(segs, segs[1:]):
                self.assertLessEqual(a[1], b[0], "%s: overlapping segments" % name)
                self.assertLessEqual(a[3], b[2], "%s: index goes backwards" % name)


class TestScaleDefinitions(unittest.TestCase):
    """Each scale defines its own bands, and nothing may assume a count --
    US AQI has six where PSI and PM2.5 have five."""

    def setUp(self):
        self.labels = liquid_lists("band_labels")
        self.short = liquid_lists("band_short")
        self.advice = liquid_lists("band_advice")
        self.edges = liquid_lists("band_edges")
        self.radii = liquid_lists("band_radii")

    def test_three_scales_are_defined(self):
        self.assertEqual(len(self.labels), 3, "expected PSI, PM2.5 and US AQI")

    def test_each_scale_is_internally_consistent(self):
        for i, labels in enumerate(self.labels):
            n = len(labels)
            self.assertEqual(len(self.short[i]), n, "scale %d: short labels differ" % i)
            self.assertEqual(len(self.advice[i]), n, "scale %d: advice differs" % i)
            self.assertEqual(len(self.edges[i]), n - 1,
                             "scale %d: needs one fewer edge than band" % i)

    def test_edges_rise(self):
        for edges in self.edges:
            nums = [float(e) for e in edges]
            self.assertEqual(nums, sorted(nums))
            self.assertEqual(len(set(nums)), len(nums))

    def test_a_ramp_exists_for_every_band_count(self):
        counts = {len(l) for l in self.labels}
        ramps = {len(r) for r in self.radii}
        self.assertTrue(counts <= ramps,
                        "band counts %s have no dot ramp (ramps: %s)" % (counts, ramps))

    def test_every_ramp_rises_and_stays_readable(self):
        import math
        spacing = int(re.search(r"assign map_dot_spacing = (\d+)", SHARED).group(1))
        cell = spacing * spacing * math.sqrt(3) / 2
        for radii in self.radii:
            nums = [float(r) for r in radii]
            self.assertEqual(nums, sorted(nums))
            self.assertEqual(len(set(nums)), len(nums), "two bands would look identical")
            for r in nums:
                self.assertLess(math.pi * r * r / cell, 0.5, "band covers over half its cell")
            for a, b in zip(nums, nums[1:]):
                self.assertGreater(b * b / (a * a), 1.25,
                                   "step from r=%s to r=%s is too subtle" % (a, b))

    def test_map_and_legend_share_the_ramp(self):
        full = (ROOT / "src" / "full.liquid").read_text()
        self.assertIn("band_radii[forloop.index0]", full, "legend must index band_radii")
        self.assertIn("band_radii[bidx]", SHARED, "map must index band_radii")

    def test_map_and_headline_band_off_the_same_edges(self):
        self.assertIn("for e in band_edges", SHARED)
        self.assertGreaterEqual(SHARED.count("for e in band_edges"), 2,
                                "headline and map must both band off band_edges")


class TestSvgTypography(unittest.TestCase):
    """Bare <text> inherits no framework font; the default fallback is serif."""

    def test_map_text_declares_a_font(self):
        block = re.search(r"\.aq-map text, \.aq-legend text \{([^}]*)\}", SHARED)
        self.assertIsNotNone(block, "map/legend text must set its own font-family")
        self.assertIn("font-family", block.group(1))


if __name__ == "__main__":
    unittest.main()
