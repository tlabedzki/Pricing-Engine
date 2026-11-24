import json

import pandas as pd
import pytest

from pricing_engine import data


def write_shop(directory, products):
    products.to_parquet(directory / "product_data.parquet")
    pd.DataFrame({
        "product_id": products["product_id"], "valid_from": pd.Timestamp("2023-01-01"), "valid_to": pd.NaT,
        "sales_price_gross": products["sales_price_gross"], "sales_price_net": products["sales_price_net"],
        "change_type": "initial",
    }).to_parquet(directory / "price_history.parquet")
    pd.DataFrame({
        "order_id": [1, 2], "order_line_id": [1, 2], "order_date": pd.to_datetime(["2023-01-01", "2024-12-31"]),
        "product_id": products["product_id"].iloc[:2].to_numpy(), "quantity": [1, 2], "unit_price_gross": [10.0, 20.0],
        "unit_price_net": [8.13, 16.26], "discount_rate": [0.0, 0.1], "order_status": "delivered", "is_fraud": False,
    }).to_parquet(directory / "order_data.parquet")
    truth = {"category_price_elasticity": {"Health": 0.6}, "default_price_elasticity": 1.2}
    (directory / "truth.json").write_text(json.dumps(truth), encoding="utf-8")


def test_load_builds_the_mock_competitor_table(tmp_path, products):
    write_shop(tmp_path, products)
    shop = data.load(tmp_path)
    assert shop.competitors_are_mock
    assert len(shop.competitor_prices) > len(products)
    assert shop.end_date == pd.Timestamp("2024-12-31")
    assert shop.true_elasticity() == {"Clothing": 1.2, "Electronics": 1.2, "Health": 0.6}


def test_load_prefers_the_real_competitor_table(tmp_path, products):
    write_shop(tmp_path, products)
    real = data.load(tmp_path).competitor_prices.head(10)
    real.to_parquet(tmp_path / "competitor_prices.parquet")
    shop = data.load(tmp_path)
    assert not shop.competitors_are_mock
    assert len(shop.competitor_prices) == 10


def test_missing_data_says_how_to_get_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="get_data.py"):
        data.load(tmp_path)
