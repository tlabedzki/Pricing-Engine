import numpy as np
import pandas as pd
import pytest

from pricing_engine.elasticity import combine, fit_discount, fit_list_price, shrink


def simulated_periods(elasticity: float, products: int = 3000, seed: int = 1) -> pd.DataFrame:
    """Products with 1-4 list-price periods; lines ~ Poisson(popularity x exposure x price ** -elasticity)."""
    rng = np.random.default_rng(seed)
    rows = []
    for product_id in range(products):
        popularity = rng.lognormal(0, 1)
        price = rng.lognormal(5, 0.7)
        for period in range(rng.integers(1, 5)):
            if period:
                price *= rng.choice([rng.uniform(1.02, 1.12), rng.uniform(0.80, 0.95)], p=[0.75, 0.25])
            exposure = rng.uniform(5, 60) / 100
            mean = 30 * popularity * exposure * (price / 150) ** -elasticity
            rows.append((product_id, "Cat", price, rng.poisson(mean), exposure))
    return pd.DataFrame(rows, columns=["product_id", "category", "price_gross", "lines", "exposure"])


@pytest.mark.parametrize("truth", [0.6, 1.8])
def test_list_price_estimate_recovers_the_truth(truth):
    result = fit_list_price(simulated_periods(truth))
    assert result["estimate"] == pytest.approx(truth, abs=3 * result["se"])
    assert result["se"] < 0.15


def test_list_price_ignores_products_without_a_price_change():
    periods = simulated_periods(1.2, products=300)
    single = periods.groupby("product_id")["price_gross"].transform("nunique") == 1
    sold = periods.groupby("product_id")["lines"].transform("sum") > 0
    assert fit_list_price(periods)["products"] == periods.loc[~single & sold, "product_id"].nunique()
    assert np.isnan(fit_list_price(periods[single])["estimate"])


@pytest.mark.parametrize("truth", [0.6, 1.6])
def test_discount_estimate_recovers_the_truth(truth):
    rng = np.random.default_rng(2)
    n = 40_000
    discount = np.where(rng.random(n) < 0.3, rng.uniform(0.05, 0.4, n), 0.0)
    base = rng.choice([1, 2, 3], n, p=[0.7, 0.2, 0.1])
    quantity = base + rng.poisson(base * ((1 - discount) ** -truth - 1))
    result = fit_discount(quantity, discount)
    assert result["estimate"] == pytest.approx(truth, abs=3 * result["se"])
    assert result["lines"] == (discount > 0).sum()


def test_discount_needs_discounted_lines():
    assert np.isnan(fit_discount([1, 2, 1], [0, 0, 0])["estimate"])


def test_combine_weights_by_precision_and_skips_missing():
    estimate, se = combine(np.array([1.0, np.nan]), np.array([0.1, np.nan]), np.array([2.0, 1.5]), np.array([0.2, 0.3]))
    assert estimate[0] == pytest.approx((1 / 0.01 + 2 / 0.04) / (1 / 0.01 + 1 / 0.04))
    assert se[0] == pytest.approx(1 / np.sqrt(1 / 0.01 + 1 / 0.04))
    assert estimate[1] == pytest.approx(1.5)
    assert se[1] == pytest.approx(0.3)


def test_shrink_pulls_noisy_estimates_harder():
    estimate = np.array([0.6, 1.0, 1.2, 1.4, 1.8, 3.0])
    se = np.array([0.05, 0.05, 0.05, 0.05, 0.05, 1.0])
    posterior, posterior_se = shrink(estimate, se)
    assert abs(posterior[0] - 0.6) < 0.01
    assert posterior[-1] < 2.0
    assert (posterior_se <= se).all()


def test_shrink_without_spread_returns_the_common_mean():
    posterior, _ = shrink(np.array([1.0, 1.01, 0.99]), np.array([0.2, 0.2, 0.2]))
    assert np.allclose(posterior, 1.0)


def test_price_periods_counts_lines_in_each_period():
    from pricing_engine.data import ShopData
    from pricing_engine.elasticity import price_periods

    products = pd.DataFrame({
        "product_id": [1, 2], "category": ["Cat", "Cat"], "product_popularity": [1.0, 3.0],
        "launch_date": pd.to_datetime(["2022-01-01", "2023-01-10"]), "discontinued_date": pd.NaT,
    })
    history = pd.DataFrame({
        "product_id": [1, 1, 2], "valid_from": pd.to_datetime(["2023-01-01", "2023-01-06", "2023-01-10"]),
        "valid_to": pd.to_datetime(["2023-01-05", None, None]), "sales_price_gross": [100.0, 110.0, 50.0],
    })
    orders = pd.DataFrame({
        "product_id": [1, 1, 1, 2, 1], "order_date": pd.to_datetime(
            ["2023-01-02", "2023-01-07", "2023-01-12", "2023-01-12", "2023-01-03"]),
        "is_fraud": [False, False, False, False, True], "quantity": 1, "discount_rate": 0.0,
    })
    shop = ShopData(products, history, orders, pd.DataFrame(), {}, True)
    periods = price_periods(shop)
    assert periods["lines"].tolist() == [1, 2, 1]
    assert periods["valid_to"].max() == pd.Timestamp("2023-01-12")
    # 2023-01-02 (one line, pool 1), 2023-01-07 (one line, pool 1), 2023-01-12 (two lines, pool 1 + 3)
    assert periods["exposure"].tolist() == pytest.approx([1.0, 1.0 + 0.5, 0.5])


def test_shrink_gives_a_category_without_signal_the_pooled_mean():
    posterior, posterior_se = shrink(np.array([1.0, 1.4, np.nan]), np.array([0.1, 0.1, np.nan]))
    assert np.isfinite(posterior).all() and np.isfinite(posterior_se).all()
    assert posterior[2] == pytest.approx(1.2)
