# Have Haze Not

A Singapore air quality tracker for [TRMNL](https://trmnl.com).

A halftone PSI map of all five NEA reporting regions, the headline reading for
your region with its dominant pollutant, a 24-hour PM2.5 forecast, and how the
neighbouring capitals compare — on one e-ink screen, sized to whichever TRMNL
panel it lands on.

![Full screen on TRMNL OG](docs/screenshot-full.png)

No server, no API keys, no hosting. TRMNL polls two free public APIs directly
and the Liquid templates do the rest.

## Devices

The layout is proportional rather than pixel-fixed, so it fills whatever panel
it lands on. TRMNL renders OG at 800x480 logical pixels and X at 1040x780
(1872x1404 at `--pixel-ratio: 1.8`), with the BYOD sizes in between.

![Full screen on TRMNL X](docs/screenshot-full-x.png)

Portrait is its own case. The width is about an OG's, but there are another
500px of height, and side by side the columns used barely half the panel. The
columns stack instead: the map takes the full width, which suits a shape that
is wide and shallow, and the readings sit above it as a row. That took a
fill of 57% to 96%.

![Portrait on TRMNL X](docs/screenshot-full-x-portrait.png)

One trap worth knowing if you touch this: the framework's `.column` sets
`width: 0` and leans on flex-basis to size it. Along a row that is fine, but
once the columns stack, width becomes the cross axis and `align-items:
stretch` cannot undo an explicit zero — every column collapses to nothing.
The override needs three classes to outrank `.trmnl .column`.

The X is 4:3 where the OG is 5:3 and carries 2.1x the pixel area, so it has
width and height a layout drawn for the OG has no content for. That space is
spent on content rather than padding:

- below a 3:2 aspect ratio the map column widens, so the extra width grows the
  map rather than the margins
- a per-region table of PSI, PM2.5 and PM10 appears in the same query. It is
  in the markup on every panel and simply not laid out on the OG, where there
  is no room for it
- the forecast chart absorbs the shorter column's spare height, up to a cap

Spreading the OG's blocks out to fill instead was tried and rejected: it opens
a ~150px void in the left column, and stretching the forecast far enough to
reach the bottom turns a 13ug/m3 drift into a cliff.

The aspect-ratio rule is progressive — if a renderer's viewport does not match
the panel it simply never fires, and the default split still lays out
correctly. `tests/test_layout.py` fails the build on a pixel width in a column,
a pixel-sized SVG, or a nested `.layout`.

## Where the data comes from

| Source | Used for | Key needed |
|---|---|---|
| [data.gov.sg real-time PSI](https://data.gov.sg/datasets/d_fe37906a0182569d891506e815e819b7/view) (NEA) | the five regional PSI readings, PM2.5/PM10, pollutant sub-indices | no |
| [Open-Meteo Air Quality](https://open-meteo.com/en/docs/air-quality-api) | 24-hour PM2.5 forecast, current PM2.5 for the regional row | no |
| [geoBoundaries](https://www.geoboundaries.org/) gbOpen SGP ADM0 | the coastline | n/a, baked in |

NEA is the source for everything inside Singapore because it is the official
measurement and it reports five separate regions. Open-Meteo's air-quality
model runs on a ~11 km grid, which cannot tell one part of Singapore from
another — two points 8 km apart return the same cell — so it is used only for
the forecast and for cities far enough apart to land in different cells.

## How the map works

There is no server to render tiles, so the map is a constant in the template.
`tools/build_map.py` takes the coastline polygon and NEA's five reporting
coordinates and bakes three Liquid variables into `src/shared.liquid`:

- `map_coast` — one SVG path covering the main island, Tekong, Ubin, Jurong
  Island, Sentosa and the southern islands
- `map_layers` — the land sampled on a hex lattice, each dot assigned to its
  nearest NEA reporting point, grouped into five layers
- `map_labels` — where each region's label sits

At render time the template loops the five layers and picks one dot radius per
layer from that region's current PSI. Bigger dots mean a worse band, which is
what the legend under the map spells out. Halftone dots were chosen over grey
fills because the panel is 1-bit.

The region shapes are therefore the Voronoi cells of NEA's five reporting
points clipped to land — an approximation of NEA's regions, not their official
boundaries, which are not published as geometry.

## Install

Clone the plugin into your TRMNL account with [`trmnlp`](https://github.com/usetrmnl/trmnlp).
`bin/trmnlp` uses a locally installed gem if you have Ruby ≥ 3.4 and falls back
to Docker otherwise, so neither is a hard requirement beyond one of the two.

```sh
bin/trmnlp login
make push          # creates the plugin; copy the new id into src/settings.yml
```

Add the returned `id:` to `src/settings.yml` so later pushes update the same
plugin instead of creating a new one each time.

Prefer the web editor? Create a Private Plugin with strategy **Polling**, paste
both URLs from `src/settings.yml` into the Polling URL field (one per line),
and paste each `src/*.liquid` file into the matching layout — remembering that
`shared.liquid` has to be prepended to each one by hand, since the web editor
has no shared file.

## Settings

**Home region** — which of NEA's five reporting regions drives the big number
and the box on the map. Defaults to Central.

TRMNL hands the custom field over as the option *label* (`West`), not a slug,
so `src/shared.liquid` downcases it before looking up NEA's lowercase keys and
falls back to Central if it still does not match. That fallback matters: a key
that misses yields nil, every `nil <= n` comparison is false, and the band
chain would otherwise run to its end and display **Hazardous** with a blank
number — the most alarming possible reading, produced by no data at all.
`tests/test_render.py` covers both cases.

## Development

```sh
make serve    # live preview at http://localhost:4567
make png      # render all four layouts to _build/*.png
make test     # geometry, API contract, and end-to-end render tests
make check    # verify the live APIs still match what the templates read
make lint     # TRMNL best-practice lint
```

`make serve` polls the real APIs, so the preview shows live Singapore air
quality.

`make test` renders the plugin through `trmnlp` for the region-handling cases,
so it needs Docker (or the gem). Those tests skip themselves when neither is
available; the rest of the suite is pure Python.

### Regenerating the map

Run `make map` after changing anything in `tools/data/`, or after tuning
`WIDTH` or `SPACING` at the top of `tools/build_map.py`. It prints an ASCII
preview so you can see the island is still the right shape, and rewrites the
block between the `BEGIN GENERATED MAP` / `END GENERATED MAP` markers in
`src/shared.liquid`. The generated block is committed; CI re-runs the script
and fails if the committed output has drifted from its inputs.

### The regional row, and why it is not an index

The row compares PM2.5 in µg/m³ rather than an air quality index. PSI and US
AQI are different national scales with different breakpoints and averaging
windows, so Singapore's PSI 108 beside Jakarta's US AQI 210 invites a
comparison the reader cannot actually make. A raw concentration is the same
quantity everywhere. Singapore is in the row too, from the same model and the
same hour as the others, so the comparison is like-for-like.

It reads lower than the PM2.5 shown for your region above it, and that is
expected: the row is Open-Meteo's modelled value for this hour, while the
region figure is NEA's measured 24-hour average. Both are labelled.

`tests/test_build_map.py` fails the build if `us_aqi` reappears anywhere in
`src/`, including in the polling URL.

### Changing the comparison cities

The cities live in two places that must stay in the same order: the
`latitude=` / `longitude=` lists in `polling_url` (`src/settings.yml`), and
`city_names` in `src/shared.liquid`. Singapore must stay first — it is also
where the forecast is read from. `make test` fails if the counts disagree or
if Singapore is not first.

### When the screen goes blank

`make check` fetches both APIs live and asserts every field the templates
dereference. Because nothing sits between the APIs and the device, a renamed
upstream field does not raise an error — it just renders an empty screen, and
this is the script that tells you so. Pass `--refresh` to update the fixtures
once you have adapted the templates.

## Layouts

| Layout | Shows |
|---|---|
| `full` | map, legend, regional cities, headline, pollutants, forecast |
| `half_vertical` | map and headline |
| `half_horizontal` | headline, all five regions, forecast |
| `quadrant` | headline PSI and band |

![Half vertical](docs/screenshot-half_vertical.png)

## Publishing

This is shaped as a TRMNL [Recipe](https://help.trmnl.com/en/articles/10122094-plugin-recipes):
public, but with no server and no OAuth — that is the third-party plugin
path, which needs a web app of your own. A recipe is a private plugin the
TRMNL team has approved for public listing; installers get their own copy
with their own `home_region`, and pushed changes reach everyone.

### Order of operations

1. **Authenticate.** `trmnlp login` stores a token in
   `$XDG_CONFIG_HOME/trmnlp/config.yml`, which a `--rm` container throws away,
   so through Docker it never survives. Use the environment variable instead —
   it takes priority over the stored token, and `bin/trmnlp` passes it through:

   ```sh
   export TRMNL_API_KEY=...        # trmnl.com → Settings → API key
   ```

2. **`make push`.** With no `id:` in `src/settings.yml` this *creates* a new
   private plugin, then writes the server's copy of `settings.yml` back over
   your local one — `id:` included. You never copy the id by hand. That
   rewrite also strips the comments from `settings.yml`, so keep anything
   worth keeping in this README.

   From then on every `make push` updates that same plugin. Without the `id:`
   each push would create another copy, which is why CI refuses to deploy
   until it is there.

3. **Add it to a playlist** on your device and check it renders on real
   hardware. The first push prints the link.

4. **Publish.** On the plugin's settings page, click **Publish as a Recipe**.
   Their linter (Chef) runs, then a human reviews, usually a day or two.
   **Unlisted** skips moderation and gives a shareable link immediately, which
   is the easier way to test the install flow first.

Before submitting:

- [ ] `make test && make lint`
- [ ] pick categories in the web UI (they are not part of `settings.yml`)
- [ ] set `TRMNL_API_KEY` as a repo secret if you want CI to deploy on push

Demo data, the usual blocker, does not apply: the plugin polls public APIs
with no keys and no personal data, so the recipe master's screen is simply
the product.

## Licence and attribution

Plugin code is MIT (see `LICENSE`). The data and geometry keep their own terms,
and the plugin is not endorsed by any of these providers:

- PSI readings © National Environment Agency, via data.gov.sg, under the
  [Singapore Open Data Licence](https://data.gov.sg/open-data-licence)
- Forecast and city AQI from Open-Meteo, [CC BY 4.0](https://open-meteo.com/en/license)
- Coastline from geoBoundaries (gbOpen SGP ADM0), ODbL, itself derived from
  the data.gov.sg Master Plan subzone boundaries
