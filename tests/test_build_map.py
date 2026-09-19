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


class TestBandThresholds(unittest.TestCase):
    """NEA's PSI bands are the scale the whole screen agrees on."""

    def test_liquid_uses_the_published_boundaries(self):
        chain = re.findall(r"home_psi <= (\d+)", SHARED)
        self.assertEqual(chain, ["50", "100", "200", "300"])

    def test_liquid_band_labels(self):
        for label in ("Good", "Moderate", "Unhealthy", "Very Unhealthy", "Hazardous"):
            self.assertIn("'%s'" % label, SHARED)

    def test_map_uses_the_same_boundaries(self):
        chain = re.findall(r"rpsi <= (\d+)", SHARED)
        self.assertEqual(chain, ["50", "100", "200", "300"])


class TestDotRamp(unittest.TestCase):
    """Dot radius is the map's only quantitative channel."""

    def setUp(self):
        raw = re.search(r"assign band_radii = '([^']*)'", SHARED).group(1)
        self.radii = [float(v) for v in raw.split(",")]

    def test_one_radius_per_band(self):
        self.assertEqual(len(self.radii), 5)

    def test_radii_increase_with_severity(self):
        self.assertEqual(self.radii, sorted(self.radii))
        self.assertEqual(len(set(self.radii)), 5, "two bands would look identical")

    def test_ink_stays_below_half_coverage(self):
        """Past ~50% ink the lattice reads as a solid block, not a shade."""
        import math

        spacing = int(re.search(r"assign map_dot_spacing = (\d+)", SHARED).group(1))
        cell = spacing * spacing * math.sqrt(3) / 2
        for band, r in enumerate(self.radii, start=1):
            coverage = math.pi * r * r / cell
            self.assertLess(coverage, 0.5, "band %d covers %.0f%% of its cell" % (band, coverage * 100))

    def test_bands_are_distinguishable(self):
        """Each step must add enough ink to be visible on a 1-bit panel."""
        for a, b in zip(self.radii, self.radii[1:]):
            self.assertGreater(b * b / (a * a), 1.4, "step from r=%s to r=%s is too subtle" % (a, b))

    def test_map_and_legend_share_the_list(self):
        full = (ROOT / "src" / "full.liquid").read_text()
        self.assertIn("band_radii[forloop.index0]", full, "legend must index band_radii")
        self.assertIn("band_radii[band_i]", SHARED, "map must index band_radii")
        for src in (full, SHARED):
            self.assertNotRegex(src, r"assign \w*_?r\w* = band[_ ]?\w* \| times:",
                                "radius formula duplicated instead of shared")


class TestSvgTypography(unittest.TestCase):
    """Bare <text> inherits no framework font; the default fallback is serif."""

    def test_map_text_declares_a_font(self):
        block = re.search(r"\.aq-map text, \.aq-legend text \{([^}]*)\}", SHARED)
        self.assertIsNotNone(block, "map/legend text must set its own font-family")
        self.assertIn("font-family", block.group(1))


if __name__ == "__main__":
    unittest.main()
