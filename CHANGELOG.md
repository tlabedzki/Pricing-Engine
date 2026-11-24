# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased] - 1.0.1

### Changed

- The portfolio look of Data-Generator: Inter for all text, served by the app from `app/static/fonts/` (no font
  service), tabular figures for every number, teal `#006e79` as the main colour, copper `#c7692c` for the one mark to
  notice and grey for the rest. Colours live in `src/pricing_engine/theme.py`; `.streamlit/config.toml` repeats them
  for Streamlit and a test keeps the two in step.
- The proposals table and the charts in the app draw on a canvas, where CSS font features do not reach: a small
  extra face with Inter's tabular digits (`scripts/inter_font.py`) serves 0-9, so their digits line up too.
- README charts, the animated demo and the app screenshot redrawn in Inter with the new palette; the misses in the
  elasticity chart are marked in copper instead of red. The walkthrough notebook uses the same colours.

### Fixed

- The animated demo no longer hides the value above a slider for a moment when the dragged value is exactly half
  way between two whole numbers, and never covers the slider's own label.

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
