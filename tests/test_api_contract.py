"""Pin the shape of the two APIs the templates read.

There is no server between the APIs and the device, so an upstream rename
breaks the screen silently -- the Liquid just renders blanks. These tests
assert the exact paths src/shared.liquid dereferences, against fixtures
captured from live responses. Run `python3 tools/check_apis.py` to re-check
the same assertions against the live APIs and refresh the fixtures.
"""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
SHARED = (ROOT / "src" / "shared.liquid").read_text()
SETTINGS = (ROOT / "src" / "settings.yml").read_text()

REGIONS = ("north", "south", "east", "west", "central")

# Every readings.<key>[region] the templates dereference.
READING_KEYS = (
    "psi_twenty_four_hourly",
    "pm25_twenty_four_hourly",
    "pm10_twenty_four_hourly",
    "pm25_sub_index",
    "pm10_sub_index",
    "o3_sub_index",
    "so2_sub_index",
    "co_sub_index",
)


def load(name):
    return json.loads((FIXTURES / name).read_text())


class TestPsiFixture(unittest.TestCase):
    def setUp(self):
        self.doc = load("psi.json")

    def test_envelope(self):
        self.assertIn("data", self.doc)
        self.assertIn("items", self.doc["data"])
        self.assertTrue(self.doc["data"]["items"], "no PSI items")

    def test_item_has_timestamp(self):
        # has_psi keys off this, and the title bar prints it.
        self.assertIn("timestamp", self.doc["data"]["items"][0])

    def test_all_reading_keys_cover_all_regions(self):
        readings = self.doc["data"]["items"][0]["readings"]
        for key in READING_KEYS:
            self.assertIn(key, readings)
            for region in REGIONS:
                self.assertIn(region, readings[key], "%s missing %s" % (key, region))
                self.assertIsInstance(readings[key][region], (int, float))

    def test_region_metadata_matches_the_baked_map(self):
        # Keyed by name, not by position: the API returns regionMetadata in a
        # varying order and never promised otherwise. Rendering looks regions
        # up by name, so only the names and coordinates have to agree.
        baked = {r["name"]: r["labelLocation"]
                 for r in json.loads((ROOT / "tools" / "data" / "psi-regions.json").read_text())}
        live = {r["name"]: r["labelLocation"] for r in self.doc["data"]["regionMetadata"]}
        self.assertEqual(sorted(live), sorted(baked))
        for name, loc in live.items():
            self.assertAlmostEqual(loc["latitude"], baked[name]["latitude"], places=4)
            self.assertAlmostEqual(loc["longitude"], baked[name]["longitude"], places=4)


class TestHourlyPm25Fixture(unittest.TestCase):
    """The AQI is derived from this feed, so it is load-bearing."""

    def setUp(self):
        self.doc = load("pm25.json")

    def test_envelope(self):
        self.assertTrue(self.doc["data"]["items"], "no PM2.5 items")

    def test_covers_all_regions(self):
        readings = self.doc["data"]["items"][0]["readings"]["pm25_one_hourly"]
        for region in REGIONS:
            self.assertIn(region, readings)
            self.assertIsInstance(readings[region], (int, float))

    def test_reads_lower_than_the_24h_average_during_haze(self):
        """Not a law of nature, but if the hourly feed ever matched the daily
        mean exactly it would mean the wrong field is being read."""
        hourly = self.doc["data"]["items"][0]["readings"]["pm25_one_hourly"]
        daily = load("psi.json")["data"]["items"][0]["readings"]["pm25_twenty_four_hourly"]
        self.assertNotEqual(sorted(hourly.items()), sorted(daily.items()),
                            "hourly and 24-hour PM2.5 are identical; check the field")


class TestWaqiFixture(unittest.TestCase):
    """Optional source: present only when a token is configured."""

    def setUp(self):
        path = FIXTURES / "waqi.json"
        if not path.exists():
            self.skipTest("no aqicn fixture; needs AQICN_API_TOKEN")
        self.doc = json.loads(path.read_text())

    def test_envelope(self):
        self.assertEqual(self.doc["status"], "ok")
        self.assertIsInstance(self.doc["data"], list)

    def test_covers_every_region(self):
        found = {s["station"]["name"].split(",")[0].lower()
                 for s in self.doc["data"]
                 if s["station"]["name"].endswith(", Singapore")}
        self.assertEqual(found, set(REGIONS),
                         "the bounding box must return all five NEA regions")

    def test_each_station_reports_an_aqi(self):
        for s in self.doc["data"]:
            self.assertIsInstance(s["aqi"], (int, float, str))


