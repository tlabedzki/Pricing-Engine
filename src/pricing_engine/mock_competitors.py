"""
Mock `competitor_prices` table with the columns agreed for Data-Generator v1.5.0.

The engine uses it only until the release ships the real table. Four fictional shops price every product they sell at
a market reference (purchase price times the median markup of its product type) times their own price level, with
persistent noise per product and a few price changes a year that return to that anchor.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
COMPETITOR_COLUMNS = [
    "competitor_price_id", "product_id", "competitor_id", "competitor_name", "valid_from", "valid_to", "price_gross",
    "price_net", "change_type", "competitor_strategy", "true_price_level", "true_market_price_gross",
]
STRATEGIES = {
    1: {"name": "Mock Discounter", "strategy": "discounter", "level": 0.92, "sd": 0.04, "coverage": 0.55,
        "changes_per_year": 1.5, "ending": "99"},
    2: {"name": "Mock Matcher", "strategy": "matcher", "level": 1.00, "sd": 0.02, "coverage": 0.70,
        "changes_per_year": 1.2, "ending": "99"},
    3: {"name": "Mock Premium", "strategy": "premium", "level": 1.08, "sd": 0.05, "coverage": 0.40,
        "changes_per_year": 0.6, "ending": "9"},
    4: {"name": "Mock Marketplace", "strategy": "marketplace", "level": 0.97, "sd": 0.10, "coverage": 0.80,
        "changes_per_year": 3.0, "ending": "99"},
}
MARKET_TREND_PER_YEAR = 0.0  # v1.5.0 keeps the anchor constant, so the level holds on every day
CHANGE_SD = 0.03
MIN_TYPE_SIZE = 20


def round_to_99(price: np.ndarray) -> np.ndarray:
    """Nearest price ending in ,99 (149.99), never below 0.99."""
    return np.maximum(np.round(np.asarray(price) + 0.01) - 0.01, 0.99)


def round_to_9(price: np.ndarray) -> np.ndarray:
    """Nearest whole zloty ending in 9 (149, 159), never below 9: symmetric, so it keeps the average price level."""
    return np.maximum(np.round((np.asarray(price) - 9) / 10) * 10 + 9, 9)


def market_reference_net(products: pd.DataFrame) -> pd.Series:
    """Market net price of each product: purchase price times the median markup of its product type (or category)."""
    markup = products["sales_price_net"] / products["net_purchase_price"]
    by_type = markup.groupby(products["product_type"]).transform("median")
    type_size = products.groupby("product_type")["product_id"].transform("size")
    by_category = markup.groupby(products["category"]).transform("median")
    chosen = by_type.where(type_size >= MIN_TYPE_SIZE, by_category)
    return (products["net_purchase_price"] * chosen).rename("market_reference_net")


def build_competitor_prices(products: pd.DataFrame, start, end, seed: int = SEED) -> pd.DataFrame:
    """Competitor list prices with validity periods between start and end, one row per price period."""
    rng = np.random.default_rng([seed, 17])
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    products = products.reset_index(drop=True)
    vat_ratio = (products["sales_price_gross"] / products["sales_price_net"]).to_numpy()
    reference_net = market_reference_net(products).to_numpy()
    first_day = products["launch_date"].clip(lower=start)
    last_day = products["discontinued_date"].fillna(end).clip(upper=end)
    on_sale = (first_day <= last_day).to_numpy()

    frames = []
    for competitor_id, shop in STRATEGIES.items():
        sd = shop["sd"]
        noise = np.exp(rng.normal(0, sd, len(products)) - sd**2 / 2)
        covered = (rng.random(len(products)) < shop["coverage"]) & on_sale
        anchor = reference_net * shop["level"] * noise
        index = np.flatnonzero(covered)
        active_days = (last_day.iloc[index] - first_day.iloc[index]).dt.days.to_numpy() + 1
        changes = rng.poisson(shop["changes_per_year"] * active_days / 365)
        product_index = np.repeat(index, changes + 1)
        is_initial = np.zeros(len(product_index), dtype=bool)
        is_initial[np.cumsum(np.r_[0, changes[:-1] + 1])] = True
        offset = np.where(is_initial, 0, rng.random(len(product_index)) * np.repeat(active_days, changes + 1))
        valid_from = first_day.iloc[product_index].to_numpy() + pd.to_timedelta(offset.astype(int), unit="D")
        frame = pd.DataFrame({"row": product_index, "valid_from": valid_from, "initial": is_initial})
        frame = frame.sort_values(["row", "valid_from", "initial"], ascending=[True, True, False])
        frame = frame.drop_duplicates(["row", "valid_from"], keep="first")

        years = (frame["valid_from"] - start).dt.days.to_numpy() / 365
        wiggle = np.where(frame["initial"], 1.0, np.exp(rng.normal(0, CHANGE_SD, len(frame))))
        net = anchor[frame["row"]] * (1 + MARKET_TREND_PER_YEAR * years) * wiggle
        gross = net * vat_ratio[frame["row"]]
        rounder = round_to_99 if shop["ending"] == "99" else round_to_9
        gross = np.where(gross < 20, round_to_99(gross), rounder(gross))
        frame["price_gross"] = gross
        same = frame["row"].eq(frame["row"].shift()) & frame["price_gross"].eq(frame["price_gross"].shift())
        frame = frame[~same].copy()

        frame["product_id"] = products["product_id"].to_numpy()[frame["row"]]
        frame["price_net"] = np.round(frame["price_gross"] / vat_ratio[frame["row"]], 2)
        previous = frame.groupby("row")["price_gross"].shift()
        frame["change_type"] = np.select(
            [previous.isna(), frame["price_gross"] > previous], ["initial", "increase"], "decrease")
        next_from = frame.groupby("row")["valid_from"].shift(-1)
        discontinued = products["discontinued_date"].to_numpy()[frame["row"]]
        frame["valid_to"] = (next_from - pd.Timedelta(days=1)).fillna(pd.Series(discontinued, index=frame.index))
        frame["competitor_id"] = competitor_id
        frame["competitor_name"] = shop["name"]
        frame["competitor_strategy"] = shop["strategy"]
        frame["true_price_level"] = shop["level"]
        frame["true_market_price_gross"] = np.round(reference_net * vat_ratio, 2)[frame["row"]]
        frames.append(frame)

    table = pd.concat(frames, ignore_index=True).sort_values(["product_id", "competitor_id", "valid_from"])
    table["competitor_price_id"] = np.arange(1, len(table) + 1)
    return table[COMPETITOR_COLUMNS].reset_index(drop=True)
