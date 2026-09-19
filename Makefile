# Docker is used for trmnlp so nothing needs Ruby 3.4 locally; bin/trmnlp
# prefers a locally installed gem when there is one.
.PHONY: serve build png map test check lint push

serve:  ## live preview on http://localhost:4567
	bin/trmnlp serve --bind 0.0.0.0

build:  ## render the four layouts to _build/*.html
	bin/trmnlp build

png:    ## render the four layouts to _build/*.png
	bin/trmnlp build --png

map:    ## regenerate the baked map block in src/shared.liquid
	python3 tools/build_map.py

test:   ## geometry and API-contract tests, against committed fixtures
	python3 -m unittest discover -s tests -v

check:  ## verify the live APIs still match what the templates read
	python3 tools/check_apis.py

lint:   ## TRMNL best-practice lint
	bin/trmnlp lint

push:   ## upload to TRMNL (needs TRMNL_API_KEY and an id: in settings.yml)
	bin/trmnlp push
