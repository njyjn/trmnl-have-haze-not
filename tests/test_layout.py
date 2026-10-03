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
        lead, rest, cities = [spans(c) for c in cells(text)]
        # landscape: headline + bars in two thirds, regions + forecast in one,
        # set apart by the wide gap
        self.assertEqual((lead[""], rest[""]), (8, 4))
        self.assertIn("landscape:gap--large", text)
        # rotated: each takes a full row
        self.assertEqual((lead["portrait:"], rest["portrait:"]), (12, 12))
        # the capitals run along the bottom on the X, in both orientations:
        # no base span, so `hidden` keeps them out of the OG's grid
        self.assertEqual(cities, {"lg:": 12})
        self.assertIn("hidden", cells(text)[2].split())
        self.assertNotIn("lg:portrait:hidden", cells(text)[2])
        # rotated, the X sets the regions and the forecast side by side to
        # make room for that row; everywhere else they stack
        self.assertIn("lg:portrait:grid lg:portrait:grid--cols-2", cells(text)[1])
        self.assertIn('<div class="border--h-5 lg:portrait:hidden"></div>', text)

    def test_half_horizontal_headline_is_as_wide_as_its_digits(self):
        """A fixed column for the headline clipped the number in Chrome,
        where the same digits set ~10px wider than in the Firefox render.
        The headline and the bars share a flex row instead: the headline
        takes its content's width and the bars grow into the rest."""
        text = (SRC / "half_horizontal.liquid").read_text()
        row = re.search(r'<div class="(col--span-8[^"]*)">\s*<div class="flex flex--col flex--left">'
                        r'.*?</div>\s*</div>\s*<div class="grow">\{\{ pollutant_bars \}\}</div>', text, re.S)
        self.assertIsNotNone(row, "headline and bars are not one flex row")
        for cls in ("flex", "flex--row", "gap--large"):
            self.assertIn(cls, row.group(1).split())
        # the framework's .content wrapper is what clipped it (overflow: hidden)
        self.assertNotIn('class="content"', text[row.start():row.end()].split("{{ pollutant_bars }}")[0])

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
        for name in ("half_horizontal", "half_vertical", "quadrant"):
            self.assertIn("value--xxlarge lg:value--xxxlarge", self.view(name),
                          "%s headline does not scale on the X" % name)
            self.assertIn("title--small lg:title--base", self.view(name))

    def test_quadrant_extras_are_x_only(self):
        q = self.view("quadrant")
        def wrapper(block):
            before = q[:q.index(block)]
            return before[before.rindex('<div class="hidden'):].split(">")[0]
        self.assertIn("hidden lg:block", wrapper("{{ home_band_advice }}"))
        # the five regions fit the X's quarter in both orientations
        self.assertEqual(wrapper("{{ region_row }}"), '<div class="hidden lg:block w--full"')

    def test_stacked_bars_except_where_height_is_short(self):
        """The same five pollutants everywhere. The name sits on its own
        line above the bar by default; three slots have no height for that
        and set the name beside the bar instead."""
        def holder(view, capture):
            text = self.view(view)
            out = []
            for m in re.finditer(re.escape("{{ %s }}" % capture), text):
                before = text[:m.start()]
                out.append(before[before.rindex('<div class="'):].split('"')[1])
            return out
        # OG full landscape: inline in the side column; the X's is stacked
        self.assertEqual(holder("full", "pollutant_bars_inline"), ["lg:hidden"])
        self.assertIn("hidden lg:block", holder("full", "pollutant_bars"))
        self.assertEqual(len(holder("full", "pollutant_bars")), 2)   # + the portrait row
        # X half_vertical rotated: inline; the OG rotated and both landscapes are stacked
        self.assertEqual(holder("half_vertical", "pollutant_bars_inline"), ["hidden lg:block"])
        hv = holder("half_vertical", "pollutant_bars")
        self.assertEqual(len(hv), 2)
        self.assertIn("portrait:hidden", hv[0])      # beside the headline, landscape
        self.assertEqual(hv[1], "lg:hidden")         # under it, OG rotated
        # X quadrant rotated: inline; everything else stacked
        self.assertEqual(holder("quadrant", "pollutant_bars_inline"), ["hidden lg:portrait:block"])
        self.assertEqual(holder("quadrant", "pollutant_bars"), ["lg:portrait:hidden"])
        # half_horizontal: stacked throughout
        self.assertEqual(holder("half_horizontal", "pollutant_bars_inline"), [])
        self.assertEqual(len(holder("half_horizontal", "pollutant_bars")), 1)

    def test_both_settings_draw_the_same_rows(self):
        """Stacked and inline are built in one loop from one bar, so they
        cannot drift apart."""
        loop = SHARED[SHARED.index("{%- for bname in bar_names -%}"):SHARED.index("{%- capture pollutant_bars -%}")]
        self.assertEqual(loop.count("{%- capture bar_track -%}"), 1)
        self.assertEqual(loop.count("{{ bar_track }}"), 2)
        self.assertNotIn("compact", SHARED)

    def test_rotated_half_keeps_the_map_and_adds_the_table(self):
        """Both devices show the map when rotated, then the per-region
        table in place of the one-line region row."""
        hv = self.view("half_vertical")
        self.assertIn('<div class="w--full">{{ map_svg }}</div>', hv)
        self.assertRegex(hv, r'<div class="hidden portrait:block">\s*(\{%- comment -%\}.*?\{%- endcomment -%\}\s*)?<div class="grid grid--cols-5">')
        self.assertIn('<div class="portrait:hidden">{{ region_row }}</div>', hv)

    def test_region_row_fits_five_across_in_the_rotated_quarter(self):
        """value--base clips at five across in 370px; small fits."""
        self.assertIn("lg:value--base lg:portrait:value--small", SHARED)

    def test_half_vertical_fills_its_height_when_rotated(self):
        """Rotated, the content is shorter than the slot on both devices.
        The column fills the height and spaces its sections out, with
        framework classes and only in that orientation."""
        hv = self.view("half_vertical")
        col = re.search(r'<div class="(flex flex--col gap--small w--full[^"]*)">', hv)
        self.assertIsNotNone(col, "main column not found")
        self.assertIn("portrait:h--full", col.group(1))
        self.assertIn("portrait:gap--distribute", col.group(1))
        self.assertNotRegex(col.group(1), r"(?<!:)\bgap--distribute|(?<!:)\bh--full",
                            "spacing must be scoped to portrait:")

    def test_shared_blocks_scale_on_the_x(self):
        """The X guide's --base resets and larger hero size, applied to the
        blocks every view shares, so no view is left at OG sizes on the X."""
        def body(name):
            a = SHARED.index("{%- capture " + name + " -%}")
            return SHARED[a:SHARED.index("{%- endcapture -%}", a)]
        for name in ("fc_block", "bar_row", "bar_row_inline", "pollutant_bars", "pollutant_bars_inline", "headline_block"):
            # labels inside an lg:hidden wrapper never show on the X, so
            # they have nothing to scale to
            shown_on_x = re.sub(r'<div class="lg:hidden">.*?</div>\s*</div>', "", body(name), flags=re.S)
            self.assertNotRegex(shown_on_x, r'class="label label--small(?! lg:label--base)',
                                "%s has a label that does not scale on the X" % name)
        head = body("headline_block")
        self.assertIn("value--xxxlarge lg:value--mega", head)
        # rotated, the headline shares a row three ways and stays at xxxlarge
        self.assertIn("lg:portrait:value--xxxlarge", head)

    def test_full_side_column_fills_the_x(self):
        """Centred, the column left ~170px empty above and below on the X.
        It distributes its blocks over the full height there instead."""
        side = cells(self.view("full"))[1]
        self.assertIn("lg:gap--distribute", side)
        self.assertIn("flex--center-y", side, "the OG still centres the column")


