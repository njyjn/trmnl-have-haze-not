"""End-to-end render tests through trmnlp.

These catch what the unit tests cannot: Liquid that runs without raising but
produces a wrong screen. The custom field is the specific hazard -- TRMNL
hands over the option *label* ("West"), not a slug, and a region key that
misses leaves every `nil <= n` comparison false, which walks the band chain
to its end and reports Hazardous with a blank number. Silent, and alarming.

Skipped when Docker is unavailable.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (scale, region, value, band)
HEADLINE = re.compile(
    r'label--small[^"]*">([^<&]*) &middot; ([^<]*)</span>\s*'
    r'<span class="value value--xxxlarge[^"]*">([^<]*)</span>\s*'
    r'<span class="title title--small[^"]*">([^<]*)</span>'
)
# Region rows in the detail table: name, scale value, PM2.5 and PM10 sub-indices
REGION_ROW = re.compile(
    r'title title--small">([^<]*)</span>\s*'
    r'<span class="value value--xsmall value--tnums">([^<]*)</span>\s*'
    r'<span class="value value--xsmall value--tnums">([^<]*)</span>\s*'
    r'<span class="value value--xsmall value--tnums">([^<]*)</span>'
)
# The legend is the 430x40 SVG; the map is the one that draws the coastline.
LEGEND = r'<svg [^>]*viewBox="0 0 430 40".*?</svg>'


def map_labels(html):
    """{REGION: value} as printed on the map. Each label is a halo copy
    (class text--white) then the text itself, which carries only x and y."""
    svg = next(s for s in re.findall(r"<svg\b.*?</svg>", html, re.S) if "<path " in s)
    texts = re.findall(r'<text x="[^"]*" y="[^"]*">([^<]*)</text>', svg)
    return dict(zip(texts[0::2], texts[1::2]))


# The regional strip comes in four drawings, each made at the width it is
# shown at: the OG's (first five cities, 430 wide), the X's landscape and
# rotated ones (all ten, 680 and 760 wide), and the X's landscape half,
# full width (1000, in half_horizontal). Shape: (viewBox, line y, label
# rows, chars-per-width estimate the template uses for normal/bold text).
STRIPS = {
    "og": ("0 0 430 46", 24, (14, 42), 6.6, 7.3),
    "x": ("0 0 680 56", 28, (15, 52), 8.6, 9.5),
    "xp": ("0 0 760 52", 26, (14, 49), 8.6, 9.5),
    "xw": ("0 0 1000 56", 28, (15, 52), 8.6, 9.5),
}
STRIP_CITIES = {"og": 5, "x": 10, "xp": 10, "xw": 10}
STRIP_VIEW = {"xw": "half_horizontal"}   # the rest are drawn in full


class Page(str):
    """full.html, with every view's HTML in .views for what full does not show."""
CITY_NAMES = ["Singapore", "Kuala Lumpur", "Jakarta", "Bangkok", "Manila",
              "Johor Bahru", "Pekanbaru", "Palembang", "Pontianak", "Kuching"]   # fixture order


def strip_svg(html, size):
    if size in STRIP_VIEW:
        html = html.views[STRIP_VIEW[size]]
    m = re.search(r'<svg class="block" viewBox="%s".*?</svg>' % STRIPS[size][0], html, re.S)
    return m.group(0) if m else None


def city_strip(html, size="og"):
    """The regional strip, left to right: [(name, dot_x, label_x, label_y, weight)]."""
    svg = strip_svg(html, size)
    if not svg:
        return None
    line_y = STRIPS[size][1]
    return [(name, float(cx), float(x), int(y), weight) for cx, x, y, weight, name in re.findall(
        r'<circle cx="([\d.]+)" cy="%d" r="[\d.]+"/>\s*<text x="([\d.]+)" y="(\d+)" font-weight="(\d+)">([^<]*)</text>' % line_y,
        svg)]


def docker_available():
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=True)
        return True
    except Exception:
        return False


def _user_flags():
    """Windows has no uid to pass; everywhere else, run as the caller."""
    if not hasattr(os, "getuid"):
        return []
    return ["--user", "%d:%d" % (os.getuid(), os.getgid()), "--env", "HOME=/tmp"]


