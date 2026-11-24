"""The five headline numbers of a set of proposals, formatted once for the app and the animated README demo."""
from __future__ import annotations

import pandas as pd

from pricing_engine import simulate


def pct(value: float, decimals: int = 1) -> str:
    if round(value * 100, decimals) == 0:
        return f"{0:.{decimals}f}%"
    return f"{value * 100:+.{decimals}f}%"


def kpis(proposals: pd.DataFrame, true_elasticity: dict[str, float]) -> dict[str, str | float]:
    """Gross profit, net revenue, units, prices raised and the profit with the true elasticity, as in the app."""
    total = simulate.totals(proposals).iloc[0]
    checked = simulate.totals(simulate.evaluate(proposals, true_elasticity)).iloc[0]
    return {
        "profit": f"{total['profit_after'] / 1e6:.2f}M", "profit_delta": pct(total["profit_change"]),
        "revenue": f"{total['revenue_after'] / 1e6:.2f}M", "revenue_delta": pct(total["revenue_change"]),
        "units": f"{total['units_after']:,.0f}", "units_delta": pct(total["units_change"]),
        "raised": f"{total['raise'] / 1000:.1f}k", "raised_delta": f"{total['lower'] / 1000:.1f}k lowered",
        "truth": pct(checked["profit_change"]),
        "profit_change": float(total["profit_change"]), "revenue_change": float(total["revenue_change"]),
        "units_change": float(total["units_change"]), "true_profit_change": float(checked["profit_change"]),
        "raise": int(total["raise"]), "lower": int(total["lower"]), "keep": int(total["keep"]),
    }
