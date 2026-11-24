"""
Dash + Mantine app of the Pricing Engine, in the portfolio look of Data-Generator: move the pricing rules and see the
proposals, profit and revenue change.

Run locally (from the repository root):
    python -m ui.app            # http://127.0.0.1:8050

The rules can be set from the address, so a set of rules can be shared as a link: /?above=10&step=15
(margin, above, step, caution). The server listens on 127.0.0.1 only.
"""
from __future__ import annotations

import os
import sys
from functools import cache, lru_cache
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import dash._dash_renderer  # noqa: E402
import dash_mantine_components as dmc  # noqa: E402
from dash import Dash, Input, Output, State, dcc, html, no_update  # noqa: E402

from pricing_engine import data, elasticity, engine, report  # noqa: E402
from ui import figures  # noqa: E402
from ui import theme as t  # noqa: E402

dash._dash_renderer._set_react_version("19.2.4")  # Mantine 3 needs React 19; Dash 4.5 still defaults to 18

REPO_URL = "https://github.com/tlabedzki/Pricing-Engine"
TABLE_ROWS = 500
# name: (label, help, minimum, maximum, step, default, (prefix, decimals, suffix) of the value);
# values in percent, caution in standard errors
RULES = {
    "margin": ("Minimum margin", "Lowest gross margin of the net price after the average discount.",
               0, 40, 1, 15, ("", 0, "%")),
    "above": ("At most above the competitor median", "Upper limit of our price over the median competitor price.",
              0, 20, 1, 5, ("+", 0, "%")),
    "step": ("Largest price change at once", "How far one change may move a price, up or down.",
             2, 20, 1, 10, ("", 0, "%")),
    "caution": ("Caution: demand more sensitive by", "Standard errors added to each category's estimated elasticity.",
                0, 2, 0.25, 0, ("", 2, " SE")),
}


def rule_text(name: str, value: float) -> str:
    """The value of a rule as shown next to its slider (ui/assets/rule_values.js writes the same while dragging)."""
    prefix, decimals, suffix = RULES[name][-1]
    return f"{prefix}{float(value):.{decimals}f}{suffix}"
STATS = (  # key in report.kpis, label, note
    ("profit", "gross profit, PLN", "{profit_delta} vs today"),
    ("revenue", "net revenue, PLN", "{revenue_delta} vs today"),
    ("units", "units sold", "{units_delta} vs today"),
    ("raised", "prices raised", "{raised_delta}"),
    ("truth", "true elasticity", "profit judged by the truth"),
)
VIEWS = {"proposals": "Proposals", "categories": "Categories", "elasticity": "Elasticity"}
COLUMNS = [  # column, header, css class, format
    ("product_name", "Product", "", "{}"),
    ("current_price", "Price", "pe-num", "{:,.0f} zł"),
    ("proposed_price", "Proposed", "pe-num", "{:,.0f} zł"),
    ("profit_gain", "Profit / year", "pe-num", "{:+,.0f} zł"),
    ("reason", "Why", "pe-why", "{}"),
]


# ---------------------------------------------------------------------------------------------------------------- #
# Data and proposals

@cache
def prepare():
    """Shop data, elasticity per category, the product snapshot and the true elasticity, computed once."""
    shop = data.load()
    table = elasticity.estimate(shop)
    return shop.truth.get("source", {}), table, engine.snapshot(shop, table), shop.true_elasticity()


def rules_from(margin, above, step, caution) -> engine.Rules:
    return engine.Rules(min_margin=float(margin) / 100, max_above_market=float(above) / 100,
                        max_step=float(step) / 100, elasticity_shift=float(caution))


@lru_cache(maxsize=64)
def proposals_for(margin, above, step, caution, categories: tuple[str, ...] = ()):
    """Proposals for one set of rules and categories (cached: the callbacks of one change share them)."""
    _, _, snap, _ = prepare()
    view = snap if not categories else snap[snap["category"].isin(categories)]
    return engine.propose(view, rules_from(margin, above, step, caution))


def start_values(search: str | None) -> dict[str, float]:
    """Slider values from the address (?above=10&step=15), clipped to the slider range; defaults otherwise."""
    query = parse_qs((search or "").lstrip("?"))
    values = {}
    for name, (_, _, low, high, step, default, _) in RULES.items():
        try:
            value = float(query.get(name, [default])[0])
        except ValueError:
            value = default
        value = min(max(value, low), high)
        values[name] = round(round(value / step) * step, 2)
    return values


# ---------------------------------------------------------------------------------------------------------------- #
# Building blocks

