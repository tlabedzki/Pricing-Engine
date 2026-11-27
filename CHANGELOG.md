# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.1.5] - 2026-11-27

### Changed

- The README language switch is a flag at the end of the badge row (the Polish flag in `README.md`, the British
  flag in `READMEPL.md`) instead of the English | Polski line under the title; `tests/test_readme_flag.py` keeps
  it there.

## [1.1.4] - 2026-11-27

### Added

- A Polish version of the README (`READMEPL.md`) with an English | Polski link under the title of both files.

### Fixed

- Two sentences of the Polish README text in `scripts/readme_blocks.py` reworded to read naturally.

## [1.1.3] - 2026-11-27

Only the README (a new section, the test count) and the version numbers change; the engine, the app and the
numbers stay as in 1.1.2.

### Added

- README section "Why these tools": what each key tool does in the project, why it fits how the data is read and
  rebuilt from a fresh clone, and which alternative was considered and why it was dropped.

### Fixed

- The package's `__version__` still said 1.1.0; it now matches `pyproject.toml`.

## [1.1.2] - 2026-11-24

The engine and the app are unchanged; the shop data and every number built on them change.

### Changed

- Data from Data-Generator v1.7.1 instead of v1.6.0 (`DATA_GENERATOR_TAG`). In v1.7.1 every net price is the gross
  price without 23% VAT; before, net prices ran from 1/1.18 to 1/4.33 of the gross price. List prices with VAT,
  orders and the estimated elasticity stay the same, so only the margin side moves: yearly gross profit before any
  change is PLN 8.09M instead of 7.86M, and the base scenario gives +3.0% instead of +2.9% (+3.1% with the true
  elasticity, was +3.0%), raising 20,765 prices and lowering 13,376 (was 20,475 and 13,715). Competitor prices
  follow the corrected market price (636,646 price periods, was 636,742).
- README numbers, the six charts, the animated demo and the notebook outputs are rebuilt on the new data; the app
  test pins the new headline numbers (default rules PLN 8.33M, bold rules PLN 8.66M).

### Fixed

- README: "no category loses" when no category loses profit (it read "no category lose").

## [1.1.1] - 2026-11-24

Only the README and its demo change; the engine and the app stay as in 1.1.0.

### Changed

- The animated demo at the top of the README follows a longer story in a 14.5 s loop: the page scrolls from the top
  to the rules, the cursor drags the competitor limit from +5% to +10% and the largest step from 10% to 15% (yearly
  gross profit PLN 8.09M, 8.28M, 8.40M), the page scrolls to the proposals, the table shows only the lowered prices,
  the Categories tab opens and its two charts grow in, then the page scrolls back to the top. The same story as the
  project card on the GitHub profile, in the README's light and dark browser frame. With reduced motion the image
  shows the rules after both drags. The alt text describes the new story.
- `scripts/make_demo_svg.py` takes full-page screenshots of the app 960 px wide in 13 states (every whole value
  of both dragged rules, the lowered prices, the Categories tab), checks every headline number against the engine
  and the layout against the timeline, and builds both files (374 KB each, 127 KB before). New option `--res`
  (image pixels per SVG pixel, default 1.25).

## [1.1.0] - 2026-11-24

### Changed

- The app moves from Streamlit to Dash and Mantine with the building blocks and look of Data-Generator: a white page,
  a hero, numbered sections (01 Rules, 02 Result), Inter served by the app from `ui/assets/fonts/` (no font service),
  tabular figures for every number, teal `#006e79` for the data and copper `#c7692c` for the one mark to notice.
  Same functions as before: the four rule sliders, the category filter, the headline numbers, the Proposals,
  Categories and Elasticity views, the proposals table with reasons, the CSV download and rules from the address
  (`?above=10&step=15`). The same rules give the same headline numbers as 1.0.0.
- Start the app with `python -m ui.app` (http://127.0.0.1:8050). Streamlit and Altair are no longer dependencies;
  Dash, Dash Mantine Components and Plotly are.
- Colours live in `src/pricing_engine/theme.py`, shared by the app and the README charts. The README charts, the
  animated demo and the app screenshot are redrawn in Inter with the new palette; the misses in the elasticity chart
  are marked in copper instead of red. The walkthrough notebook uses the same colours.

### Added

- Tests of the app (`tests/test_ui.py`): layout, callbacks, table, download, figures and the 1.0.0 numbers, and of
  the look (`tests/test_theme.py`): fonts from the repo, colour tokens.

### Fixed

- The animated demo no longer hides a slider value for a moment when the dragged value is exactly half way between
  two whole numbers.

## [1.0.0] - 2026-11-24

### Added

- Data download: `scripts/get_data.py` clones Data-Generator v1.6.0 and generates the shop data (seed 42) with the
  true price elasticity from its settings; five fictional competitors, promotions counted at the regular price.
- Price elasticity per category from list-price changes (conditional Poisson, DuckDB SQL for exposure) and discounts
  (Poisson regression), combined by precision and shrunk towards the average (empirical Bayes), checked against the
  truth.
- Pricing engine: the gross price ending in 9 with the highest expected gross profit within a minimum margin, a limit
  over the competitor median and a largest step, with the deciding rule and a reason sentence for every product.
  A competitor promotion (Data-Generator 1.6.0) counts at the competitor's regular price.
- Simulation: three scenarios, uncertainty from the elasticity intervals and a check with the true elasticity.
- Command line `main.py`, Streamlit app on 127.0.0.1 (rules can be set from the address, `?above=10&step=15`),
  walkthrough notebook.
- README in English with charts, numbers and an animated app demo (SVG, light and dark) from one script run;
  the demo's numbers come from the engine and are checked against the running app.
- Tests (pytest) and CI.