def render(home_region, scale=None, waqi=False, mutate=None):
    """Render full.html in a throwaway copy configured for one region.

    `mutate`, if given, edits the fixture overrides in place before the
    render, to simulate a feed that is missing data."""
    with tempfile.TemporaryDirectory() as tmp:
        project = pathlib.Path(tmp) / "plugin"
        shutil.copytree(
            ROOT, project,
            ignore=shutil.ignore_patterns(".git", "_build", "__pycache__", ".trmnlp"),
        )
        # Feed the committed fixtures rather than whatever the APIs say right
        # now. Otherwise every render polls live, several in a row get
        # throttled, and an empty payload renders the no-data screen -- which
        # showed up as these tests failing differently on each run.
        # Deterministic inputs also let the assertions check exact numbers.
        # `variables` is deep-merged over the polled data, and JSON is valid
        # YAML, so the fixtures go in verbatim.
        overrides = {
            "IDX_0": json.loads((ROOT / "fixtures" / "psi.json").read_text()),
            # The poller wraps an array-rooted response as {"data": [...]},
            # so the override has to have that shape too.
            "IDX_1": json.loads((ROOT / "fixtures" / "pm25.json").read_text()),
            "IDX_2": {"data": json.loads((ROOT / "fixtures" / "open-meteo.json").read_text())},
            # Without a token the request fails; pass the failure shape so the
            # fallback path is what the default tests exercise.
            "IDX_3": (json.loads((ROOT / "fixtures" / "waqi.json").read_text())
                      if waqi else {"status": "error", "data": "Invalid key"}),
        }
        if mutate:
            mutate(overrides)
        fields = {"home_region": home_region}
        if scale:
            fields["scale"] = scale
        (project / ".trmnlp.yml").write_text(
            "---\n"
            "watch: []\n"
            "framework_version: latest\n"
            "time_zone: Asia/Singapore\n"
            "transform_runtime: disabled\n"
            "custom_fields: " + json.dumps(fields) + "\n"
            "variables: " + json.dumps(overrides) + "\n"
        )
        # The image runs as root. Docker Desktop on macOS remaps bind-mount
        # ownership to the calling user, so this is invisible there, but on
        # Linux the uid passes straight through: _build lands owned by root
        # and TemporaryDirectory cannot unlink it on the way out. Run as the
        # invoking user so nothing root-owned is created in the first place.
        # HOME is set because an unmapped uid has none, and the gem warns
        # when it cannot create its cache directory.
        subprocess.run(
            [
                "docker", "run", "--rm",
                *_user_flags(),
                "--volume", "%s:/plugin" % project,
                "trmnl/trmnlp", "build",
            ],
            capture_output=True, timeout=600, check=True,
        )
        page = Page((project / "_build" / "full.html").read_text())
        page.views = {f.stem: f.read_text() for f in (project / "_build").glob("*.html")}
        return page


@unittest.skipUnless(docker_available(), "docker not available")
class TestCustomFieldCasing(unittest.TestCase):
    """The field arrives capitalised; NEA's keys are lowercase."""

    @classmethod
    def setUpClass(cls):
        cls.html = render("West")

    def test_headline_resolves(self):
        m = HEADLINE.search(self.html)
        self.assertIsNotNone(m, "headline block missing")
        _, label, value, band = m.groups()
        self.assertEqual(label, "West")
        self.assertTrue(value.strip().isdigit(), "PSI rendered blank for a capitalised region")
        self.assertNotEqual(band, "Hazardous", "nil PSI fell through the band chain")

    def test_pollutants_resolve(self):
        found = {name: value for name, _, _, value in BAR.findall(self.html)}
        self.assertEqual(set(found), set(SUB_INDEX))
        for name, value in found.items():
            self.assertTrue(value.strip().isdigit(), "%s rendered blank" % name)

    def test_band_agrees_with_the_value(self):
        """Default scale is US AQI, which has its own six-band ladder."""
        scale, _, value, band = HEADLINE.search(self.html).groups()
        self.assertEqual(scale, "US AQI now")
        v = int(value)
        expected = (
            "Good" if v <= 50 else
            "Moderate" if v <= 100 else
            "Unhealthy for Sensitive" if v <= 150 else
            "Unhealthy" if v <= 200 else
            "Very Unhealthy" if v <= 300 else
            "Hazardous"
        )
        self.assertEqual(band, expected)


