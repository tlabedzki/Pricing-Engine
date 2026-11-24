"""
Pricing Engine app: move the pricing rules and see the proposals, profit and revenue change live.

    streamlit run app/streamlit_app.py

The server listens on 127.0.0.1 only (.streamlit/config.toml).
"""
from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pricing_engine import data, elasticity, engine, simulate  # noqa: E402

BLUE, ORANGE, RED, KEEP, INK_2 = "#2a78d6", "#eb6834", "#e34948", "#b5b3ab", "#52514e"
ACTION_COLORS = alt.Scale(domain=["raise", "lower", "keep"], range=[BLUE, ORANGE, KEEP])

st.set_page_config(page_title="Pricing Engine", layout="wide")


@st.cache_data(show_spinner="Estimating price elasticity from the shop data…")
def prepare():
    shop = data.load()
    table = elasticity.estimate(shop)
    return shop.truth.get("source", {}), table, engine.snapshot(shop, table), shop.true_elasticity()


def pct(value: float, decimals: int = 1) -> str:
    if round(value * 100, decimals) == 0:
        return f"{0:.{decimals}f}%"
    return f"{value * 100:+.{decimals}f}%"


try:
    source, table, snap, truth = prepare()
except FileNotFoundError as error:
    st.error(f"{error}")
    st.stop()

with st.sidebar:
    st.header("Pricing rules")
    min_margin = st.slider("Minimum margin", 0, 40, 15, 1, format="%d%%",
                           help="Lowest gross margin of the net price after the average discount") / 100
    above = st.slider("At most above the competitor median", 0, 20, 5, 1, format="+%d%%") / 100
    step = st.slider("Largest price change at once", 2, 20, 10, 1, format="%d%%") / 100
    caution = st.slider("Caution: demand more sensitive by", 0.0, 2.0, 0.0, 0.25, format="%.2f SE",
                        help="Standard errors added to each category's estimated elasticity")
    categories = st.multiselect("Categories", sorted(snap["category"].unique()), placeholder="All categories")
    st.caption(f"Data: Lumo, a fictional shop from Data-Generator {source.get('tag', '')} (seed "
               f"{source.get('seed', '')}). {len(snap):,} products on sale.")

rules = engine.Rules(min_margin=min_margin, max_above_market=above, max_step=step, elasticity_shift=caution)
view = snap if not categories else snap[snap["category"].isin(categories)]
proposals = engine.propose(view, rules)
total = simulate.totals(proposals).iloc[0]
checked = simulate.totals(simulate.evaluate(proposals, truth)).iloc[0]

st.title("Pricing Engine")
st.write("Price proposals for every product from the estimated price elasticity, competitor prices and your rules. "
         "Move the rules on the left; the yearly effect updates at once.")

kpi = st.columns(5)
kpi[0].metric("Gross profit a year, PLN", f"{total['profit_after'] / 1e6:.2f}M", pct(total["profit_change"]))
kpi[1].metric("Net revenue a year, PLN", f"{total['revenue_after'] / 1e6:.2f}M", pct(total["revenue_change"]))
kpi[2].metric("Units a year", f"{total['units_after']:,.0f}", pct(total["units_change"]))
kpi[3].metric("Prices raised", f"{total['raise'] / 1000:.1f}k", f"{total['lower'] / 1000:.1f}k lowered",
              delta_color="off", delta_arrow="off",
              help=f"{int(total['raise']):,} prices raised, {int(total['lower']):,} lowered, "
                   f"{int(total['keep']):,} kept")
kpi[4].metric("Profit, true elasticity", pct(checked["profit_change"]),
              help="The same proposals judged with Data-Generator's true elasticity: the check a real shop never has")

tab_products, tab_categories, tab_elasticity = st.tabs(["Proposals", "Categories", "Elasticity"])

