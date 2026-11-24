"""
What the proposals do to units, revenue and gross profit: per scenario, per category, under the uncertainty of the
estimated elasticity, and under the true elasticity from Data-Generator (the check a real shop never gets).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pricing_engine.engine import Rules, propose

SCENARIOS = {
    # cautious: no price above the competitor median, small steps, demand assumed 1.64 SE more sensitive (90% bound)
    "cautious": Rules(max_above_market=0.0, max_step=0.05, elasticity_shift=1.64),
    "base": Rules(),
    "bold": Rules(max_above_market=0.10, max_step=0.15),
}
TOTALS = ("units", "revenue", "profit")


def totals(proposals: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Units, net revenue and gross profit a year before and after, with relative changes."""
    columns = [f"{name}_{when}" for name in TOTALS for when in ("before", "after")]
    grouped = proposals.groupby(by)[columns].sum() if by else proposals[columns].sum().to_frame().T
    for name in TOTALS:
        grouped[f"{name}_change"] = grouped[f"{name}_after"] / grouped[f"{name}_before"] - 1
    counts = proposals.groupby(by)["action"] if by else proposals["action"]
    actions = counts.value_counts().unstack(fill_value=0) if by else counts.value_counts().to_frame().T
    for action in ("raise", "lower", "keep"):
        grouped[action] = actions[action].values if action in actions else 0
    grouped["products"] = grouped[["raise", "lower", "keep"]].sum(axis=1)
    return grouped.reset_index(drop=by is None)


def scenarios(table: pd.DataFrame, scenarios: dict[str, Rules] = SCENARIOS) -> pd.DataFrame:
    """Shop totals for every scenario of rules."""
    rows = []
    for name, rules in scenarios.items():
        proposals = propose(table, rules)
        row = totals(proposals).iloc[0].to_dict()
        row.update({
            "scenario": name, "min_margin": rules.min_margin, "max_above_market": rules.max_above_market,
            "max_step": rules.max_step, "elasticity_shift": rules.elasticity_shift,
            "average_change": proposals["change"].mean(),
            "median_index_after": proposals["index_after"].median(),
        })
        rows.append(row)
    first = ["scenario", "min_margin", "max_above_market", "max_step", "elasticity_shift"]
    frame = pd.DataFrame(rows)
    return frame[first + [c for c in frame.columns if c not in first]]


def evaluate(proposals: pd.DataFrame, elasticity: pd.Series | dict) -> pd.DataFrame:
    """The same price changes judged with another elasticity per category (for example the true one)."""
    by_category = proposals["category"].map(pd.Series(elasticity)).to_numpy(float)
    out = proposals.copy()
    ratio = out["proposed_price"] / out["current_price"]
    out["units_after"] = out["units_before"] * ratio ** -by_category
    net_after = out["proposed_price"] / out["vat_ratio"] * (1 - out["average_discount"])
    out["revenue_after"] = out["units_after"] * net_after
    out["profit_after"] = out["units_after"] * (net_after - out["unit_cost"])
    return out


def uncertainty(proposals: pd.DataFrame, elasticity: pd.DataFrame, draws: int = 1000, seed: int = 42):
    """
    Profit and revenue change of the proposals when each category elasticity is drawn from its estimate's normal
    distribution: returns one row per draw.
    """
    rng = np.random.default_rng(seed)
    table = elasticity.set_index("category")
    position = pd.Index(table.index).get_indexer(proposals["category"])
    ratio = (proposals["proposed_price"] / proposals["current_price"]).to_numpy()
    units = proposals["units_before"].to_numpy()
    net_after = (proposals["proposed_price"] / proposals["vat_ratio"] * (1 - proposals["average_discount"])).to_numpy()
    cost = proposals["unit_cost"].to_numpy()
    profit_before = proposals["profit_before"].sum()
    revenue_before = proposals["revenue_before"].sum()
    draw = rng.normal(table["elasticity"].to_numpy(), table["elasticity_se"].to_numpy(), (draws, len(table)))
    draw = np.maximum(draw, 0.05)
    units_after = units[None, :] * ratio[None, :] ** -draw[:, position]
    profit = (units_after * (net_after - cost)[None, :]).sum(axis=1)
    revenue = (units_after * net_after[None, :]).sum(axis=1)
    return pd.DataFrame({"profit_change": profit / profit_before - 1, "revenue_change": revenue / revenue_before - 1})
