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
        baked = json.loads((ROOT / "tools" / "data" / "psi-regions.json").read_text())
        live = self.doc["data"]["regionMetadata"]
        self.assertEqual([r["name"] for r in live], [r["name"] for r in baked])
        for a, b in zip(live, baked):
            self.assertAlmostEqual(
                a["labelLocation"]["latitude"], b["labelLocation"]["latitude"], places=4
            )
            self.assertAlmostEqual(
                a["labelLocation"]["longitude"], b["labelLocation"]["longitude"], places=4
            )


class TestOpenMeteoFixture(unittest.TestCase):
    def setUp(self):
        self.doc = load("open-meteo.json")

    def test_root_is_an_array_of_locations(self):
        # TRMNL wraps an array root as {"data": [...]}, which is why
        # shared.liquid reads IDX_1.data rather than IDX_1 directly.
        self.assertIsInstance(self.doc, list)

    def test_one_entry_per_requested_coordinate(self):
        urls = [u for u in SETTINGS.splitlines() if "air-quality-api" in u]
        self.assertEqual(len(urls), 1)
        lats = re.search(r"latitude=([^&]+)", urls[0]).group(1).split(",")
        self.assertEqual(len(self.doc), len(lats))

    def test_singapore_has_an_hourly_forecast(self):
        hourly = self.doc[0]["hourly"]
        self.assertEqual(len(hourly["pm2_5"]), 24)
        self.assertEqual(len(hourly["time"]), 24)
        self.assertTrue(all(isinstance(v, (int, float)) for v in hourly["pm2_5"]))

    def test_cities_have_a_current_us_aqi(self):
        for entry in self.doc[1:]:
            self.assertIsInstance(entry["current"]["us_aqi"], (int, float))

    def test_city_labels_match_the_requested_order(self):
        names = re.search(r"'([^']*)' \| split: ','", SHARED)
        labels = names.group(1).split(",")
        self.assertEqual(len(labels), len(self.doc) - 1,
                         "city_names must label every coordinate after Singapore")


if __name__ == "__main__":
    unittest.main()