with tab_products:
    action = st.segmented_control("Show", ["all", "raise", "lower", "keep"], default="all")
    shown = proposals if action in (None, "all") else proposals[proposals["action"] == action]
    shown = shown.assign(profit_gain=shown["profit_after"] - shown["profit_before"]).sort_values(
        "profit_gain", ascending=False)
    columns = {
        "product_name": "Product", "current_price": "Price", "proposed_price": "Proposed", "reason": "Why",
        "profit_gain": "Profit / year",
    }
    st.dataframe(
        shown[list(columns)].rename(columns=columns).head(500), hide_index=True, width="stretch",
        column_config={
            "Profit / year": st.column_config.NumberColumn(format="%+.0f zł", help="Expected change in gross profit",
                                                           width=90),
            "Product": st.column_config.TextColumn(width=210),
            "Price": st.column_config.NumberColumn(format="%.0f zł", width=75),
            "Proposed": st.column_config.NumberColumn(format="%.0f zł", width=80),
            "Why": st.column_config.TextColumn(width=760),
        },
    )
    st.caption(f"{len(shown):,} products, the 500 with the largest profit gain shown.")
    st.download_button("Download all proposals (CSV)", proposals.to_csv(index=False).encode("utf-8"),
                       "proposals.csv", "text/csv")

with tab_categories:
    by_category = simulate.totals(proposals, "category")
    bars = alt.Chart(by_category).mark_bar(cornerRadiusEnd=4, height=16).encode(
        x=alt.X("profit_change:Q", title="Gross profit change", axis=alt.Axis(format="+%")),
        y=alt.Y("category:N", sort="-x", title=None),
        color=alt.condition("datum.profit_change >= 0", alt.value(BLUE), alt.value(RED)),
        tooltip=[alt.Tooltip("category:N", title="Category"),
                 alt.Tooltip("profit_change:Q", title="Profit", format="+.1%"),
                 alt.Tooltip("revenue_change:Q", title="Revenue", format="+.1%"),
                 alt.Tooltip("raise:Q", title="Raise"), alt.Tooltip("lower:Q", title="Lower"),
                 alt.Tooltip("keep:Q", title="Keep")],
    ).properties(height=34 * len(by_category))
    st.altair_chart(bars, width="stretch")
    decided = proposals.groupby(["binding", "action"]).size().rename("products").reset_index()
    rules_chart = alt.Chart(decided).mark_bar(height=16).encode(
        x=alt.X("products:Q", title="Products", stack="zero"),
        y=alt.Y("binding:N", sort="-x", title="Rule that decided the price"),
        color=alt.Color("action:N", scale=ACTION_COLORS, title="Action"),
        tooltip=["binding", "action", "products"],
    ).properties(height=40 * decided["binding"].nunique())
    st.altair_chart(rules_chart, width="stretch")

with tab_elasticity:
    st.write("How strongly demand reacts to price in each category, estimated from list-price changes and discounts, "
             "next to the true value set in Data-Generator.")
    e = table.assign(low=table["elasticity"] - 1.645 * table["elasticity_se"],
                     high=table["elasticity"] + 1.645 * table["elasticity_se"])
    base = alt.Chart(e).encode(y=alt.Y("category:N", sort=alt.EncodingSortField("true_elasticity"), title=None))
    chart = (base.mark_rule(color=BLUE, opacity=0.45, strokeWidth=2).encode(
                 x=alt.X("low:Q", title="Price elasticity"), x2="high:Q")
             + base.mark_circle(color=BLUE, size=80, opacity=1).encode(
                 x="elasticity:Q", tooltip=[alt.Tooltip("elasticity:Q", format=".2f", title="Estimate"),
                                            alt.Tooltip("true_elasticity:Q", format=".2f", title="Truth")])
             + base.mark_point(shape="diamond", color=ORANGE, filled=True, size=90).encode(x="true_elasticity:Q"))
    st.altair_chart(chart.properties(height=30 * len(e)), width="stretch")
    st.caption("Dot: estimate with a 90% interval. Diamond: the true value.")