@unittest.skipUnless(docker_available(), "docker not available")
class TestRenderedDotSizes(unittest.TestCase):
    """Every dot drawn must come from the shared radius list."""

    @classmethod
    def setUpClass(cls):
        cls.html = render("Central")
        # Take the ramp from the legend the page actually drew, not from the
        # first band_radii in the source: each scale declares its own, so
        # matching on source order picks whichever happens to come first.
        svg = re.search(LEGEND, cls.html, re.S).group(0)
        cls.allowed = {float(r) for r in re.findall(r'<circle[^>]*r="([\d.]+)"', svg)}

    def test_all_circle_radii_come_from_band_radii(self):
        # the map's dots: the SVG that draws the coastline (the regional
        # strip has dots of its own, which are markers, not readings)
        map_svg = next(s for s in re.findall(r"<svg\b.*?</svg>", self.html, re.S) if "<path " in s)
        radii = {float(r) for r in re.findall(r'<circle[^>]*\br="([\d.]+)"', map_svg)}
        self.assertTrue(radii, "no dots rendered")
        self.assertTrue(
            radii <= self.allowed,
            "unexpected radii %s; band_radii is %s" % (sorted(radii - self.allowed), sorted(self.allowed)),
        )

    def test_legend_shows_every_band(self):
        """The legend is what makes dot size decodable, so every band must draw."""
        legend = re.search(LEGEND, self.html, re.S)
        self.assertIsNotNone(legend)
        radii = {float(r) for r in re.findall(r'<circle[^>]*\br="([\d.]+)"', legend.group(0))}
        self.assertEqual(radii, self.allowed)


@unittest.skipUnless(docker_available(), "docker not available")
class TestUnknownRegion(unittest.TestCase):
    """A value that is not one of the five regions must fall back, not blank out."""

    @classmethod
    def setUpClass(cls):
        cls.html = render("Atlantis")

    def test_falls_back_to_central(self):
        _, label, value, band = HEADLINE.search(self.html).groups()
        self.assertEqual(label, "Central")
        self.assertTrue(value.strip().isdigit())
        self.assertNotEqual(band, "Hazardous")


