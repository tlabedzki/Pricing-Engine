import numpy as np
import pandas as pd
import pytest

from pricing_engine.mock_competitors import (
    COMPETITOR_COLUMNS,
    STRATEGIES,
    build_competitor_prices,
    market_reference_net,
    round_to_9,
    round_to_99,
)

START, END = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")


@pytest.fixture(scope="module")
def table(products):
    return build_competitor_prices(products, START, END)


def test_columns_match_the_contract(table):
    assert list(table.columns) == COMPETITOR_COLUMNS
    assert table["competitor_price_id"].is_unique


def test_same_seed_same_table(products, table):
    pd.testing.assert_frame_equal(table, build_competitor_prices(products, START, END))


def test_prices_positive_and_net_below_gross(table):
    assert (table["price_net"] > 0).all()
    assert (table["price_gross"] > table["price_net"]).all()


def test_endings(table):
    cents = np.round(table["price_gross"] % 1, 2)
    whole_nine = (cents == 0) & (table["price_gross"] % 10 == 9)
    premium = table["competitor_strategy"].eq("premium")
    assert (cents[~premium] == 0.99).all()
    assert (whole_nine | (cents == 0.99))[premium].all()
    assert whole_nine[premium & table["price_gross"].ge(30)].all()


def test_periods_are_contiguous_and_do_not_overlap(table):
    ordered = table.sort_values(["product_id", "competitor_id", "valid_from"])
    same = ordered[["product_id", "competitor_id"]].eq(ordered[["product_id", "competitor_id"]].shift()).all(axis=1)
    gap = ordered["valid_from"] - ordered["valid_to"].shift()
    assert (gap[same] == pd.Timedelta(days=1)).all()
    assert (ordered["valid_from"].between(START, END)).all()
    assert (ordered["valid_to"].dropna() >= ordered.loc[ordered["valid_to"].notna(), "valid_from"]).all()


def test_one_open_period_per_active_offer(table, products):
    open_rows = table[table["valid_to"].isna()]
    assert not open_rows.duplicated(["product_id", "competitor_id"]).any()
    active = set(products.loc[products["discontinued_date"].isna(), "product_id"])
    assert set(open_rows["product_id"]) <= active


def test_first_row_is_initial_and_changes_alternate_correctly(table):
    first = table.groupby(["product_id", "competitor_id"]).head(1)
    assert first["change_type"].eq("initial").all()
    previous = table.groupby(["product_id", "competitor_id"])["price_gross"].shift()
    later = previous.notna()
    up = table.loc[later, "price_gross"] > previous[later]
    assert (table.loc[later, "change_type"] == np.where(up, "increase", "decrease")).all()


def test_coverage_and_price_level_follow_the_settings(table, products):
    reference = market_reference_net(products).set_axis(products["product_id"])
    initial = table[table["change_type"].eq("initial") & table["valid_from"].eq(START)]
    ratio = initial["price_net"] / initial["product_id"].map(reference)
    for competitor_id, shop in STRATEGIES.items():
        rows = table["competitor_id"] == competitor_id
        on_sale = (products["discontinued_date"].isna() | (products["discontinued_date"] >= START)).sum()
        assert table.loc[rows, "product_id"].nunique() / on_sale == pytest.approx(shop["coverage"], abs=0.03)
        assert ratio[initial["competitor_id"] == competitor_id].mean() == pytest.approx(shop["level"], abs=0.02)


def test_rounding():
    assert list(round_to_99([149.3, 149.6, 0.2])) == [148.99, 149.99, 0.99]
    assert list(round_to_9([153, 155, 149.4, 3])) == [149, 159, 149, 9]