def section(number, title, lead, body, section_id):
    return html.Section([
        html.Div([html.Span(f"{number:02d}", className="dg-step"), html.H2(title, className="dg-h2")],
                 className="dg-section-head"),
        dmc.Text(lead, className="dg-lead-small"),
        html.Div(body, id=f"{section_id}-body"),
    ], id=section_id, className="dg-section")


def stat(label, value, note="", stat_id=None):
    return html.Div([html.Div(value, className="dg-stat-value"), html.Div(label, className="dg-stat-label"),
                     html.Div(note, className="dg-stat-note")], className="dg-stat", id=stat_id or "")


def rule_slider(name):
    label, help_text, low, high, step, default, (prefix, decimals, suffix) = RULES[name]
    return html.Div([
        html.Div([dmc.Text(label, className="dg-label"),
                  html.Span(rule_text(name, default), id=f"{name}-value", className="pe-rule-value",
                            **{"data-prefix": prefix, "data-decimals": str(decimals), "data-suffix": suffix})],
                 className="pe-rule-head"),
        dmc.Text(help_text, className="dg-caption pe-rule-help"),
        dmc.Slider(id=name, min=low, max=high, step=step, value=default, color="petrol", size="sm",
                   label=None, updatemode="mouseup", className="pe-slider"),
    ], className="pe-rule")


def rules_view(categories, source, products):
    return [
        html.Div([rule_slider(name) for name in RULES], className="pe-rules"),
        dmc.MultiSelect(id="categories", data=categories, placeholder="All categories", label="Categories",
                        clearable=True, searchable=True, className="pe-categories", size="md"),
        dmc.Text(f"Data: Lumo, a fictional shop from Data-Generator {source.get('tag', '')} (seed "
                 f"{source.get('seed', '')}). {products:,} products on sale.", className="dg-caption pe-source"),
    ]


def result_view(elasticity_block):
    return [
        html.Div([stat(label, "", stat_id=f"stat-{key}") for key, label, _ in STATS], className="dg-stats",
                 id="stats"),
        dmc.SegmentedControl(id="view", value="proposals", size="md", className="pe-tabs",
                             data=[{"value": k, "label": v} for k, v in VIEWS.items()]),
        html.Div([
            dmc.SegmentedControl(id="show", value="all", size="sm", className="pe-show",
                                 data=[{"value": v, "label": v} for v in ("all", "raise", "lower", "keep")]),
            html.Div(id="table"),
            dmc.Button("Download all proposals (CSV)", id="download-button", variant="outline", color="petrol",
                       className="pe-download"),
            dcc.Download(id="download"),
        ], id="view-proposals", className="pe-tab-body"),
        html.Div(id="view-categories", className="pe-tab-body", style={"display": "none"}),
        html.Div(elasticity_block, id="view-elasticity", className="pe-tab-body", style={"display": "none"}),
    ]


def chart_block(text, figure, extra_class=""):
    title, subtitle = text
    return html.Figure([
        html.Figcaption([html.Div(title, className="dg-chart-title"), html.Div(subtitle, className="dg-chart-sub")]),
        dcc.Graph(figure=figure, config=figures.CONFIG, className="dg-graph",
                  style={"height": f"{figure.layout.height}px"}),
    ], className=f"dg-chart {extra_class}")


def table_view(proposals, show):
    shown = proposals if show in (None, "all") else proposals[proposals["action"] == show]
    shown = shown.assign(profit_gain=shown["profit_after"] - shown["profit_before"]).sort_values(
        "profit_gain", ascending=False)
    head = shown.head(TABLE_ROWS)

    def cell(column, css, fmt, row):
        value = row[column]
        text = fmt.format(value)
        if column == "proposed_price":
            css += " pe-up" if value > row["current_price"] else " pe-down" if value < row["current_price"] else ""
        return html.Td(text, className=css or None, title=text if column in ("reason", "product_name") else None)

    rows = [html.Tr([cell(column, css, fmt, row) for column, _, css, fmt in COLUMNS])
            for row in head.to_dict("records")]
    table = html.Table([
        html.Thead(html.Tr([html.Th(header, className=css or None) for _, header, css, _ in COLUMNS])),
        html.Tbody(rows),
    ], className="dg-table pe-table")
    return [
        html.Div(table, className="dg-table-scroll", tabIndex="0", role="region",
                 **{"aria-label": "Price proposals, scrolls in both directions"}),
        dmc.Text(f"{len(shown):,} products, the {len(head):,} with the largest profit gain shown.",
                 className="dg-caption", mt="sm"),
    ]


