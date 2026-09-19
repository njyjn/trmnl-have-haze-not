"""End-to-end render tests through trmnlp.

These catch what the unit tests cannot: Liquid that runs without raising but
produces a wrong screen. The custom field is the specific hazard -- TRMNL
hands over the option *label* ("West"), not a slug, and a region key that
misses leaves every `nil <= n` comparison false, which walks the band chain
to its end and reports Hazardous with a blank number. Silent, and alarming.

Skipped when Docker is unavailable.
"""

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

HEADLINE = re.compile(
    r'label--small">PSI 24h &middot; ([^<]*)</span>\s*'
    r'<span class="value value--xxxlarge value--tnums">([^<]*)</span>\s*'
    r'<span class="title title--small">([^<]*)</span>'
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


def render(home_region):
    """Render full.html in a throwaway copy configured for one region."""
    with tempfile.TemporaryDirectory() as tmp:
        project = pathlib.Path(tmp) / "plugin"
        shutil.copytree(
            ROOT, project,
            ignore=shutil.ignore_patterns(".git", "_build", "__pycache__", ".trmnlp"),
        )
        (project / ".trmnlp.yml").write_text(
            "---\n"
            "watch: []\n"
            "custom_fields:\n"
            '  home_region: "%s"\n'
            "framework_version: latest\n"
            "time_zone: Asia/Singapore\n"
            "transform_runtime: disabled\n" % home_region
        )
        subprocess.run(
            ["docker", "run", "--rm", "--volume", "%s:/plugin" % project, "trmnl/trmnlp", "build"],
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
        label, value, band = m.groups()
        self.assertEqual(label, "West")
        self.assertTrue(value.strip().isdigit(), "PSI rendered blank for a capitalised region")
        self.assertNotEqual(band, "Hazardous", "nil PSI fell through the band chain")

    def test_pollutants_resolve(self):
        found = dict(POLLUTANT.findall(self.html))
        self.assertEqual(set(found), {"PM2.5", "PM10"})
        for name, value in found.items():
            self.assertTrue(value.strip().isdigit(), "%s rendered blank" % name)

    def test_band_agrees_with_the_psi(self):
        _, value, band = HEADLINE.search(self.html).groups()
        psi = int(value)
        expected = (
            "Good" if psi <= 50 else
            "Moderate" if psi <= 100 else
            "Unhealthy" if psi <= 200 else
            "Very Unhealthy" if psi <= 300 else
            "Hazardous"
        )
        self.assertEqual(band, expected)


@unittest.skipUnless(docker_available(), "docker not available")
class TestUnknownRegion(unittest.TestCase):
    """A value that is not one of the five regions must fall back, not blank out."""

    @classmethod
    def setUpClass(cls):
        cls.html = render("Atlantis")

    def test_falls_back_to_central(self):
        label, value, band = HEADLINE.search(self.html).groups()
        self.assertEqual(label, "Central")
        self.assertTrue(value.strip().isdigit())
        self.assertNotEqual(band, "Hazardous")


if __name__ == "__main__":
    unittest.main()
