"""Guards on how the layouts size themselves.

The plugin has to render on every TRMNL panel, not just the one it was drawn
on: OG is 800x480 logical px, X is 1040x780 (1872x1404 at --pixel-ratio 1.8),
and the BYOD list spans everything between. Two mistakes have already been
made here and both are invisible until you render at another size:

  * a column width in px, which pinned the map to 57% of an OG and 44% of an X
  * nesting .layout, which is hard-sized to the full screen via --screen-w /
    --screen-h, so an inner one overflows its parent and blanks the panel
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
LAYOUTS = ("full", "half_horizontal", "half_vertical", "quadrant")
SHARED = (SRC / "shared.liquid").read_text()
STYLE = re.search(r"<style>(.*?)</style>", SHARED, re.S).group(1)


def rules(prefix):
    """Every CSS declaration block whose selector mentions `prefix`."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", STYLE):
        if prefix in sel:
            out.append((sel.strip(), body))
    return out


def spans(cls):
    """{breakpoint prefix: span} for one grid cell's class list."""
    out = {}
    for prefix, n in re.findall(r"(?:^|\s)((?:[a-z]+:)*)col--span-(\d+)", cls):
        out[prefix] = int(n)
    return out


def cells(text):
    """Class lists of every grid cell (anything with a col--span)."""
    return [c for c in re.findall(r'class="([^"]*)"', text) if "col--span-" in c]


class TestColumnsAreProportional(unittest.TestCase):
    """Columns come from the framework grid, so they are fractions of the
    panel by construction. What can still go wrong is spans that do not add
    up, which leaves a gap or wraps a column onto a second row."""

    def test_full_spans_fill_the_grid_at_each_size(self):
        full = (SRC / "full.liquid").read_text()
        self.assertIn("grid grid--cols-12", full)
        map_cell, side_cell = [spans(c) for c in cells(full)]
        self.assertEqual(map_cell[""] + side_cell[""], 12, "OG split does not fill 12")
        self.assertEqual(map_cell["lg:"] + side_cell["lg:"], 12, "X split does not fill 12")
        self.assertGreater(map_cell["lg:"], map_cell[""], "the X's extra width should go to the map")

    def test_half_horizontal_spans_fill_the_grid(self):
        text = (SRC / "half_horizontal.liquid").read_text()
        self.assertIn("grid grid--cols-3", text)
        self.assertEqual(sum(spans(c)[""] for c in cells(text)), 3)

    def test_grid_cells_do_not_use_fixed_width_utilities(self):
        for name in LAYOUTS:
            text = (SRC / ("%s.liquid" % name)).read_text()
            for c in cells(text):
                self.assertNotRegex(c, r"\bw--\d+\b",
                                    "%s.liquid pins a column with a fixed-width utility" % name)

    def test_cells_stretch_across_only(self):
        """flex--stretch stretches both axes: it gives every child flex:1 1 0,
        which splits the column height evenly and shrinks the map to fit.
        flex--stretch-x is the cross-axis-only one."""
        for name in LAYOUTS:
            text = (SRC / ("%s.liquid" % name)).read_text()
            self.assertNotRegex(text, r"\bflex--stretch(?![-\w])",
                                "%s.liquid uses both-axis flex--stretch" % name)


class TestStyleIsSvgOnly(unittest.TestCase):
    """Layout is framework classes; the <style> block is only for the insides
    of the SVGs, which framework classes cannot reach."""

    def test_every_rule_targets_an_svg(self):
        for sel, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)):
            for part in sel.split(","):
                self.assertRegex(part.strip(), r"^\.aq-(map|legend|spark)\b",
                                 "%r is layout CSS; use framework classes" % part.strip())

    def test_no_media_queries(self):
        self.assertNotIn("@media", STYLE)


