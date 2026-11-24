"""Load the shop tables made by Data-Generator (scripts/get_data.py) from data/raw/."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
DATA_GENERATOR_TAG = "v1.7.1"
TABLES = ("product_data", "price_history", "order_data", "competitor_prices")

PRODUCT_COLUMNS = [
    "product_id", "category", "subcategory", "product_type", "brand", "product_name", "net_purchase_price",
    "sales_price_net", "sales_price_gross", "sales_margin", "product_popularity", "launch_date", "discontinued_date",
]
ORDER_COLUMNS = [
    "order_id", "order_line_id", "order_date", "product_id", "quantity", "unit_price_gross", "unit_price_net",
    "discount_rate", "order_status", "is_fraud",
]


@dataclass
class ShopData:
    """The tables the engine reads. `competitor_prices` is the mock table only for releases before v1.5.0."""

    products: pd.DataFrame
    price_history: pd.DataFrame
    orders: pd.DataFrame
    competitor_prices: pd.DataFrame
    truth: dict
    competitors_are_mock: bool

    @property
    def end_date(self) -> pd.Timestamp:
        return self.orders["order_date"].max()

    def true_elasticity(self) -> dict[str, float]:
        """True price elasticity of every category in the data, from Data-Generator settings."""
        explicit = self.truth["category_price_elasticity"]
        default = self.truth["default_price_elasticity"]
        return {category: explicit.get(category, default) for category in sorted(self.products["category"].unique())}


def missing_data_message(directory: Path) -> str:
    return f"No shop data in {directory}. Run: python scripts/get_data.py"


def load(directory: Path = RAW_DIR) -> ShopData:
    """Read the Parquet tables and truth.json; build the mock competitor table when the release has none."""
    if not (directory / "product_data.parquet").exists():
        raise FileNotFoundError(missing_data_message(directory))
    products = pd.read_parquet(directory / "product_data.parquet", columns=PRODUCT_COLUMNS)
    price_history = pd.read_parquet(directory / "price_history.parquet")
    orders = pd.read_parquet(directory / "order_data.parquet", columns=ORDER_COLUMNS)
    truth = json.loads((directory / "truth.json").read_text(encoding="utf-8"))

    competitor_file = directory / "competitor_prices.parquet"
    if competitor_file.exists():
        competitor_prices = pd.read_parquet(competitor_file)
        mock = False
    else:
        from pricing_engine.mock_competitors import build_competitor_prices

        end = orders["order_date"].max()
        competitor_prices = build_competitor_prices(products, start=orders["order_date"].min(), end=end)
        mock = True
    return ShopData(products, price_history, orders, competitor_prices, truth, mock)
