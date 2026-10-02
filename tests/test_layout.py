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


def spans(cls):
    """{breakpoint prefix: span} for one grid cell's class list."""
    out = {}
    for prefix, n in re.findall(r"(?:^|\s)((?:[a-z]+:)*)col--span-(\d+)", cls):
        out[prefix] = int(n)
    return out


def cells(text):
    """Class lists of the main grid's cells (anything with a col--span).

    In full.liquid the portrait-only readings row above the grid has cells
    of its own, so start from the main grid."""
    main = text.find('class="grid grid--cols-12')
    if main >= 0:
        text = text[main:]
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
        headline, extras, rest = [spans(c) for c in cells(text)]
        self.assertEqual(headline[""] + rest[""], 3, "base split does not fill 3")
        # X portrait: the pollutant readings sit beside the headline, and
        # exist in no other layout (no base span, so `hidden` keeps them out).
        self.assertNotIn("", extras)
        self.assertEqual(headline["lg:portrait:"] + extras["lg:portrait:"], 3,
                         "X portrait headline row does not fill 3")

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


class TestNoStyleBlock(unittest.TestCase):
    """Layout is framework classes, and the SVGs carry their own styling as
    presentation attributes, so no view needs a <style> block. Review's
    automated check flags one."""

    def test_no_style_block_anywhere(self):
        for name in LAYOUTS + ("shared",):
            text = (SRC / ("%s.liquid" % name)).read_text()
            self.assertNotIn("<style", text, "%s.liquid has a <style> block" % name)

    def test_svgs_name_their_font(self):
        """Presentation attributes cannot read var(--value-font-family), so
        the font is spelled out on each SVG that draws text."""
        for name in ("full", "shared"):
            text = (SRC / ("%s.liquid" % name)).read_text()
            for tag in re.findall(r"<svg\b[^>]*>", text):
                if 'preserveAspectRatio="none"' in tag:
                    continue  # no text
                self.assertIn('font-family="Inter', tag, "%s.liquid: svg without a font" % name)


class TestDarkMode(unittest.TestCase):
    """Dark mode swaps the framework's black and white. A hard-coded #000
    in an SVG vanishes on the black background, so SVG ink follows
    currentColor and halos use text--white (the background in both modes)."""

    def test_no_hard_coded_black_or_white(self):
        for name in LAYOUTS + ("shared",):
            text = (SRC / ("%s.liquid" % name)).read_text()
            text = re.sub(r'data:image/[^"]+', "", text)
            self.assertNotRegex(text, r'(?i)(fill|stroke)="#(000|fff)(000|fff)?"',
                                "%s.liquid hard-codes a colour dark mode cannot swap" % name)

    def test_halos_use_the_background_colour(self):
        halos = re.findall(r'<text class="text--white"[^>]*stroke="currentColor"', SHARED)
        self.assertEqual(len(halos), 2, "expected a text--white halo for the name and the value")
        self.assertNotIn("dark:text--black", SHARED,
                         "dark mode already swaps text--white to black; the override undoes it")


class TestLintInlineStyleBudget(unittest.TestCase):
    """Mirrors trmnlp lint's LimitedInlineStyles: it counts raw occurrences
    of these property names anywhere in the markup, comments included, and
    fails above six. SVG presentation attributes count too."""

    PROPERTIES = ("justify-content", "padding", "margin", "background-color",
                  "border-radius", "text-align", "object-fit", "font-size")

    def test_within_budget(self):
        markup = "".join((SRC / ("%s.liquid" % n)).read_text() for n in LAYOUTS + ("shared",))
        count = sum(markup.count(p) for p in self.PROPERTIES)
        self.assertLessEqual(count, 6, "trmnlp lint allows 6; markup has %d" % count)


class TestMashupsUseTheX(unittest.TestCase):
    """Review asked for the mashup views to use the X's extra room: type a
    size up (lg:), and content that only exists there. The OG must not gain
    any of it, and the full view keeps the sizes it was approved with."""

    def view(self, name):
        return (SRC / ("%s.liquid" % name)).read_text()

    def test_half_views_step_the_headline_up_on_the_x(self):
        for name in ("half_horizontal", "half_vertical"):
            self.assertIn("value--xxlarge lg:value--xxxlarge", self.view(name),
                          "%s headline does not scale on the X" % name)
            self.assertIn("title--small lg:title--base", self.view(name))

    def test_quadrant_extras_are_x_only(self):
        q = self.view("quadrant")
        for block in ("{{ region_row }}", "{{ home_band_advice }}", "{{ pollutant_block_lg }}"):
            before = q[:q.index(block)]
            wrapper = before[before.rindex('<div class="hidden'):]
            self.assertRegex(wrapper, r'<div class="hidden lg:(portrait:)?block',
                             "%s is not gated on the X" % block)
        # the pollutant readings only fit the taller, rotated quarter
        before = q[:q.index("{{ pollutant_block_lg }}")]
        self.assertIn("lg:portrait:block", before[before.rindex('<div class="hidden'):])

    def test_region_row_fits_five_across_in_the_rotated_quarter(self):
        """value--base clips at five across in 370px; small fits."""
        self.assertIn("lg:value--base lg:portrait:value--small", SHARED)

    def test_full_view_keeps_its_sizes(self):
        full = self.view("full")
        self.assertNotIn("_lg }}", full, "full.liquid should use the unscaled blocks")
        for name in ("fc_block", "pollutant_block", "headline_block"):
            a = SHARED.index("{%- capture " + name + " -%}")
            body = SHARED[a:SHARED.index("{%- endcapture -%}", a)]
            self.assertNotIn("lg:label--base", body, "%s is shared with full and must stay unscaled" % name)


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
        """In any portrait, not just the X's: the OG rotated is a real
        orientation too, and a lg:-only rule left its map at 7/12."""
        map_cell = spans(cells(self.full)[0])
        self.assertEqual(map_cell.get("portrait:"), 12, "OG portrait keeps the landscape span")
        self.assertEqual(map_cell.get("lg:portrait:"), 12, "X portrait keeps the lg: span")

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
            for m in re.finditer(r'class="([^"]*label--gray[^"]*)"', text):
                self.assertIn("1bit:text--black", m.group(1),
                              "%s.liquid has a grey label that vanishes at 1-bit" % name)


if __name__ == "__main__":
    unittest.main()
