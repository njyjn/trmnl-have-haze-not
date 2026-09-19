# Baked map inputs

These two files are the only inputs to `tools/build_map.py`. They are committed
so the map can be regenerated without network access.

| File | Source | Licence |
|---|---|---|
| `sgp-adm0.geojson` | [geoBoundaries](https://www.geoboundaries.org/) gbOpen SGP ADM0, simplified release `9469f09` | ODbL, derived from data.gov.sg Master Plan subzone boundaries |
| `psi-regions.json` | `regionMetadata` from the data.gov.sg real-time PSI API | Singapore Open Data Licence |

To refresh the coastline:

```sh
curl -sL "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/SGP/ADM0/geoBoundaries-SGP-ADM0_simplified.geojson" \
  -o tools/data/sgp-adm0.geojson
make map && make test
```

`psi-regions.json` is refreshed by `python3 tools/check_apis.py --refresh`
only if NEA moves a reporting point; `make test` fails when the committed
coordinates and the live ones disagree.
