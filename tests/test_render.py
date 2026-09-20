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
    r'label--small">([^<&]*) &middot; ([^<]*)</span>\s*'
    r'<span class="value value--xxxlarge value--tnums">([^<]*)</span>\s*'
    r'<span class="title title--small">([^<]*)</span>'
)
# Region rows in the detail table: name, scale value, PM2.5, PM10
REGION_ROW = re.compile(
    r'title title--small">([^<]*)</span>\s*'
    r'<span class="value value--xsmall value--tnums">([^<]*)</span>\s*'
    r'<span class="value value--xsmall value--tnums">([^<]*)</span>\s*'
    r'<span class="value value--xsmall value--tnums">([^<]*)</span>'
)
POLLUTANT = re.compile(
    r'label--small">(PM2\.5|PM10)</span>\s*<span class="value[^"]*">([^<]*)</span>'
)


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


def render(home_region, scale=None):
    """Render full.html in a throwaway copy configured for one region."""
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
        }
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
        return (project / "_build" / "full.html").read_text()


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
        found = dict(POLLUTANT.findall(self.html))
        self.assertEqual(set(found), {"PM2.5", "PM10"})
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
        svg = re.search(r'<svg class="aq-legend".*?</svg>', cls.html, re.S).group(0)
        cls.allowed = {float(r) for r in re.findall(r'<circle[^>]*r="([\d.]+)"', svg)}

    def test_all_circle_radii_come_from_band_radii(self):
        radii = {float(r) for r in re.findall(r'<circle[^>]*\br="([\d.]+)"', self.html)}
        self.assertTrue(radii, "no dots rendered")
        self.assertTrue(
            radii <= self.allowed,
            "unexpected radii %s; band_radii is %s" % (sorted(radii - self.allowed), sorted(self.allowed)),
        )

    def test_legend_shows_every_band(self):
        """The legend is what makes dot size decodable, so every band must draw."""
        legend = re.search(r'<svg class="aq-legend".*?</svg>', self.html, re.S)
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
        svg = re.search(r'<svg class="aq-legend".*?</svg>', html, re.S)
        self.assertIsNotNone(svg)
        return svg.group(0)

    def test_headline_names_the_chosen_scale(self):
        for choice, (expected, _) in self.CASES.items():
            scale = HEADLINE.search(self.pages[choice]).group(1)
            self.assertEqual(scale, expected, "%s picked the wrong scale" % choice)

    def test_legend_bands_follow_the_scale(self):
        for choice, (_, bands) in self.CASES.items():
            got = re.findall(r'y="24" text-anchor="middle">([^<]*)</text>',
                             self.legend(self.pages[choice]))
            self.assertEqual(got, bands, "%s legend" % choice)

    def test_dot_count_matches_band_count(self):
        for choice, (_, bands) in self.CASES.items():
            dots = re.findall(r'<circle[^>]*r="([\d.]+)"', self.legend(self.pages[choice]))
            self.assertEqual(len(dots), len(bands), "%s legend dots" % choice)

    def test_cities_are_on_the_chosen_scale_too(self):
        """The comparison row must never be in different units to the headline."""
        values = {}
        for choice in self.CASES:
            found = re.findall(
                r'label--small">([A-Z][a-z][^<]*)</span>\s*'
                r'<span class="value value--small value--tnums">([^<]*)</span>',
                self.pages[choice])
            self.assertEqual(len(found), 5, "%s: expected five cities" % choice)
            values[choice] = [int(v) for _, v in found]
        # Same cities, same hour: an index reads higher than the raw
        # concentration it is derived from, so the three must differ.
        self.assertNotEqual(values["US AQI"], values["PM2.5"])
        self.assertNotEqual(values["NEA PSI"], values["PM2.5"])

    def test_pm25_scale_shows_the_concentration_itself(self):
        """On PM2.5 the region column must equal the PM2.5 column."""
        rows = REGION_ROW.findall(self.pages["PM2.5"])
        self.assertEqual(len(rows), 5)
        for name, shown, pm25, _ in rows:
            self.assertEqual(shown, pm25, "%s: scale column should be the PM2.5 value" % name)


if __name__ == "__main__":
    unittest.main()
