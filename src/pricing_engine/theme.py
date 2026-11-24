"""
Visual tokens shared by the app, the README charts and the animated demo: the portfolio look of Data-Generator.

A white page, teal for the data, copper for the one thing to notice, neutral greys for everything else, Inter for all
text with tabular figures. The values mirror Data-Generator's ui/theme.py; the app (ui/) and the README charts
(scripts/make_charts.py) read them from here.
"""
from __future__ import annotations

TEAL = ["#ebf8fa", "#d3eef1", "#addbe1", "#84c4cd", "#59aab4", "#34929e", "#14808c", "#006e79", "#005861", "#00434b"]
COPPER = ["#fff2eb", "#fce2d4", "#f8c9af", "#f0ac86", "#e79363", "#d97d45", "#c7692c", "#aa5823", "#88461c", "#6b3818"]

PRIMARY = TEAL[7]   # data, buttons, sliders, links
ACCENT = COPPER[6]  # the single highlighted mark: the true value, a loss, a price cut
MIST = "#c3d5d8"    # recessive data marks (kept prices, the state before)
AREA = "rgba(0, 110, 121, 0.07)"

PAGE = "#ffffff"
INK = "#14232a"     # primary text
TEXT = "#4a585e"    # secondary text, value labels
MUTED = "#808b90"   # captions, axis labels
LINE = "#e5e9ea"    # hairlines and the chart grid
WASH = "#f5f7f7"    # sidebar, table header, hover

FONT = "Inter"
SANS_STACK = f"'{FONT}', 'Segoe UI', system-ui, sans-serif"
NUMBER_FEATURES = "'tnum' 1, 'cv11' 1"  # tabular figures for every number

ACTIONS = {"raise": PRIMARY, "lower": ACCENT, "keep": MIST}
