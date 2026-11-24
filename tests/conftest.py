import numpy as np
import pandas as pd
import pytest

CATEGORIES = ("Electronics", "Health", "Clothing")


def make_products(n: int = 3000, seed: int = 0) -> pd.DataFrame:
    """A small catalogue shaped like Data-Generator product_data (no files needed, so CI runs without data)."""
    rng = np.random.default_rng(seed)
    cost = np.round(rng.lognormal(4.5, 0.8, n), 2)
    margin = rng.uniform(0.2, 0.5, n)
    net = np.round(cost / (1 - margin), 2)
    gross = np.round(net * 1.23)
    launch = pd.Timestamp("2022-06-01") + pd.to_timedelta(rng.integers(0, 800, n), unit="D")
    discontinued = pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns]")
    stop = rng.random(n) < 0.15
    discontinued[stop] = launch[stop] + pd.to_timedelta(rng.integers(120, 400, stop.sum()), unit="D")
    return pd.DataFrame({
        "product_id": np.arange(200001, 200001 + n),
        "category": rng.choice(CATEGORIES, n),
        "subcategory": "Sub",
        "product_type": rng.choice(["Type A", "Type B", "Type C", "Rare"], n, p=[0.4, 0.3, 0.295, 0.005]),
        "brand": "Brand",
        "product_name": [f"Product {i}" for i in range(n)],
        "net_purchase_price": cost,
        "sales_price_net": np.round(gross / 1.23, 2),
        "sales_price_gross": gross,
        "sales_margin": margin,
        "product_popularity": rng.lognormal(0, 1, n),
        "launch_date": launch,
        "discontinued_date": discontinued,
    })


@pytest.fixture(scope="session")
def products() -> pd.DataFrame:
    return make_products()
