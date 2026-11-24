"""
Price proposals: for every product on sale, the list price ending in 9 with the highest expected gross profit
within the pricing rules, and a sentence that says why.

Demand at a new price follows the category elasticity: units(p) = units(p0) x (p / p0) ** -elasticity.
Gross profit = units x (net price x (1 - average discount) - purchase price).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from pricing_engine.data import ShopData

STEP = 0.005
GRID = np.arange(-0.30, 0.30 + STEP / 2, STEP)
PRIOR_YEARS = 1.0


@dataclass(frozen=True)
class Rules:
    """Pricing rules. Prices are gross list prices ending in 9, as the shop sets them."""

    min_margin: float = 0.15  # lowest gross margin of the net list price after the average discount
    max_above_market: float = 0.05  # at most 5% above the median competitor price
    max_step: float = 0.10  # at most 10% up or down in one change
    elasticity_shift: float = 0.0  # standard errors added to the elasticity (> 0 = demand reacts more, cautious)

    def with_changes(self, **changes) -> Rules:
        return replace(self, **changes)


def round_to_9(price: np.ndarray) -> np.ndarray:
    """Nearest whole zloty ending in 9, never below 9."""
    return np.maximum(np.round((np.asarray(price) - 9) / 10) * 10 + 9, 9)


def current_competitor_prices(competitor_prices: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """
    Median, lowest price and number of competitor offers valid on `day`, per product. A short promotion
    (`is_promotion`, Data-Generator 1.6.0 and later) counts at the competitor's regular price before it.
    """
    if "is_promotion" in competitor_prices.columns and competitor_prices["is_promotion"].any():
        prices = competitor_prices.sort_values(["product_id", "competitor_id", "valid_from"])
        regular = prices["price_gross"].where(~prices["is_promotion"].astype(bool))
        regular = regular.groupby([prices["product_id"], prices["competitor_id"]]).ffill()
        competitor_prices = prices.assign(price_gross=regular.fillna(prices["price_gross"]))
    valid = (competitor_prices["valid_from"] <= day) & (
        competitor_prices["valid_to"].isna() | (competitor_prices["valid_to"] >= day))
    offers = competitor_prices.loc[valid]
    return offers.groupby("product_id")["price_gross"].agg(
        competitor_median="median", competitor_min="min", offers="size")


def baseline_units(shop: ShopData, days: int = 365) -> pd.DataFrame:
    """
    Expected units a year at today's price: the product's delivered units in the last `days`, shrunk towards the
    category rate per unit of popularity (a Gamma-Poisson average worth PRIOR_YEARS of the product's own sales).
    """
    start = shop.end_date - pd.Timedelta(days=days - 1)
    recent = shop.orders[(shop.orders["order_date"] >= start) & shop.orders["order_status"].eq("delivered")
                         & ~shop.orders["is_fraud"]]
    units = recent.groupby("product_id")["quantity"].sum()
    discount = (recent["discount_rate"] * recent["quantity"]).groupby(recent["product_id"]).sum()

    products = shop.products.set_index("product_id")
    on_sale = products["discontinued_date"].isna() | (products["discontinued_date"] >= shop.end_date)
    launched = products["launch_date"].clip(lower=start)
    share_of_year = ((shop.end_date - launched).dt.days + 1).clip(lower=1, upper=days) / days
    frame = pd.DataFrame({
        "category": products["category"],
        "popularity": products["product_popularity"],
        "units_observed": units.reindex(products.index, fill_value=0),
        "share_of_year": share_of_year,
    })[on_sale & (products["launch_date"] <= shop.end_date)]
    exposure = frame["popularity"] * frame["share_of_year"]
    rate = frame["units_observed"].groupby(frame["category"]).sum() / exposure.groupby(frame["category"]).sum()
    prior = frame["category"].map(rate) * frame["popularity"]
    frame["units_per_year"] = (frame["units_observed"] + PRIOR_YEARS * prior) / (frame["share_of_year"] + PRIOR_YEARS)

    category_discount = (discount.groupby(products["category"]).sum()
                         / units.groupby(products["category"]).sum()).fillna(0)
    frame["average_discount"] = frame["category"].map(category_discount).fillna(0)
    return frame[["units_observed", "units_per_year", "average_discount"]]


def snapshot(shop: ShopData, elasticity: pd.DataFrame) -> pd.DataFrame:
    """One row per product on sale on the last day of the data, with everything the engine needs."""
    products = shop.products.set_index("product_id")
    demand = baseline_units(shop)
    table = products.loc[demand.index, ["product_name", "category", "brand", "net_purchase_price",
                                       "sales_price_gross", "sales_price_net"]].join(demand)
    table = table.rename(columns={"net_purchase_price": "unit_cost", "sales_price_gross": "price_gross",
                                  "sales_price_net": "price_net"})
    table["vat_ratio"] = table["price_gross"] / table["price_net"]
    by_category = elasticity.set_index("category")
    table["elasticity"] = table["category"].map(by_category["elasticity"])
    table["elasticity_se"] = table["category"].map(by_category["elasticity_se"])
    table = table.join(current_competitor_prices(shop.competitor_prices, shop.end_date))
    table["offers"] = table["offers"].fillna(0).astype(int)
    return table.reset_index()


def _profit(price_gross, base_price, units, elasticity, vat_ratio, discount, cost):
    units_at_price = units * (price_gross / base_price) ** -elasticity
    unit_margin = price_gross / vat_ratio * (1 - discount) - cost
    return units_at_price * unit_margin, units_at_price


def propose(table: pd.DataFrame, rules: Rules = Rules()) -> pd.DataFrame:
    """Best allowed price for every product, with the rule that decided it and a reason sentence."""
    t = table
    n = len(t)
    current = t["price_gross"].to_numpy(float)
    vat = t["vat_ratio"].to_numpy(float)
    discount = t["average_discount"].to_numpy(float)
    cost = t["unit_cost"].to_numpy(float)
    units = t["units_per_year"].to_numpy(float)
    elasticity = np.maximum(t["elasticity"].to_numpy(float) + rules.elasticity_shift * t["elasticity_se"].to_numpy(
        float), 0.05)
    market = t["competitor_median"].to_numpy(float)

    floor = cost / (1 - discount) / (1 - rules.min_margin) * vat
    cap = np.where(np.isfinite(market), market * (1 + rules.max_above_market), np.inf)
    low_step, high_step = current * (1 - rules.max_step), current * (1 + rules.max_step)

    candidates = round_to_9(current[:, None] * (1 + GRID[None, :]))
    candidates = np.sort(np.concatenate([current[:, None], candidates], axis=1), axis=1)
    tolerance = 1e-9
    in_step = (candidates >= low_step[:, None] - tolerance) & (candidates <= high_step[:, None] + tolerance)
    above_floor = candidates >= floor[:, None] - tolerance
    under_cap = candidates <= cap[:, None] + tolerance
    allowed = in_step & above_floor & under_cap

    profit, _ = _profit(candidates, current[:, None], units[:, None], elasticity[:, None], vat[:, None],
                        discount[:, None], cost[:, None])
    # tie-break towards the current price, so equal profit never causes a change
    distance = np.abs(candidates - current[:, None]) / current[:, None]
    tie_break = 1e-9 * distance * (1 + np.abs(profit))
    score = np.where(allowed, profit - tie_break, -np.inf)
    feasible = allowed.any(axis=1)
    rows = np.arange(n)

    # no price satisfies every rule: keep the margin and the step, get as close to the market as allowed
    fallback_ok = in_step & above_floor
    no_floor = ~fallback_ok.any(axis=1)
    fallback = np.where(fallback_ok, candidates, np.inf).min(axis=1)
    fallback = np.where(no_floor, np.where(in_step, candidates, -np.inf).max(axis=1), fallback)
    chosen = np.where(feasible, score.argmax(axis=1), 0)
    best = np.where(feasible, candidates[rows, chosen], fallback)

    # the rule that stopped the price: the next grid price towards the unconstrained optimum is not allowed
    unconstrained = candidates[rows, (profit - tie_break).argmax(axis=1)]
    higher = candidates > best[:, None] + 0.5
    lower = candidates < best[:, None] - 0.5
    up = np.where(higher.any(axis=1), higher.argmax(axis=1), candidates.shape[1] - 1)
    down = np.where(lower.any(axis=1), candidates.shape[1] - 1 - lower[:, ::-1].argmax(axis=1), 0)
    # no allowed price: the margin blocks the market limit only if every price ending in 9 above the floor passes
    # the cap; otherwise the step (with the price endings) keeps the price from reaching the market
    lowest_above_floor = np.where(above_floor, candidates, np.inf).min(axis=1)
    binding = np.select(
        [~feasible & no_floor, ~feasible & (lowest_above_floor > cap + tolerance), ~feasible,
         (unconstrained > best) & ~under_cap[rows, up], (unconstrained > best) & ~in_step[rows, up],
         (unconstrained < best) & ~above_floor[rows, down], (unconstrained < best) & ~in_step[rows, down]],
        ["margin_conflict", "market_conflict", "step_down", "market_cap", "step_up", "margin_floor", "step_down"],
        "profit_optimum")

    new_profit, new_units = _profit(best, current, units, elasticity, vat, discount, cost)
    old_profit, old_units = _profit(current, current, units, elasticity, vat, discount, cost)
    net_factor = (1 - discount) / vat

    out = t[["product_id", "product_name", "category", "brand", "unit_cost", "vat_ratio", "average_discount",
             "offers", "competitor_median", "competitor_min", "elasticity_se"]].copy()
    out["elasticity"] = elasticity
    out["current_price"] = current
    out["proposed_price"] = best
    out["change"] = best / current - 1
    out["index_before"] = current / market
    out["index_after"] = best / market
    out["margin_before"] = 1 - cost / (current * net_factor)
    out["margin_after"] = 1 - cost / (best * net_factor)
    out["units_before"], out["units_after"] = old_units, new_units
    out["revenue_before"], out["revenue_after"] = old_units * current * net_factor, new_units * best * net_factor
    out["profit_before"], out["profit_after"] = old_profit, new_profit
    out["binding"] = binding
    out["action"] = np.select([best > current + 0.5, best < current - 0.5], ["raise", "lower"], "keep")
    out["reason"] = [_reason(row, rules) for row in out.itertuples(index=False)]
    return out


def _pct(value: float) -> str:
    """Whole percent; one decimal under 10%, so 5.4% above a limit of 5% does not read as 5%."""
    value = abs(value) * 100
    return f"{value:.1f}%".replace(".0%", "%") if value < 10 else f"{value:.0f}%"


def _reason(row, rules: Rules) -> str:
    """One sentence a category manager can check: what to do, and the fact behind it."""
    if row.offers > 0 and np.isfinite(row.competitor_median):
        gap = row.index_before - 1
        side = "above" if gap > 0 else "below"
        position = f"{_pct(gap)} {side} the competitor median"
        if abs(gap) < 0.005:
            position = "level with the competitor median"
    else:
        position = "no competitor sells it"
    demand = (f"demand in {row.category} reacts {'weakly' if row.elasticity < 1 else 'strongly'} to price "
              f"(elasticity {row.elasticity:.1f})")
    margin, limit, step = _pct(rules.min_margin), f"+{_pct(rules.max_above_market)}", _pct(rules.max_step)
    head = f"{'Raise' if row.action == 'raise' else 'Lower'} {_pct(row.change)}"
    above_limit = row.offers > 0 and row.index_before > 1 + rules.max_above_market + 1e-9
    over_limit = f", more than the limit of {limit}" if above_limit else ""
    templates = {
        ("keep", "profit_optimum"): f"Keep: the current price already earns the most; {position}, {demand}.",
        ("keep", "market_cap"): f"Keep: {position}; a higher price would pass the limit of {limit}.",
        ("keep", "step_up"): f"Keep: {position}, but the next price ending in 9 is a bigger step than {step}.",
        ("keep", "step_down"): f"Keep: {position}{over_limit}, but the next lower price ending in 9 is a bigger "
                               f"step than {step}.",
        ("keep", "margin_floor"): f"Keep: a lower price would break the minimum margin of {margin}.",
        ("keep", "market_conflict"): f"Keep: {position}, but a lower price would break the minimum margin of "
                                     f"{margin}.",
        ("keep", "margin_conflict"): f"Keep: the margin is below the minimum of {margin}, and the next price ending "
                                     f"in 9 is a bigger step than {step}.",
        ("raise", "profit_optimum"): f"{head}: the price with the highest expected profit; {position}, {demand}.",
        ("raise", "market_cap"): f"{head}: {position}; it stops at the limit of {limit}, {demand}.",
        ("raise", "step_up"): f"{head}, as far as the {step} step limit allows: {position}, {demand}.",
        ("raise", "market_conflict"): f"{head} to reach the minimum margin of {margin}, although this puts it "
                                      f"{_pct(row.index_after - 1)} {'above' if row.index_after > 1 else 'below'} "
                                      f"the competitor median.",
        ("raise", "margin_conflict"): f"{head}, as far as the {step} step limit allows: the margin is still below the "
                                      f"minimum of {margin}.",
        ("raise", "margin_floor"): f"{head} to reach the minimum margin of {margin}; {position}.",
        ("lower", "profit_optimum"): f"{head}: the price with the highest expected profit; {position}, {demand}.",
        ("lower", "market_cap"): f"{head}: {position}, more than the limit of {limit}.",
        ("lower", "step_down"): f"{head}, as far as the {step} step limit allows: "
                                f"{position}{over_limit or ', ' + demand}.",
        ("lower", "market_conflict"): f"{head}: {position}; the minimum margin of {margin} stops it above the "
                                      f"limit of {limit}.",
        ("lower", "margin_floor"): f"{head}: {demand}; the minimum margin of {margin} stops it here.",
    }
    return templates.get((row.action, row.binding), f"{head}: {position}.")
