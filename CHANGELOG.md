# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Data download: `scripts/get_data.py` clones Data-Generator v1.5.0 and generates the shop data (seed 42) with the
  true price elasticity from its settings.
- Price elasticity per category from list-price changes (conditional Poisson, DuckDB SQL for exposure) and discounts
  (Poisson regression), combined by precision and shrunk towards the average (empirical Bayes), checked against the
  truth.
- Pricing engine: the gross price ending in 9 with the highest expected gross profit within a minimum margin, a limit
  over the competitor median and a largest step, with the deciding rule and a reason sentence for every product.
  A competitor promotion (Data-Generator 1.6.0) counts at the competitor's regular price.
- Simulation: three scenarios, uncertainty from the elasticity intervals and a check with the true elasticity.
- Command line `main.py`, Streamlit app on 127.0.0.1, walkthrough notebook, README charts and numbers from one script.
- Tests (pytest) and CI.