class TestFullViewTable(unittest.TestCase):
    """The X's per-region table carries every pollutant NEA measures."""

    def test_seven_columns_on_the_x(self):
        full = (SRC / "full.liquid").read_text()
        table = full[full.index('<div class="hidden lg:block">\n          <div class="grid grid--cols-7">'):]
        table = table[:table.index("{%- endfor -%}")]
        # sub-indices, as the bars show: NEA's CO concentration is whole mg/m3, 1 almost everywhere
        for key in ("pm25", "pm10", "o3", "so2", "co"):
            self.assertIn("readings.%s_sub_index[rname]" % key, table)
        self.assertNotIn("_hourly[rname]", table)
        self.assertEqual(table.count('class="grid grid--cols-7"'), 2, "header row and one row per region")


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
        # several blocks are X-only; the table is the one built on a 4-column grid
        block = re.search(r'<div class="hidden lg:block">\s*<div class="grid grid--cols-7">(.*?)\{%- endfor -%\}', full, re.S)
        self.assertIsNotNone(block, "region table is not gated on lg:")
        self.assertIn("pm10_sub_index", block.group(1))


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
        for block in ("headline_block", "pollutant_bars", "fc_block"):
            self.assertEqual(self.full.count("{{ %s }}" % block), 2,
                             "%s should render beside the map and in the portrait row" % block)


class TestOneBitLegibility(unittest.TestCase):
    """Grey labels dither away on a 1-bit panel; the framework has a class
    that forces them black there, and review asks for it."""

    def test_every_grey_label_is_forced_black_on_1bit(self):
        for name in LAYOUTS + ("shared",):
            text = (SRC / ("%s.liquid" % name)).read_text()
            for m in re.finditer(r'class="([^"]*label--gray[^"]*)"', text):
                self.assertIn("1bit:text--black", m.group(1),
                              "%s.liquid has a grey label that vanishes at 1-bit" % name)


if __name__ == "__main__":
    unittest.main()
