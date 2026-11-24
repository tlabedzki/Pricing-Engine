"""
Plotly figures of the app in the portfolio look (Data-Generator's ui/figures.py): teal for the data, copper for the
one thing to notice, grey context, hairline grid, Inter with tabular figures. Each figure comes with a title that
states its finding and a subtitle that says how to read it.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from pricing_engine import engine, simulate
from ui import theme as t

CONFIG = {"displayModeBar": False}
Z90 = 1.645  # half-width of a 90% interval in standard errors


def _num(size, color):
    """Font of numbers on a chart (axis ticks, value labels)."""
    return {"family": t.NUM_STACK, "size": size, "color": color}


def _layout(fig, height, **extra):
    margin = extra.pop("margin", {"l": 8, "r": 8, "t": 12, "b": 8})
    fig.update_layout(
        height=height, margin=margin, paper_bgcolor=t.PAGE, plot_bgcolor=t.PAGE,
        font={"family": t.SANS_STACK, "size": 13, "color": t.TEXT}, showlegend=False,
        hoverlabel={"bgcolor": t.PAGE, "bordercolor": t.LINE,
                    "font": {"family": t.SANS_STACK, "color": t.INK, "size": 13}},
        barcornerradius=4, dragmode=False, **{"bargap": 0.32, **extra},
    )
    return fig


def pct(value: float, decimals: int = 1) -> str:
    text = f"{value * 100:+.{decimals}f}%"
    return text if round(value * 100, decimals) else f"{0:.{decimals}f}%"


def rule_names(rules: engine.Rules) -> dict[str, str]:
    """Readable names of the rule that decided each price, with the numbers of the current rules."""
    return {
        "profit_optimum": "highest profit in the rules",
        "market_cap": f"limit +{rules.max_above_market:.0%} over competitors",
        "step_up": f"largest step up ({rules.max_step:.0%})",
        "step_down": f"largest step down ({rules.max_step:.0%})",
        "margin_floor": f"minimum margin {rules.min_margin:.0%}",
        "market_conflict": "minimum margin above the competitor limit",
        "margin_conflict": f"margin below {rules.min_margin:.0%} after the largest step",
    }


def categories(proposals: pd.DataFrame) -> tuple[tuple[str, str], go.Figure]:
    """Gross profit change per category: teal bars for gains, copper for losses, value at the end of each bar."""
    data = simulate.totals(proposals, "category").sort_values("profit_change")
    colors = [t.PRIMARY if v >= 0 else t.ACCENT for v in data["profit_change"]]
    fig = go.Figure()
    fig.add_bar(y=data["category"], x=data["profit_change"], orientation="h", marker={"color": colors},
                customdata=data[["revenue_change", "raise", "lower", "keep"]],
                hovertemplate="%{y}<br>profit <b>%{x:+.1%}</b> · revenue %{customdata[0]:+.1%}<br>"
                              "%{customdata[1]:,} raised · %{customdata[2]:,} lowered · %{customdata[3]:,} kept"
                              "<extra></extra>")
    span = float(data["profit_change"].max() - min(data["profit_change"].min(), 0)) or 0.01
    fig.add_scatter(y=data["category"], x=data["profit_change"], mode="text", hoverinfo="skip",
                    text=[f"  {pct(v)}  " for v in data["profit_change"]],
                    textposition=["middle right" if v >= 0 else "middle left" for v in data["profit_change"]],
                    textfont=_num(12, t.TEXT))
    low = min(float(data["profit_change"].min()), 0) - span * 0.16
    fig.update_yaxes(showgrid=False, ticks="", tickfont={"color": t.INK}, fixedrange=True, automargin=True,
                     ticklabelstandoff=10)
    fig.update_xaxes(visible=False, range=[low, float(data["profit_change"].max()) + span * 0.18], fixedrange=True,
                     zeroline=True, zerolinecolor=t.LINE)
    top = data.iloc[-1]
    losers = int((data["profit_change"] < 0).sum())
    title = f"{top['category']} gains the most: {pct(top['profit_change'])} gross profit"
    sub = ("Change in yearly gross profit per category. "
           + {0: "No category loses profit.", 1: "One category loses profit."}.get(
               losers, f"{losers} categories lose profit."))
    return (title, sub), _layout(fig, max(260, 28 * len(data) + 24), bargap=0.36)


def decision_rules(proposals: pd.DataFrame, rules: engine.Rules) -> tuple[tuple[str, str], go.Figure]:
    """Products by the rule that decided the price, split into raised (teal), lowered (copper) and kept (mist)."""
    table = pd.crosstab(proposals["binding"], proposals["action"]).reindex(columns=list(t.ACTIONS), fill_value=0)
    table = table.loc[table.sum(axis=1).sort_values().index]
    names = [rule_names(rules).get(b, b) for b in table.index]
    fig = go.Figure()
    for action, color in t.ACTIONS.items():
        fig.add_bar(y=names, x=table[action], orientation="h", name=action, marker={"color": color},
                    hovertemplate=f"%{{y}}<br>{action}: <b>%{{x:,}}</b> products<extra></extra>")
    totals = table.sum(axis=1)
    fig.add_scatter(y=names, x=totals, mode="text", text=[f"  {v:,}" for v in totals], textposition="middle right",
                    hoverinfo="skip", textfont=_num(12, t.TEXT))
    fig.update_yaxes(showgrid=False, ticks="", tickfont={"color": t.INK}, fixedrange=True, automargin=True,
                     ticklabelstandoff=10)
    fig.update_xaxes(visible=False, range=[0, float(totals.max()) * 1.16], fixedrange=True)
    lead = table.index[-1]
    title = f"{rule_names(rules).get(lead, lead).capitalize()} decides {totals.iloc[-1] / totals.sum():.0%} of prices"
    sub = "Products by the rule that set the proposal: raised in teal, lowered in copper, kept in grey."
    fig.update_layout(barmode="stack")
    return (title, sub), _layout(fig, max(220, 38 * len(table) + 24), bargap=0.42)


def elasticity(table: pd.DataFrame) -> tuple[tuple[str, str], go.Figure]:
    """Estimated elasticity per category with a 90% interval (teal) next to the true value (copper diamond)."""
    data = table.sort_values("true_elasticity")
    low = data["elasticity"] - Z90 * data["elasticity_se"]
    high = data["elasticity"] + Z90 * data["elasticity_se"]
    hit = (data["true_elasticity"] >= low) & (data["true_elasticity"] <= high)
    fig = go.Figure()
    for category, lo, hi in zip(data["category"], low, high, strict=True):
        fig.add_scatter(x=[lo, hi], y=[category, category], mode="lines", hoverinfo="skip",
                        line={"color": t.TEAL[4], "width": 3})
    fig.add_scatter(x=data["elasticity"], y=data["category"], mode="markers", name="estimate",
                    marker={"color": t.PRIMARY, "size": 11, "line": {"color": t.PAGE, "width": 2}},
                    customdata=pd.DataFrame({"low": low, "high": high, "truth": data["true_elasticity"]}),
                    hovertemplate="%{y}<br>estimate <b>%{x:.2f}</b> (%{customdata[0]:.2f} to %{customdata[1]:.2f})"
                                  "<br>truth %{customdata[2]:.2f}<extra></extra>")
    fig.add_scatter(x=data["true_elasticity"], y=data["category"], mode="markers", name="truth", hoverinfo="skip",
                    marker={"color": t.ACCENT, "size": 11, "symbol": "diamond", "line": {"color": t.PAGE, "width": 2}})
    fig.update_yaxes(showgrid=False, ticks="", fixedrange=True, automargin=True, ticklabelstandoff=10,
                     tickfont={"color": t.INK})
    fig.update_xaxes(gridcolor=t.LINE, zeroline=False, ticks="", tickfont=_num(12, t.MUTED), fixedrange=True,
                     tickformat=".1f", dtick=0.25,
                     rangemode="tozero", title={"text": "price elasticity (% fall in demand after a 1% price rise)",
                                                "font": {"size": 12, "color": t.MUTED}})
    title = f"The estimate hits the truth in {int(hit.sum())} of {len(data)} categories"
    sub = "Dot: estimate from list-price changes and discounts with a 90% interval. Diamond: the true value."
    return (title, sub), _layout(fig, 30 * len(data) + 70, margin={"l": 8, "r": 8, "t": 12, "b": 48})
