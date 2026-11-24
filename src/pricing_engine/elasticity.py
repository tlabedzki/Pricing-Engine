"""
Price elasticity per category, estimated from the shop data and checked against the truth from Data-Generator.

Two signals carry the same parameter in the data:

* list price: when a product's list price goes up, its share of the category's order lines goes down. Estimated
  within each product (conditional Poisson: the product's lines spread over its price periods in proportion to
  exposure x price ** -elasticity), so product popularity cancels out;
* discount: a discounted line sells more units, expected quantity x (1 - discount) ** -elasticity (Poisson
  regression of quantity on -log(1 - discount)).

Both estimates get cluster-robust standard errors, are combined by inverse variance and then shrunk towards the
average of all categories (empirical Bayes), so a category with few sales borrows strength from the rest.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar

from pricing_engine.data import ShopData

SQL_DIR = Path(__file__).with_name("sql")
MIN_ELASTICITY = 0.1


def price_periods(shop: ShopData) -> pd.DataFrame:
    """Lines and exposure of every list-price period (SQL in sql/price_periods.sql, run by DuckDB)."""
    query = (SQL_DIR / "price_periods.sql").read_text(encoding="utf-8")
    with duckdb.connect() as con:
        con.register("orders", shop.orders)
        con.register("products", shop.products)
        con.register("price_history", shop.price_history)
        return con.execute(query, {"end_date": shop.end_date.date()}).df()


def _group_sum(groups: np.ndarray, values: np.ndarray, size: int) -> np.ndarray:
    return np.bincount(groups, values, minlength=size)


def fit_list_price(periods: pd.DataFrame) -> dict[str, float]:
    """Conditional Poisson estimate of the elasticity from list-price changes within products of one category."""
    sold = periods.groupby("product_id")["lines"].transform("sum") > 0
    changed = periods.groupby("product_id")["price_gross"].transform("nunique") > 1
    data = periods[sold & changed & (periods["exposure"] > 0)]
    if data.empty:
        return {"estimate": np.nan, "se": np.nan, "products": 0, "lines": 0}
    group = pd.factorize(data["product_id"])[0]
    size = group.max() + 1
    lines = data["lines"].to_numpy(float)
    log_price = np.log(data["price_gross"].to_numpy())
    log_price -= (_group_sum(group, log_price, size) / np.bincount(group))[group]
    log_exposure = np.log(data["exposure"].to_numpy())
    total = _group_sum(group, lines, size)

    def shares(elasticity: float) -> np.ndarray:
        z = log_exposure - elasticity * log_price
        z -= pd.Series(z).groupby(group).transform("max").to_numpy()
        weight = np.exp(z)
        return weight / _group_sum(group, weight, size)[group]

    def negative_log_likelihood(elasticity: float) -> float:
        return -np.sum(lines * np.log(shares(elasticity)))

    elasticity = minimize_scalar(negative_log_likelihood, bounds=(-3, 6), method="bounded").x
    share = shares(elasticity)
    mean_x = _group_sum(group, share * log_price, size)
    var_x = _group_sum(group, share * log_price**2, size) - mean_x**2
    score = -_group_sum(group, lines * log_price, size) + total * mean_x
    information = np.sum(total * var_x)
    se = np.sqrt(np.sum(score**2)) / information
    return {"estimate": elasticity, "se": se, "products": int(size), "lines": int(lines.sum())}


def fit_discount(quantity: np.ndarray, discount: np.ndarray) -> dict[str, float]:
    """Poisson regression log E[quantity] = a + elasticity * -log(1 - discount), with sandwich standard errors."""
    quantity = np.asarray(quantity, float)
    x = -np.log(1 - np.asarray(discount, float))
    if (x > 0).sum() < 2:
        return {"estimate": np.nan, "se": np.nan, "lines": int((x > 0).sum())}
    design = np.column_stack([np.ones_like(x), x])

    def negative_log_likelihood(beta: np.ndarray) -> float:
        mu = np.exp(design @ beta)
        return -(quantity * np.log(mu) - mu).sum()

    def gradient(beta: np.ndarray) -> np.ndarray:
        return -design.T @ (quantity - np.exp(design @ beta))

    beta = minimize(negative_log_likelihood, [np.log(quantity.mean()), 1.0], jac=gradient, method="BFGS").x
    mu = np.exp(design @ beta)
    bread = np.linalg.inv((design * mu[:, None]).T @ design)
    residual = design * (quantity - mu)[:, None]
    covariance = bread @ (residual.T @ residual) @ bread
    return {"estimate": beta[1], "se": float(np.sqrt(covariance[1, 1])), "lines": int((x > 0).sum())}


def combine(first: np.ndarray, first_se: np.ndarray, second: np.ndarray, second_se: np.ndarray):
    """Inverse-variance average of two estimates of the same parameter (a missing one is skipped)."""
    w1 = np.where(np.isfinite(first), 1 / np.asarray(first_se) ** 2, 0)
    w2 = np.where(np.isfinite(second), 1 / np.asarray(second_se) ** 2, 0)
    estimate = (np.nan_to_num(first) * w1 + np.nan_to_num(second) * w2) / (w1 + w2)
    return estimate, 1 / np.sqrt(w1 + w2)


def shrink(estimate: np.ndarray, se: np.ndarray):
    """
    Empirical Bayes shrinkage towards the precision-weighted mean; the spread between categories (tau^2) by the
    DerSimonian-Laird estimator. Returns posterior means and standard deviations.
    """
    estimate, se = np.asarray(estimate, float), np.asarray(se, float)
    weight = 1 / se**2
    mean = np.sum(weight * estimate) / weight.sum()
    q = np.sum(weight * (estimate - mean) ** 2)
    tau2 = max(0.0, (q - (len(estimate) - 1)) / (weight.sum() - np.sum(weight**2) / weight.sum()))
    if tau2 == 0:
        return np.full_like(estimate, mean), np.full_like(se, 1 / np.sqrt(weight.sum()))
    posterior_weight = weight + 1 / tau2
    posterior = (weight * estimate + mean / tau2) / posterior_weight
    return posterior, 1 / np.sqrt(posterior_weight)


def estimate(shop: ShopData) -> pd.DataFrame:
    """Elasticity per category from both signals, combined and shrunk, next to the true value."""
    periods = price_periods(shop)
    lines = shop.orders.loc[~shop.orders["is_fraud"], ["product_id", "quantity", "discount_rate"]]
    lines = lines.merge(shop.products[["product_id", "category"]], on="product_id")
    rows = []
    for category in sorted(shop.products["category"].unique()):
        price = fit_list_price(periods[periods["category"] == category])
        in_category = lines[lines["category"] == category]
        discount = fit_discount(in_category["quantity"], in_category["discount_rate"])
        rows.append({
            "category": category,
            "list_price": price["estimate"], "list_price_se": price["se"],
            "products_with_price_changes": price["products"], "lines": len(in_category),
            "discount": discount["estimate"], "discount_se": discount["se"], "discounted_lines": discount["lines"],
        })
    table = pd.DataFrame(rows)
    table["combined"], table["combined_se"] = combine(
        table["list_price"], table["list_price_se"], table["discount"], table["discount_se"])
    table["elasticity"], table["elasticity_se"] = shrink(table["combined"], table["combined_se"])
    table["elasticity"] = table["elasticity"].clip(lower=MIN_ELASTICITY)
    truth = shop.true_elasticity()
    table["true_elasticity"] = table["category"].map(truth)
    return table
