#!/usr/bin/env python3
"""Check the live APIs still return what the templates read.

Nothing sits between data.gov.sg / Open-Meteo and the device, so a renamed
field does not raise -- the screen just renders blanks. Run this when the
plugin looks wrong:

    python3 tools/check_apis.py             # check live responses
    python3 tools/check_apis.py --refresh   # and rewrite fixtures/ on success

The polling URLs are read straight out of src/settings.yml so this can never
drift from what TRMNL actually fetches.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
SETTINGS = ROOT / "src" / "settings.yml"

# data.gov.sg rejects urllib's default User-Agent with a 403.
USER_AGENT = "trmnl-sg-air/1.0 (+https://github.com/)"


def polling_urls() -> list[str]:
    """Pull the URLs out of settings.yml without needing a YAML parser."""
    urls, in_block = [], False
    for line in SETTINGS.read_text().splitlines():
        if line.startswith("polling_url:"):
            in_block = True
            continue
        if in_block:
            stripped = line.strip()
            if stripped.startswith("http"):
                urls.append(stripped)
                continue
            if stripped:  # next key -- block scalar is over
                break
    return urls


def fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise SystemExit("error: %s returned %s" % (url, resp.status))
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="rewrite fixtures/ when the checks pass")
    args = parser.parse_args()

    urls = polling_urls()
    if len(urls) != 3:
        print("error: expected 3 polling URLs in settings.yml, found %d" % len(urls), file=sys.stderr)
        return 1

    psi_url = next(u for u in urls if u.endswith("/psi"))
    pm25_url = next(u for u in urls if u.endswith("/pm25"))
    om_url = next(u for u in urls if "open-meteo" in u)

    for u in (psi_url, pm25_url):
        print("GET %s" % u)
    print("GET %s" % om_url[:96] + "...")
    psi = fetch(psi_url)
    pm25 = fetch(pm25_url)
    om = fetch(om_url)

    # Write to a scratch location first so the contract tests run against the
    # live payloads; only promote to fixtures/ if they pass.
    staged = {"psi.json": psi, "pm25.json": pm25, "open-meteo.json": om}
    backups = {name: (FIXTURES / name).read_text() for name in staged if (FIXTURES / name).exists()}
    for name, doc in staged.items():
        (FIXTURES / name).write_text(json.dumps(doc, indent=2))

    sys.path.insert(0, str(ROOT / "tests"))
    import test_api_contract  # noqa: E402

    suite = unittest.TestLoader().loadTestsFromModule(test_api_contract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if not result.wasSuccessful() or not args.refresh:
        for name, text in backups.items():
            (FIXTURES / name).write_text(text)
        if not result.wasSuccessful():
            print("\nlive APIs no longer match what src/shared.liquid reads", file=sys.stderr)
            return 1
        print("\nlive APIs match; fixtures left unchanged (pass --refresh to update)")
        return 0

    print("\nlive APIs match; fixtures refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
