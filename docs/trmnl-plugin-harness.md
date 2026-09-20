# Building a TRMNL plugin harness

How to give any TRMNL plugin a development harness: local preview, tests that
run offline, and CI that deploys on merge.

Most of this document is a list of things that are true about TRMNL and
`trmnlp` but are not written down anywhere, or are written down wrongly. They
were established by reading [`usetrmnl/trmnlp`](https://github.com/usetrmnl/trmnlp)
source and by rendering and looking at the output — not from documentation.
Several cost an hour each to find. Read them before writing any Liquid.

**Using this with an agent:** paste the whole file as the prompt, and add one
line saying where the plugin lives and whether it is private or destined for
publication. The plugin in this repository is a worked example of everything
below — `bin/trmnlp`, `Makefile`, `.github/workflows/trmnl.yml` and `tests/`
are the files to copy.

---

## What to build

1. **`bin/trmnlp`** — uses the gem when present, Docker otherwise, handling
   every caveat under *Docker and tooling* below.
2. **`Makefile`** — `serve`, `build`, `png`, `test`, `lint`, `push`.
3. **`.trmnlp.yml`** — dev config. Note in a comment that `serve` rewrites this
   file whenever the Custom Fields picker is used, so it appears in
   `git status` after a preview session.
4. **Tests that need no network:**
   - *Contract tests* pinning every field the templates dereference, against
     committed fixtures. This is the highest-value suite: with no server
     between the API and the device, a renamed upstream field does not raise —
     it silently renders blanks.
   - *Render tests* that run `trmnlp build` and assert on the output HTML.
     These catch Liquid that runs without error but produces a wrong screen,
     which unit tests cannot.
   - A script that checks the **live** API still matches what the templates
     read, for when the screen goes blank in production.
5. **CI** — lint and test on PR, deploy on merge, gated on `id:` being present
   so a push can never create a duplicate plugin.
6. **README** — local dev, deploy flow, and where secrets come from.

---

## Templates and data

- `src/shared.liquid` is **prepended** to every layout before rendering
  (`Renderer#full_markup`). Assigns there are visible in all layouts, and a
  `{% capture %}` there is the only way to share markup between them — Liquid
  has no macros.
- One polling URL puts fields at the root. Multiple URLs (newline-separated in
  `polling_url`) arrive as `IDX_0`, `IDX_1`, … one per URL, in order.
- A JSON response whose **root is an array** is wrapped as `{"data": [...]}`
  (`Poller#wrap_array`). With multiple URLs that means `IDX_1.data[0]`.
- Custom fields are at `trmnl.plugin_settings.custom_fields_values.<keyname>`,
  and a `select` yields the **option label** (`"West"`), not a slug. Normalise
  before using one as a hash key.
- Liquid comparisons against `nil` are all false, so a missed key walks an
  `if/elsif` chain to its final `else` and renders a confident wrong answer
  instead of failing. Guard explicitly and fall back to a "no data" state.
  Check what your worst-case `else` actually says — a chain that ends at the
  most severe outcome will report that severity from no data at all.
- Liquid `sort` works on numeric arrays, and `slice` works on arrays, which
  covers most reshaping without a transform.
- The preview warns above 75 KB of merge variables and rejects at 100 KB.
- Serverless transforms (`src/transform.{py,rb,js,php}`) exist and the hosted
  service supports them, but everything in Liquid runs on every plan. Prefer
  Liquid unless the reshaping genuinely needs a language.

## CSS and layout

- Get real class names from the framework bundle itself:
  `curl -sL https://usetrmnl.com/css/latest/plugins.css`. It is ~18 MB — use
  `grep`. A Python regex with nested quantifiers backtracks for minutes on a
  file that size.
- `.layout` is `width: var(--screen-w); height: var(--screen-h)`. **Never nest
  it.** An inner one is sized to the whole screen and pushes its content out of
  view, producing a blank panel with no error. Use `.flex`/`.flex--col` inside.
- `.trmnl .column` sets `width: 0` and relies on flex-basis. Along a row that
  is fine; the moment columns stack, width becomes the cross axis and
  `align-items: stretch` cannot undo an explicit zero — every column collapses
  to nothing. An override needs three classes to outrank it.
- The framework sets `font-family` only on its own component classes
  (`.title`, `.value`, `.label`). Bare SVG `<text>` inherits nothing that
  resolves and falls back to **serif** — the only serif on the screen. Set it
  from `var(--value-font-family)`.
- Grey text (`label--gray-out`) dithers away on 1-bit panels. Add
  `1bit:text--black`.
- `preserveAspectRatio="none"` scales stroke width along with the box. Add
  `vector-effect="non-scaling-stroke"` to anything stretched, or lines render
  as blobs.
- An SVG with a pixel `width`/`height` attribute cannot grow with the panel.
  Use `viewBox` + `width="100%"` and let CSS drive height.
- `trmnlp lint` flags "too many inline styles" past a threshold. Prefer
  framework classes (`grid grid--cols-N`, `border--h-5`) over hand-rolled CSS.

## Devices and orientation

- OG is 800×480 logical px. TRMNL X is `screen--v2`: **1040×780 logical** at
  `--pixel-ratio: 1.8` (1872×1404 physical), `--color-depth: 4`.
- The X is 4:3 against the OG's 5:3, so it has both width and height that an
  OG-shaped layout has no content for. Spend it on content. Spreading existing
  blocks to fill opens voids, and stretching a chart to reach the bottom
  exaggerates small variation into drama.
- Portrait applies `screen--portrait`, which swaps the screen dimensions.
  Layouts must reflow — a side-by-side design typically uses barely half the
  panel. Key off the `.screen--portrait` class, which TRMNL sets itself, rather
  than a media query, which depends on the renderer's viewport matching the
  panel.
- The full class list the preview applies is
  `screen screen--1bit screen--v2 screen--lg screen--1x`, plus
  `screen--portrait`. Omitting `screen` or the size class renders a grey or
  checkerboard background — that is a missing-class artifact, not a layout bug.
- Render any size directly against a running `serve`:
  `/render/<view>.png?screen_classes=<space-separated>&width=W&height=H`
- Mashup views (`half_*`, `quadrant`) are sized by the framework's `.view--*`
  wrapper. Cropping a full-size render to half its width does **not** simulate
  one; use the preview's own layout tabs.

## Docker and tooling

- The `trmnl/trmnlp` image runs as **root**. Docker Desktop on macOS remaps
  bind-mount ownership to the caller, so this is invisible there; on Linux CI
  the uid passes straight through, `_build` ends up root-owned, and the runner
  cannot delete it. Always pass `--user "$(id -u):$(id -g)"` and
  `--env HOME=/tmp` — an unmapped uid has no home and the gem warns when it
  cannot create its cache directory.
- Only `serve` needs `--publish 4567:4567`. Publishing it for every command
  makes `build`, `lint` and `push` fail with "port is already allocated"
  whenever a `serve` is running — exactly when you reach for them.
- Add `-it` only when `[ -t 0 ] && [ -t 1 ]`, or `make` breaks in CI. Build the
  docker arguments in a bash array; bash 3.2, still the macOS default, errors
  on empty array expansion under `set -u`.
- `trmnlp login` writes its token to `$XDG_CONFIG_HOME/trmnlp/config.yml`,
  which a `--rm` container discards — **a login through Docker can never
  persist**. `TRMNL_API_KEY` takes priority over that file and is the only auth
  that works this way. Pass it through with `--env TRMNL_API_KEY`.
- `trmnlp push` with no `id:` **creates** a plugin, then overwrites your local
  `src/settings.yml` with the server's copy, `id:` included. You never copy the
  id by hand. That rewrite **strips every comment**, so document in the README,
  not in `settings.yml`.
- Every push after the first confirms via `$stdin.gets.chomp`, which is `nil`
  with no TTY and crashes the run. CI must use `push --force`.
- `trmnlp lint` exits non-zero on failure, so CI can gate on it. It caps
  `description` at 35 characters.
- Every command accepts `--dir` / `-d` (a Thor `class_option`, not per-command).

## Publishing, if the plugin is not private

- A **Recipe** is a private plugin approved for public listing: public, no
  server, no OAuth. The OAuth flow belongs to the *third-party* plugin type,
  which expects you to run a web app. Most Liquid plugins want a Recipe.
- Publish from the plugin's settings page. A linter runs, then a human reviews.
  **Unlisted** skips moderation and yields a shareable link immediately, which
  is the cheaper way to test the install flow first.
- Review expects an `author_bio` custom field (`field_type: author_bio`, with
  `github_url` and `learn_more_url`), categories chosen in the web UI, and the
  layout tested at OG landscape, X landscape and X portrait.
- The usual blocker is **demo data**: the recipe master's screen is visible to
  anyone installing, so a plugin showing personal data must ship fake values.
  Plugins reading public APIs with no key have nothing to hide and can skip it.
- Match `refresh_interval` to how often the source actually updates. Polling a
  hourly feed every 15 minutes multiplies wasted requests by every installer.

## If the plugin lives in a monorepo

- Mount the plugin subdirectory as `/plugin` rather than the repository root.
  `trmnlp push` zips the project directory, so mounting the root uploads the
  whole monorepo. `--dir` also works but mounting is simpler.
- Give the workflow a `paths:` filter so it runs only when the plugin directory
  changes, and set `working-directory` accordingly.

## If the data is sensitive

Committed fixtures are the risk. A harness that captures live API responses
into `fixtures/` is right for public data and wrong for anything personal.

- Make fixtures **synthetic**: structurally identical to the real payload with
  invented values. Generate one from a real response by replacing every number,
  name and identifier, then delete the original.
- Assert on shape and behaviour, never on real values.
- Keep credentials out of committed files entirely. Secrets reach the plugin
  through custom fields or `polling_headers` referencing a field, and reach CI
  through repository secrets.
- Grep the staged diff for credential-shaped strings before the first commit.
- Note that local preview polls the real endpoint. Decide deliberately whether
  `serve` should use live data or a local fixture server.

---

## Verification bar

Passing tests are not evidence on their own.

- **Render and look at the PNGs** for every layout, at OG landscape, X
  landscape and X portrait. Several bugs above are invisible in a passing test
  suite and obvious in a screenshot.
- **Prove each test bites.** Re-introduce the bug it covers, confirm it fails,
  restore, confirm it passes. A test that has never failed has proven nothing.
- **Say which checks ran where.** The root-ownership bug above passes on macOS
  forever; only Linux CI can falsify it.
- **Report what was not verified, and why.** Rendering in headless Firefox is
  not the same as e-ink: dot density, dithering and contrast can all read
  differently on real hardware.
