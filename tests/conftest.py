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


def write_shop(directory, products: pd.DataFrame, lines: int = 6000, seed: int = 0) -> None:
    """Write a tiny shop in the Data-Generator layout: products, price history, order lines and truth.json."""
    import json

    rng = np.random.default_rng(seed)
    start, end = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")
    history = []
    for row in products.itertuples():
        first = max(row.launch_date, start)
        price = row.sales_price_gross / rng.uniform(1.0, 1.15)
        history.append((row.product_id, first, price))
        if rng.random() < 0.6:
            change = first + pd.Timedelta(days=int(rng.integers(30, 300)))
            history.append((row.product_id, change, row.sales_price_gross))
    history = pd.DataFrame(history, columns=["product_id", "valid_from", "sales_price_gross"])
    history = history[history["valid_from"] <= end].sort_values(["product_id", "valid_from"])
    history["valid_to"] = history.groupby("product_id")["valid_from"].shift(-1) - pd.Timedelta(days=1)
    history["sales_price_net"] = (history["sales_price_gross"] / 1.23).round(2)
    history["change_type"] = np.where(history.duplicated("product_id"), "increase", "initial")
    history.to_parquet(directory / "price_history.parquet")
    products.to_parquet(directory / "product_data.parquet")

    day = start + pd.to_timedelta(rng.integers(0, 731, lines), unit="D")
    discount = np.where(rng.random(lines) < 0.3, rng.uniform(0.05, 0.3, lines), 0.0)
    pd.DataFrame({
        "order_id": np.arange(lines), "order_line_id": np.arange(lines), "order_date": day,
        "product_id": rng.choice(products["product_id"], lines), "quantity": 1 + rng.poisson(0.3, lines),
        "unit_price_gross": 100.0, "unit_price_net": 81.3, "discount_rate": discount,
        "order_status": rng.choice(["delivered", "returned", "cancelled"], lines, p=[0.85, 0.1, 0.05]),
        "is_fraud": rng.random(lines) < 0.01,
    }).to_parquet(directory / "order_data.parquet")
    truth = {"category_price_elasticity": {"Health": 0.6, "Clothing": 1.8}, "default_price_elasticity": 1.2,
             "source": {"tag": "test", "seed": 0}}
    (directory / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