def page():
    try:
        source, table, snap, _ = prepare()
    except FileNotFoundError as error:
        source, table, snap = None, None, None
        problem = str(error)
    header = html.Header(html.Div([
        html.Span(["Pricing Engine", html.Span(".", className="dg-dot")], className="dg-wordmark"),
        html.A("Source on GitHub", href=REPO_URL, target="_blank", className="dg-link"),
    ], className="dg-wrap dg-topline"))
    hero = html.Div([
        html.P("Price proposals from data", className="dg-eyebrow"),
        html.H1(["A price for every product, ", html.Br(), "with ", html.Em("a reason"), " and its profit."],
                className="dg-h1"),
        html.P("Proposals for every product of a fictional shop from the estimated price elasticity, competitor "
               "prices and your rules. Move a rule; the effect on a year of sales updates at once.",
               className="dg-lead"),
    ], className="dg-hero")
    if snap is None:
        body = [hero, section(1, "Rules", "The shop data is missing.", html.P(problem, className="dg-placeholder"),
                              "rules")]
    else:
        body = [
            hero,
            section(1, "Rules", "Four rules limit every price. The address keeps them, so a set of rules is a link.",
                    rules_view(sorted(snap["category"].unique()), source, len(snap)), "rules"),
            section(2, "Result", "A year of sales after the proposals, against today's prices.",
                    result_view(chart_block(*figures.elasticity(table))), "result"),
        ]
    footer = html.Footer([
        html.P("All products, prices and sales are generated by Data-Generator: a fictional shop, seed 42. "
               "The true elasticity is known only because the data is generated."),
        html.A(REPO_URL.removeprefix("https://"), href=REPO_URL, target="_blank", className="dg-link"),
    ], className="dg-footer")
    return dmc.MantineProvider(theme=t.MANTINE_THEME, children=html.Div([
        dcc.Location(id="url", refresh=False),
        header,
        html.Main(html.Div([*body, footer], className="dg-wrap")),
    ], className="dg-page"))


# ---------------------------------------------------------------------------------------------------------------- #
# App and callbacks

app = Dash(__name__, title="Pricing Engine", assets_folder=str(Path(__file__).parent / "assets"),
           suppress_callback_exceptions=True)
app.layout = page
RULE_INPUTS = [Input(name, "value") for name in RULES]


@app.callback([Output(name, "value") for name in RULES], Input("url", "search"))
def apply_address(search):
    """Rules from the address when the page opens."""
    values = start_values(search)
    return [values[name] for name in RULES]


def stats_view(numbers: dict) -> list:
    return [stat(label, numbers[key], note.format(**numbers), stat_id=f"stat-{key}") for key, label, note in STATS]


@app.callback(
    Output("stats", "children"), Output("view-categories", "children"),
    *[Output(f"{name}-value", "children") for name in RULES],
    *RULE_INPUTS, Input("categories", "value"),
)
def update_result(margin, above, step, caution, categories):
    """Headline numbers, the category charts and the rule values for the current rules."""
    if None in (margin, above, step, caution):
        return (no_update,) * (2 + len(RULES))
    proposals = proposals_for(margin, above, step, caution, tuple(sorted(categories or ())))
    numbers = report.kpis(proposals, prepare()[3])
    rules = rules_from(margin, above, step, caution)
    charts = [chart_block(*figures.categories(proposals)),
              chart_block(*figures.decision_rules(proposals, rules), "pe-chart-gap")]
    values = [rule_text(name, value) for name, value in zip(RULES, (margin, above, step, caution), strict=True)]
    return stats_view(numbers), charts, *values


@app.callback(Output("table", "children"), Input("show", "value"), *RULE_INPUTS, Input("categories", "value"))
def update_table(show, margin, above, step, caution, categories):
    if None in (margin, above, step, caution):
        return no_update
    return table_view(proposals_for(margin, above, step, caution, tuple(sorted(categories or ()))), show)


@app.callback([Output(f"view-{name}", "style") for name in VIEWS], Input("view", "value"))
def switch_view(view):
    return [{} if name == (view or "proposals") else {"display": "none"} for name in VIEWS]


@app.callback(
    Output("download", "data"), Input("download-button", "n_clicks"),
    *[State(name, "value") for name in RULES], State("categories", "value"), prevent_initial_call=True,
)
def download(clicks, margin, above, step, caution, categories):
    if not clicks:
        return no_update
    proposals = proposals_for(margin, above, step, caution, tuple(sorted(categories or ())))
    return dcc.send_string(proposals.to_csv(index=False), "proposals.csv")


def main():
    app.run(host="127.0.0.1", port=int(os.environ.get("PE_PORT", 8050)), debug=False)


if __name__ == "__main__":
    main()