class TestOpenMeteoFixture(unittest.TestCase):
    def setUp(self):
        self.doc = load("open-meteo.json")

    def test_root_is_an_array_of_locations(self):
        # TRMNL wraps an array root as {"data": [...]}, which is why
        # shared.liquid reads IDX_1.data rather than IDX_1 directly.
        self.assertIsInstance(self.doc, list)

    def test_one_entry_per_requested_coordinate(self):
        # Match the polling URL itself, not any mention of the host -- the
        # author_bio description links to Open-Meteo's docs.
        urls = [u.strip() for u in SETTINGS.splitlines()
                if u.strip().startswith("https://air-quality-api.open-meteo.com/v1/air-quality?")]
        self.assertEqual(len(urls), 1)
        # Order matters: it decides the IDX_ numbering the templates read.
        polled = [l.strip() for l in SETTINGS.splitlines() if l.strip().startswith("https://")]
        self.assertTrue(polled[0].endswith("/psi"), "PSI must stay IDX_0")
        self.assertTrue(polled[1].endswith("/pm25"), "hourly PM2.5 must stay IDX_1")
        self.assertIn("open-meteo", polled[2], "Open-Meteo must stay IDX_2")
        lats = re.search(r"latitude=([^&]+)", urls[0]).group(1).split(",")
        self.assertEqual(len(self.doc), len(lats))

    def test_singapore_has_an_hourly_forecast(self):
        hourly = self.doc[0]["hourly"]
        self.assertEqual(len(hourly["pm2_5"]), 24)
        self.assertEqual(len(hourly["time"]), 24)
        self.assertTrue(all(isinstance(v, (int, float)) for v in hourly["pm2_5"]))

    def test_every_location_has_a_current_pm25(self):
        # Singapore is index 0 and is shown in the regional row too, so every
        # entry needs the reading, not just the cities after it.
        for i, entry in enumerate(self.doc):
            self.assertIsInstance(entry["current"]["pm2_5"], (int, float),
                                  "location %d has no current pm2_5" % i)

    def test_city_labels_match_the_requested_order(self):
        # Anchor on the variable name: matching any "'...' | split: ','" would
        # pick up whichever such list happens to come first in the file.
        names = re.search(r"assign city_names = '([^']*)'", SHARED)
        self.assertIsNotNone(names, "city_names not found in shared.liquid")
        labels = names.group(1).split(",")
        self.assertEqual(len(labels), len(self.doc),
                         "city_names must label every requested coordinate")
        self.assertEqual(labels[0], "Singapore",
                         "Singapore must stay first; the forecast is read from index 0")


class TestPublishingMetadata(unittest.TestCase):
    """Fields the recipe review looks at."""

    def test_name_and_description(self):
        self.assertRegex(SETTINGS, r"(?m)^name: Have Haze Not$")
        m = re.search(r"(?m)^description: (.+)$", SETTINGS)
        self.assertIsNotNone(m)
        self.assertLessEqual(len(m.group(1)), 35, "trmnlp lint caps description at 35 chars")

    def test_author_bio_is_present(self):
        self.assertIn("field_type: author_bio", SETTINGS,
                      "recipe review expects an author_bio field")

    def test_field_descriptions_are_single_lines(self):
        """No block scalars in custom_fields.

        A folded `>-` description parses to one clean line locally, but the
        line breaks survive into how TRMNL renders the field on the settings
        and install pages. Published recipes keep each description on one
        physical line, so this does too.
        """
        in_fields = False
        for i, line in enumerate(SETTINGS.splitlines(), 1):
            if line.startswith("custom_fields:"):
                in_fields = True
                continue
            if in_fields and line and not line[0].isspace() and not line.startswith("-"):
                in_fields = False
            if in_fields and line.strip().startswith("description:"):
                value = line.split("description:", 1)[1].strip()
                self.assertTrue(value, "line %d: description is empty" % i)
                self.assertNotIn(value[0], "|>",
                                 "line %d: description uses a block scalar; keep it "
                                 "on one line so TRMNL renders it as one paragraph" % i)

    def test_refresh_interval_respects_the_upstream_cadence(self):
        m = re.search(r"(?m)^refresh_interval: (\d+)$", SETTINGS)
        self.assertIsNotNone(m)
        # NEA publishes hourly; polling faster just adds load for every
        # installer without ever showing a newer number.
        self.assertGreaterEqual(int(m.group(1)), 30)


if __name__ == "__main__":
    unittest.main()
