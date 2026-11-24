import numpy as np
import pandas as pd
import pytest

from pricing_engine.data import ShopData
from pricing_engine.engine import Rules, baseline_units, current_competitor_prices, propose, round_to_9, snapshot

VAT = 1.23


def product(price=100.0, cost=50.0, elasticity=1.2, market=np.nan, offers=None, units=10.0, discount=0.0):
    return {
        "product_id": 1, "product_name": "Test", "category": "Cat", "brand": "B", "unit_cost": cost,
        "price_gross": price, "price_net": price / VAT, "vat_ratio": VAT, "units_observed": units,
        "units_per_year": units, "average_discount": discount, "elasticity": elasticity, "elasticity_se": 0.1,
        "competitor_median": market, "competitor_min": market,
        "offers": offers if offers is not None else int(np.isfinite(market)),
    }


def run(rules=None, **kwargs):
    return propose(pd.DataFrame([product(**kwargs)]), rules or Rules()).iloc[0]


def test_round_to_9():
    assert list(round_to_9([153, 155, 1003, 2])) == [149, 159, 999, 9]


def test_keeps_the_price_when_the_next_one_passes_the_market_limit():
    row = run(price=99, cost=40, elasticity=0.5, market=100)  # 109 > 100 x 1.05
    assert row.action == "keep"
    assert row.binding == "market_cap"


def test_raise_stops_at_the_market_limit():
    row = run(price=899, cost=300, elasticity=0.5, market=920)
    assert row.proposed_price == 959  # 920 x 1.05 = 966, so 969 is out
    assert row.binding == "market_cap"
    assert row.profit_after > row.profit_before
    assert "limit of +5%" in row.reason


def test_raise_stops_at_the_largest_step():
    row = run(price=899, cost=300, elasticity=0.5, market=1500)
    assert row.proposed_price == 979  # 899 x 1.1 = 988.9, so 989 is out
    assert row.binding == "step_up"
    assert row.change <= 0.10


def test_far_above_the_market_lowers_by_the_largest_step():
    row = run(price=1499, cost=300, elasticity=1.2, market=1000)
    assert row.action == "lower"
    assert row.proposed_price == 1359  # 1499 x 0.9 = 1349.1, so 1349 is out
    assert row.binding == "step_down"


def test_margin_floor_beats_the_market_limit():
    row = run(price=999, cost=700, elasticity=1.2, market=900)
    floor = 700 / 0.85 * VAT  # 1012.9, above the market limit of 945
    assert row.proposed_price >= floor
    assert row.binding == "market_conflict"
    assert "minimum margin" in row.reason


def test_interior_profit_optimum_without_competitors():
    # constant elasticity 3: the best net price is cost x e / (e - 1) = 1.5 x cost
    row = run(price=1999, cost=1000, elasticity=3.0)
    assert row.binding == "profit_optimum"
    assert row.proposed_price == pytest.approx(1.5 * 1000 * VAT, abs=10)
    assert row.offers == 0
    assert "no competitor sells it" in row.reason


def test_keeps_the_price_when_it_is_already_best():
    row = run(price=1849, cost=1000, elasticity=3.0)
    assert row.action == "keep"
    assert row.proposed_price == 1849
    assert row.reason.startswith("Keep")


def test_demand_and_profit_follow_the_elasticity():
    row = run(price=899, cost=300, elasticity=0.5, market=1500, units=100, discount=0.1)
    assert row.units_after == pytest.approx(100 * (979 / 899) ** -0.5)
    assert row.profit_after == pytest.approx(row.units_after * (979 / VAT * 0.9 - 300))


def test_cautious_rules_raise_less():
    base = run(price=999, cost=600, elasticity=1.2, market=1300)
    cautious = run(Rules(max_step=0.05, elasticity_shift=2), price=999, cost=600, elasticity=1.2, market=1300)
    assert cautious.proposed_price < base.proposed_price


