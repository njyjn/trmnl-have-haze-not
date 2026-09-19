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


class TestColumnsAreProportional(unittest.TestCase):
    def test_no_pixel_widths_on_columns(self):
        for sel, body in rules(".aq-col"):
            self.assertNotRegex(
                body, r"width:\s*\d+px",
                "%s sets a pixel width; use a flex-basis percentage" % sel,
            )
            self.assertNotRegex(
                body, r"flex:[^;]*\b\d+px",
                "%s sets a pixel flex-basis; use a percentage" % sel,
            )

    def test_every_column_has_a_percentage_basis(self):
        bases = re.findall(r"\.aq-col--\w+\s*\{[^}]*flex:\s*[\d.]+\s+[\d.]+\s+([\d.]+%)", STYLE)
        self.assertGreaterEqual(len(bases), 4, "expected a basis for each column class")

    def test_layouts_do_not_use_fixed_width_utilities_for_columns(self):
        for name in LAYOUTS:
            text = (SRC / ("%s.liquid" % name)).read_text()
            for m in re.finditer(r'class="[^"]*\bcolumn\b[^"]*"', text):
                self.assertNotRegex(
                    m.group(0), r"\bw--\d+\b",
                    "%s.liquid pins a column with a fixed-width utility" % name,
                )


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
    """The extra block ships in the markup everywhere but only lays out
    where there is height for it."""

    def test_hidden_by_default(self):
        self.assertRegex(STYLE, r"\.aq-regions\s*\{[^}]*display:\s*none")

    def test_enabled_inside_the_aspect_query(self):
        query = re.search(r"@media \(max-aspect-ratio[^{]*\{(.*?)\n  \}", STYLE, re.S)
        self.assertIsNotNone(query, "aspect-ratio query not found")
        self.assertRegex(query.group(1), r"\.aq-regions\s*\{[^}]*display:\s*block")

    def test_markup_is_present_unconditionally(self):
        full = (SRC / "full.liquid").read_text()
        self.assertIn('class="aq-regions"', full)


if __name__ == "__main__":
    unittest.main()