class TestLayoutIsNotNested(unittest.TestCase):
    """.layout is width:var(--screen-w);height:var(--screen-h)."""

    def test_one_layout_element_per_file(self):
        for name in LAYOUTS:
            text = (SRC / ("%s.liquid" % name)).read_text()
            self.assertEqual(
                text.count('class="layout'), 1,
                "%s.liquid must have exactly one .layout element" % name,
            )

    def test_shared_declares_none(self):
        self.assertNotIn('class="layout', SHARED)


class TestSvgsScale(unittest.TestCase):
    """An SVG with a pixel width cannot grow with the panel."""

    def test_svgs_use_viewbox_and_relative_width(self):
        found = 0
        for name in LAYOUTS + ("shared",):
            text = (SRC / ("%s.liquid" % name)).read_text()
            for tag in re.findall(r"<svg\b[^>]*>", text):
                found += 1
                self.assertIn("viewBox", tag, "svg in %s.liquid has no viewBox" % name)
                width = re.search(r'\bwidth="([^"]+)"', tag)
                self.assertIsNotNone(width, "svg in %s.liquid has no width" % name)
                self.assertTrue(
                    width.group(1).endswith("%"),
                    "svg in %s.liquid has a fixed width %r" % (name, width.group(1)),
                )
                self.assertNotRegex(
                    tag, r'\bheight="\d',
                    "svg in %s.liquid pins a pixel height; let the aspect drive it" % name,
                )
        self.assertGreaterEqual(found, 3)

    def test_stretched_svgs_pin_their_stroke(self):
        """preserveAspectRatio="none" scales stroke width with the box."""
        for name in LAYOUTS:
            text = (SRC / ("%s.liquid" % name)).read_text()
            for svg in re.findall(r"<svg\b[^>]*preserveAspectRatio=\"none\".*?</svg>", text, re.S):
                for shape in re.findall(r"<(?:polyline|line|path)\b[^>]*>", svg):
                    self.assertIn(
                        "non-scaling-stroke", shape,
                        "%s.liquid: stretched shape needs vector-effect" % name,
                    )


class TestConditionalDetail(unittest.TestCase):
    """The X has height the OG does not; the per-region table fills it."""

    def test_region_table_only_on_the_x(self):
        full = (SRC / "full.liquid").read_text()
        block = re.search(r'<div class="hidden lg:block">(.*?)\{%- endfor -%\}', full, re.S)
        self.assertIsNotNone(block, "region table is not gated on lg:")
        self.assertIn("pm10_twenty_four_hourly", block.group(1))


class TestPortrait(unittest.TestCase):
    """Portrait is a review requirement (OG landscape, X landscape, X portrait)
    and it is the orientation nothing else exercises."""

    def setUp(self):
        self.full = (SRC / "full.liquid").read_text()

    def test_map_takes_the_full_width(self):
        map_cell = spans(cells(self.full)[0])
        self.assertEqual(map_cell.get("lg:portrait:"), 12)

    def test_side_column_steps_aside(self):
        self.assertIn("portrait:hidden", cells(self.full)[1])

    def test_readings_lead_the_stack(self):
        """The grid cannot reorder, so the readings are emitted again above
        it, shown only in portrait."""
        row = self.full.index('<div class="hidden portrait:block')
        grid = self.full.index('<div class="grid grid--cols-12')
        self.assertLess(row, grid)
        for block in ("headline_block", "pollutant_block", "fc_block"):
            self.assertEqual(self.full.count("{{ %s }}" % block), 2,
                             "%s should render beside the map and in the portrait row" % block)


class TestOneBitLegibility(unittest.TestCase):
    """Grey labels dither away on a 1-bit panel; the framework has a class
    that forces them black there, and review asks for it."""

    def test_every_grey_label_is_forced_black_on_1bit(self):
        for name in LAYOUTS:
            text = (SRC / ("%s.liquid" % name)).read_text()
            for m in re.finditer(r'class="([^"]*label--gray-out[^"]*)"', text):
                self.assertIn("1bit:text--black", m.group(1),
                              "%s.liquid has a grey label that vanishes at 1-bit" % name)


if __name__ == "__main__":
    unittest.main()