def test_every_proposal_keeps_the_rules():
    rng = np.random.default_rng(3)
    rows = []
    for i in range(3000):
        price = round_to_9(rng.lognormal(5, 1))
        market = price * rng.uniform(0.7, 1.4) if rng.random() < 0.9 else np.nan
        rows.append({**product(price=price, cost=price / VAT * rng.uniform(0.4, 0.9), elasticity=rng.uniform(0.3, 2.5),
                               market=market, discount=rng.uniform(0, 0.1)), "product_id": i})
    rules = Rules()
    out = propose(pd.DataFrame(rows), rules)
    conflict = out["binding"].isin(["margin_conflict", "market_conflict", "step_down"])
    assert (out["proposed_price"] % 10 == 9).all()
    assert (out["change"].abs() <= rules.max_step + 1e-9).all()
    assert (out.loc[~out["binding"].eq("margin_conflict"), "margin_after"] >= rules.min_margin - 1e-9).all()
    above = out["index_after"] > 1 + rules.max_above_market + 1e-9
    assert not (above & ~conflict).any()
    assert out["reason"].str.len().gt(20).all()
    assert set(out["action"]) <= {"raise", "lower", "keep"}


def test_competitor_prices_valid_on_the_day():
    offers = pd.DataFrame({
        "product_id": [1, 1, 1, 2], "price_gross": [100.0, 90.0, 300.0, 50.0],
        "valid_from": pd.to_datetime(["2024-01-01", "2024-01-01", "2023-01-01", "2024-12-01"]),
        "valid_to": pd.to_datetime([None, None, "2023-12-31", "2024-12-30"]),
    })
    result = current_competitor_prices(offers, pd.Timestamp("2024-12-31"))
    assert result.loc[1, "competitor_median"] == 95
    assert result.loc[1, "offers"] == 2
    assert 2 not in result.index


def test_baseline_units_shrink_towards_the_category(products):
    on_sale = products[products["discontinued_date"].isna()].head(3)
    orders = pd.DataFrame({
        "product_id": [on_sale["product_id"].iloc[0]] * 4, "quantity": [1, 2, 1, 1],
        "order_date": pd.to_datetime(["2024-03-01", "2024-05-01", "2024-12-31", "2022-01-01"]),
        "order_status": ["delivered", "delivered", "delivered", "delivered"], "discount_rate": [0, 0.2, 0, 0],
        "is_fraud": False,
    })
    shop = ShopData(products, pd.DataFrame(), orders, pd.DataFrame(), {}, True)
    units = baseline_units(shop)
    first = units.loc[on_sale["product_id"].iloc[0]]
    assert first["units_observed"] == 4
    assert 0 < first["units_per_year"] < 4
    assert units["units_per_year"].gt(0).any()
    assert set(units.index) <= set(products["product_id"])


def test_snapshot_joins_elasticity_and_competitors(products):
    orders = pd.DataFrame({
        "product_id": products["product_id"].head(50), "quantity": 1, "order_date": pd.Timestamp("2024-12-31"),
        "order_status": "delivered", "discount_rate": 0.0, "is_fraud": False,
    })
    from pricing_engine.mock_competitors import build_competitor_prices

    competitors = build_competitor_prices(products, "2023-01-01", "2024-12-31")
    shop = ShopData(products, pd.DataFrame(), orders, competitors, {}, True)
    elasticity = pd.DataFrame({"category": ["Electronics", "Health", "Clothing"], "elasticity": [1.6, 0.6, 1.8],
                               "elasticity_se": 0.1})
    table = snapshot(shop, elasticity)
    assert table["elasticity"].notna().all()
    assert table["offers"].between(0, 4).all()
    assert (table.loc[table["offers"] > 0, "competitor_median"] > 0).all()
    out = propose(table)
    assert len(out) == len(table)


def test_a_competitor_promotion_counts_at_the_regular_price():
    offers = pd.DataFrame({
        "product_id": [1, 1, 1, 1], "competitor_id": [5, 5, 5, 1], "price_gross": [100.0, 70.0, 100.0, 90.0],
        "valid_from": pd.to_datetime(["2024-01-01", "2024-12-28", "2025-01-02", "2024-01-01"]),
        "valid_to": pd.to_datetime(["2024-12-27", "2025-01-01", None, None]),
        "is_promotion": [False, True, False, False],
    })
    result = current_competitor_prices(offers, pd.Timestamp("2024-12-31"))
    assert result.loc[1, "competitor_min"] == 90
    assert result.loc[1, "competitor_median"] == 95
    assert result.loc[1, "offers"] == 2