# Published EPA breakpoints (2024 revision), repeated here deliberately: the
# point is to check the Liquid against an independent implementation, so this
# must not read the table out of shared.liquid.
EPA_PM25 = [(0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
            (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500)]


def sub_index(c, table):
    for clo, chi, ilo, ihi in table:
        if clo <= c <= chi:
            return round((ihi - ilo) * (c - clo) / (chi - clo) + ilo)
    return 500


@unittest.skipUnless(docker_available(), "docker not available")
class TestDerivedAqi(unittest.TestCase):
    """No free source publishes an AQI per Singapore region, so the plugin
    derives one from NEA's measurements. The page prints its own inputs --
    PM2.5 and PM10 per region -- so the arithmetic can be checked against a
    separate implementation without trusting the Liquid that produced it."""

    @classmethod
    def setUpClass(cls):
        cls.html = render("Central", scale="US AQI")

    def rows(self):
        rows = REGION_ROW.findall(self.html)
        self.assertEqual(len(rows), 5, "expected one row per NEA region")
        return rows

    def test_every_region_matches_an_independent_calculation(self):
        # The AQI comes off NEA's hourly PM2.5, not the 24-hour column the
        # page prints, so read the hourly figures straight from the fixture
        # the render was given.
        hourly = json.loads((ROOT / "fixtures" / "pm25.json").read_text())
        hourly = hourly["data"]["items"][0]["readings"]["pm25_one_hourly"]
        for name, shown, _pm25_24h, _pm10 in self.rows():
            c = hourly[name.lower()]
            expected = sub_index(float(c), EPA_PM25)
            self.assertEqual(int(shown), expected,
                             "%s: page says %s, EPA breakpoints on the hourly "
                             "PM2.5 of %s give %d" % (name, shown, c, expected))

    def test_uses_the_hourly_reading_not_the_daily_mean(self):
        """The whole point of the change: a 24-hour mean lags badly enough
        during haze to disagree with every other source by ~60 points."""
        for name, shown, pm25_24h, _ in self.rows():
            daily = sub_index(float(pm25_24h), EPA_PM25)
            if daily != int(shown):
                return
        self.fail("every region matches the 24-hour mean; the hourly feed "
                  "is probably not being read")

    def test_headline_matches_the_home_region_row(self):
        _, region, value, _ = HEADLINE.search(self.html).groups()
        row = {n: v for n, v, _, _ in self.rows()}
        self.assertIn(region, row)
        self.assertEqual(value, row[region],
                         "headline and detail table disagree for %s" % region)


@unittest.skipUnless(docker_available(), "docker not available")
class TestScaleSwitching(unittest.TestCase):
    """Every scale must change the whole screen, not just the big number."""

    CASES = {
        "US AQI": ("US AQI now", ["Good", "Moderate", "Sensitive", "Unhealthy",
                              "V. unhealthy", "Hazardous"]),
        "NEA PSI": ("PSI 24h", ["Good", "Moderate", "Unhealthy",
                                "V. unhealthy", "Hazardous"]),
        "PM2.5": ("PM2.5 24h", ["Good", "Moderate", "Unhealthy",
                                "V. unhealthy", "Hazardous"]),
    }

    @classmethod
    def setUpClass(cls):
        cls.pages = {k: render("Central", scale=k) for k in cls.CASES}

    def legend(self, html):
        svg = re.search(LEGEND, html, re.S)
        self.assertIsNotNone(svg)
        return svg.group(0)

    def test_headline_names_the_chosen_scale(self):
        for choice, (expected, _) in self.CASES.items():
            scale = HEADLINE.search(self.pages[choice]).group(1)
            self.assertEqual(scale, expected, "%s picked the wrong scale" % choice)

    def test_legend_bands_follow_the_scale(self):
        for choice, (_, bands) in self.CASES.items():
            got = re.findall(r'y="24" text-anchor="middle"[^>]*>([^<]*)</text>',
                             self.legend(self.pages[choice]))
            self.assertEqual(got, bands, "%s legend" % choice)

    def test_dot_count_matches_band_count(self):
        for choice, (_, bands) in self.CASES.items():
            dots = re.findall(r'<circle[^>]*r="([\d.]+)"', self.legend(self.pages[choice]))
            self.assertEqual(len(dots), len(bands), "%s legend dots" % choice)

    def test_pm25_scale_shows_the_concentration_itself(self):
        """On PM2.5 the region column is NEA's 24-hour concentration, not a sub-index."""
        psi = json.loads((ROOT / "fixtures" / "psi.json").read_text())["data"]["items"][0]["readings"]
        rows = REGION_ROW.findall(self.pages["PM2.5"])
        self.assertEqual(len(rows), 5)
        for name, shown, sub, _ in rows:
            region = name.lower()
            self.assertEqual(shown, str(psi["pm25_twenty_four_hourly"][region]),
                             "%s: scale column should be the PM2.5 value" % name)
            self.assertEqual(sub, str(psi["pm25_sub_index"][region]),
                             "%s: PM2.5 column should be the sub-index" % name)

    def test_regional_strip_is_drawn_on_every_scale(self):
        """Five cities on the OG's line and ten on the X's, whichever scale is
        chosen, with no number printed for any of them."""
        for choice in self.CASES:
            for size, n in STRIP_CITIES.items():
                names = CITY_NAMES[:n]
                strip = city_strip(self.pages[choice], size)
                self.assertIsNotNone(strip, "%s: no %s strip" % (choice, size))
                self.assertEqual(sorted(n for n, *_ in strip), sorted(names), "%s %s" % (choice, size))
                self.assertFalse(re.search(r">[^<]*\d[^<]*</text>", strip_svg(self.pages[choice], size)),
                                 "%s: the %s strip prints a number" % (choice, size))


@unittest.skipUnless(docker_available(), "docker not available")
class TestAqicnSource(unittest.TestCase):
    """With a token the AQI is aqicn's measured figure; without one it falls
    back to the value derived from NEA's hourly PM2.5, so the plugin keeps
    working for anyone who never registers."""

    @classmethod
    def setUpClass(cls):
        cls.measured = json.loads((ROOT / "fixtures" / "waqi.json").read_text())
        cls.with_token = render("Central", scale="US AQI", waqi=True)
        cls.without = render("Central", scale="US AQI", waqi=False)

    def expected(self):
        out = {}
        for s in self.measured["data"]:
            name = s["station"]["name"]
            if name.endswith(", Singapore"):
                out[name.split(",")[0].upper()] = str(s["aqi"])
        return out

    def map_values(self, html):
        return map_labels(html)

    def test_token_makes_every_region_match_aqicn_exactly(self):
        self.assertEqual(self.map_values(self.with_token), self.expected())

    def test_without_a_token_it_still_renders_numbers(self):
        got = self.map_values(self.without)
        self.assertEqual(sorted(got), sorted(self.expected()))
        for region, v in got.items():
            self.assertTrue(v.strip().isdigit(), "%s blank on the fallback path" % region)

    def test_the_two_paths_actually_differ(self):
        """If they matched, the token would be doing nothing."""
        self.assertNotEqual(self.map_values(self.with_token), self.map_values(self.without))

    def test_regional_strip_places_cities_by_the_models_own_figure(self):
        """Cleanest at the left end, worst at the right, the rest to scale
        between them, straight from Open-Meteo's us_aqi. Same strip with or
        without a token: it is a like-for-like comparison between cities,
        so Singapore stays on the model too."""
        om = json.loads((ROOT / "fixtures" / "open-meteo.json").read_text())
        value = dict(zip(CITY_NAMES, [c["current"]["us_aqi"] for c in om]))
        for size, n in STRIP_CITIES.items():
            width = int(STRIPS[size][0].split()[2])
            shown = {k: value[k] for k in CITY_NAMES[:n]}
            lo, hi = min(shown.values()), max(shown.values())
            strips = [city_strip(self.with_token, size), city_strip(self.without, size)]
            self.assertEqual(strips[0], strips[1], "a token must not change the %s strip" % size)
            strip = strips[0]
            self.assertEqual([name for name, *_ in strip], sorted(shown, key=shown.get), size)
            for name, dot_x, _, _, weight in strip:
                want = 6 + (shown[name] - lo) * (width - 12) / (hi - lo)
                self.assertAlmostEqual(dot_x, want, delta=0.1, msg="%s %s is not placed to scale" % (size, name))
                self.assertEqual(weight, "700" if name == "Singapore" else "500")

    def test_strip_labels_alternate_sides(self):
        """Neighbours in rank go above and below the line in turn, so two
        cities with nearly the same figure do not print on top of each other."""
        for size in STRIPS:
            above, below = STRIPS[size][2]
            ys = [y for _, _, _, y, _ in city_strip(self.without, size)]
            self.assertEqual(ys, [above if i % 2 == 0 else below for i in range(len(ys))], size)

    def test_a_label_moved_off_its_dot_has_a_leader(self):
        """When crowding moves a label away from its dot, a thin line joins
        them; a label still over its dot needs none."""
        for size in STRIPS:
            svg = strip_svg(self.without, size)
            leaders = re.findall(r'<line x1="([\d.]+)" y1="\d+" x2="([\d.]+)" y2="\d+" stroke="currentColor" stroke-width="0.75"/>', svg)
            for x1, x2 in leaders:
                self.assertGreater(abs(float(x1) - float(x2)), 6, "%s: a leader where no label moved" % size)

    def test_headline_region_number_is_not_repeated_as_a_city_figure(self):
        """The headline is measured; the strip is modelled. No number for
        Singapore may appear in the regional strip to contradict it."""
        for html in (self.with_token, self.without):
            block = html[html.index("Regional &middot; modelled"):]
            block = block[:block.index("</svg>")]
            self.assertFalse(re.search(r">\s*\d+\s*<", block), "a number is printed in the regional strip")



@unittest.skipUnless(docker_available(), "docker not available")
class TestMissingData(unittest.TestCase):
    """A value a feed did not send must read as missing, never as zero:
    zero is the cleanest air on every scale, so it would look like good news."""

    def test_home_region_missing_reads_as_no_reading(self):
        def drop(o):
            o["IDX_0"]["data"]["items"][0]["readings"]["pm25_twenty_four_hourly"]["central"] = None
        html = render("Central", scale="PM2.5", mutate=drop)
        _, _, value, band = HEADLINE.search(html).groups()
        self.assertEqual(value, "–")
        self.assertEqual(band, "No reading")

    def test_region_missing_on_the_map_has_a_dash_and_no_dots(self):
        def drop(o):
            o["IDX_0"]["data"]["items"][0]["readings"]["pm25_twenty_four_hourly"]["east"] = None
            o["IDX_1"]["data"]["items"][0]["readings"]["pm25_one_hourly"]["east"] = None
        html = render("Central", mutate=drop)
        self.assertEqual(map_labels(html)["EAST"], "–")
        _, _, value, _ = HEADLINE.search(html).groups()
        self.assertTrue(value.isdigit(), "a missing neighbour must not blank the headline")

    def test_offline_aqicn_station_falls_back_to_nea(self):
        def offline(o):
            for s in o["IDX_3"]["data"]:
                if s["station"]["name"].startswith("Central"):
                    s["aqi"] = "-"
        html = render("Central", scale="US AQI", waqi=True, mutate=offline)
        _, _, value, band = HEADLINE.search(html).groups()
        _, _, nea_value, _ = HEADLINE.search(render("Central", scale="US AQI")).groups()
        self.assertEqual(value, nea_value,
                         "offline station should fall back to NEA, got %r" % value)
        self.assertNotEqual(band, "No reading")

    def test_empty_forecast_says_so(self):
        def empty(o):
            o["IDX_2"]["data"][0]["hourly"]["pm2_5"] = []
        html = render("Central", mutate=empty)
        self.assertIn("Forecast unavailable", html)


# One pollutant row: name, bar (solid when dominant), value. The name is
# either on the line above the bar (stacked) or beside it (inline); the
# gap between them differs, the three parts do not.
BAR = re.compile(
    r'<span class="label label--small lg:label--base[^"]*">(PM2\.5|PM10|Ozone|SO2|CO)</span>'
    r'(?:\s*<div class="flex flex--row flex--center-y gap--small">)?\s*'
    r'<div class="progress-bar progress-bar--small grow([^"]*)">\s*<div class="track">\s*'
    r'<div class="fill" style="width: (\d+)%"></div>\s*</div>\s*</div>\s*'
    r'<span class="value[^"]*">([^<]*)</span>')
SUB_INDEX = {"PM2.5": "pm25_sub_index", "PM10": "pm10_sub_index", "Ozone": "o3_sub_index",
             "SO2": "so2_sub_index", "CO": "co_sub_index"}


@unittest.skipUnless(docker_available(), "docker not available")
class TestPollutantBars(unittest.TestCase):
    """The bars are the pollutant readout on every screen: the same five."""

    @classmethod
    def setUpClass(cls):
        cls.html = render("Central")
        cls.psi = json.loads((ROOT / "fixtures" / "psi.json").read_text())["data"]["items"][0]["readings"]

    def test_each_bar_shows_its_sub_index(self):
        rows = BAR.findall(self.html)
        self.assertTrue(rows, "no bars rendered")
        for name, _, width, value in rows:
            sub = self.psi[SUB_INDEX[name]]["central"]
            self.assertEqual(int(value), sub, "%s shows the wrong sub-index" % name)
            self.assertEqual(int(width), min(100, sub * 100 // 200), "%s bar is the wrong length" % name)

    def test_half_horizontal_region_table_shows_sub_indices(self):
        """The X's half: a row per pollutant that moves, a column per region,
        on the same sub-index scale as the bars."""
        hh = self.html.views["half_horizontal"]
        regions = ["north", "south", "east", "west", "central"]
        for label, key in (("PM2.5", "pm25"), ("PM10", "pm10"), ("Ozone", "o3")):
            m = re.search(r'<span class="label label--small">%s</span>((?:\s*<span class="value value--xsmall value--tnums">[^<]*</span>){5})'
                          % re.escape(label), hh)
            self.assertIsNotNone(m, "no %s row in half_horizontal" % label)
            shown = re.findall(r">([^<]*)</span>", m.group(1))
            self.assertEqual(shown, [str(self.psi[key + "_sub_index"][r]) for r in regions], label)

    def test_all_five_in_order_wherever_the_bars_appear(self):
        names = [name for name, _, _, _ in BAR.findall(self.html)]
        order = ["PM2.5", "PM10", "Ozone", "SO2", "CO"]
        self.assertEqual(len(names) % 5, 0)
        for i in range(0, len(names), 5):
            self.assertEqual(names[i:i + 5], order)

    def test_only_the_dominant_pollutant_is_solid(self):
        solid = {name for name, cls, _, _ in BAR.findall(self.html) if "emphasis-3" in cls}
        self.assertEqual(solid, {"PM2.5"})

    def test_solid_bar_follows_the_dominant_pollutant(self):
        def so2_leads(o):
            o["IDX_0"]["data"]["items"][0]["readings"]["so2_sub_index"]["central"] = 180
        html = render("Central", mutate=so2_leads)
        solid = {name for name, cls, _, _ in BAR.findall(html) if "emphasis-3" in cls}
        self.assertEqual(solid, {"SO2"})


@unittest.skipUnless(docker_available(), "docker not available")
class TestBestAndWorstHour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = render("Central")
        cls.om = json.loads((ROOT / "fixtures" / "open-meteo.json").read_text())[0]["hourly"]

    def test_best_and_worst_hour_come_from_the_forecast(self):
        pm = self.om["pm2_5"]; times = self.om["time"]
        def at(i):
            hour = int(times[i][11:13])
            return "%d%s" % (hour % 12 or 12, "am" if hour < 12 else "pm")
        best_i = pm.index(min(pm)); worst_i = pm.index(max(pm))
        self.assertIn("Best %s &middot; %d" % (at(best_i), round(pm[best_i])), self.html)
        self.assertIn("Worst %s &middot; %d" % (at(worst_i), round(pm[worst_i])), self.html)


@unittest.skipUnless(docker_available(), "docker not available")
class TestRegionalStripCrowding(unittest.TestCase):
    """The template estimates label widths; these are the arrangements that
    put the most labels in the least room. On each side of the line, a
    label must end before the next one starts, and stay on the strip."""

    CASES = {
        "all within 9 points": list(range(100, 110)),
        "all identical": [120] * 10,
        "three bunched at the worst end": [60, 180, 182, 184, 70, 75, 80, 85, 90, 95],
        "eight bunched at the worst end": [20, 30, 298, 299, 300, 297, 296, 295, 294, 293],
        "eight bunched at the clean end": [61, 60, 62, 63, 64, 65, 66, 67, 180, 300],
    }

    def test_labels_never_overlap_or_leave_the_strip(self):
        for case, vals in self.CASES.items():
            def crowd(o, vals=vals):
                for city, v in zip(o["IDX_2"]["data"], vals):
                    city["current"]["us_aqi"] = v
            html = render("Central", mutate=crowd)
            for size, n in STRIP_CITIES.items():
                _, _, rows, char_w, char_bold = STRIPS[size]
                width = float(STRIPS[size][0].split()[2])
                strip = city_strip(html, size)
                self.assertEqual(len(strip), n, "%s %s" % (case, size))
                est = {name: len(name) * (char_bold if name == "Singapore" else char_w) for name in CITY_NAMES}
                for side in rows:
                    labels = [(x, x + est[name], name) for name, _, x, y, _ in strip if y == side]
                    for left, right, name in labels:
                        self.assertGreaterEqual(left, 0, "%s %s: %s starts off the strip" % (case, size, name))
                        self.assertLessEqual(right, width + 0.5, "%s %s: %s runs off the strip" % (case, size, name))
                    for (_, right, a), (left, _, b) in zip(labels, labels[1:]):
                        self.assertLessEqual(right, left, "%s %s: %s runs into %s" % (case, size, a, b))


if __name__ == "__main__":
    unittest.main()
