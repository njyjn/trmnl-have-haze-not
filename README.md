# Singapore Air Quality — a TRMNL plugin

A halftone PSI map of Singapore, the headline reading for your region, the
dominant pollutant, a 24-hour PM2.5 forecast, and the neighbouring capitals —
on one e-ink screen, sized to whichever TRMNL panel it lands on.

![Full screen on TRMNL OG](docs/screenshot-full.png)

No server, no API keys, no hosting. TRMNL polls two free public APIs directly
and the Liquid templates do the rest.

## Devices

The layout is proportional rather than pixel-fixed, so it fills whatever panel
it lands on. TRMNL renders OG at 800x480 logical pixels and X at 1040x780
(1872x1404 at `--pixel-ratio: 1.8`), with the BYOD sizes in between.

![Full screen on TRMNL X](docs/screenshot-full-x.png)

The X is 4:3 where the OG is 5:3, so it has spare width and height that a
layout drawn for the OG has no content for. Two rules handle it: the map
column widens below a 3:2 aspect ratio, so the extra width grows the map
rather than the margins; and the forecast chart absorbs the shorter column's
spare height, up to a cap, which squares the two columns off. Whatever slack
remains is centred as margin above and below rather than spread into gaps.

The aspect-ratio rule is progressive — if a renderer's viewport does not match
the panel it simply never fires, and the default split still lays out
correctly. `tests/test_layout.py` fails the build on a pixel width in a column,
a pixel-sized SVG, or a nested `.layout`.

## Where the data comes from

| Source | Used for | Key needed |
|---|---|---|
| [data.gov.sg real-time PSI](https://data.gov.sg/datasets/d_fe37906a0182569d891506e815e819b7/view) (NEA) | the five regional PSI readings, PM2.5/PM10, pollutant sub-indices | no |
| [Open-Meteo Air Quality](https://open-meteo.com/en/docs/air-quality-api) | 24-hour PM2.5 forecast, current US AQI for regional cities | no |
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

### Changing the comparison cities

The cities live in two places that must stay in the same order: the
`latitude=` / `longitude=` lists in `polling_url` (`src/settings.yml`), and
`city_names` in `src/shared.liquid`. Singapore must stay first — it is the
entry the forecast is read from. `make test` fails if the counts disagree.

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

## Licence and attribution

Plugin code is MIT (see `LICENSE`). The data and geometry keep their own terms,
and the plugin is not endorsed by any of these providers:

- PSI readings © National Environment Agency, via data.gov.sg, under the
  [Singapore Open Data Licence](https://data.gov.sg/open-data-licence)
- Forecast and city AQI from Open-Meteo, [CC BY 4.0](https://open-meteo.com/en/license)
- Coastline from geoBoundaries (gbOpen SGP ADM0), ODbL, itself derived from
  the data.gov.sg Master Plan subzone boundaries
