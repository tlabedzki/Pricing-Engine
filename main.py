"""
Pricing Engine command line.

    python main.py                       # everything: elasticity, proposals, scenarios, files in output/
    python main.py elasticity            # elasticity per category next to the truth
    python main.py propose --max-step 0.05 --max-above-market 0 --min-margin 0.2
    python main.py simulate              # the three scenarios and the check against the true elasticity
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pricing_engine import data, elasticity, engine, simulate  # noqa: E402

OUTPUT = ROOT / "output"


def pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def money(value: float) -> str:
    return f"{value / 1e6:.2f} mln PLN"


def show_elasticity(table) -> None:
    print("\nPrice elasticity per category (estimate, 90% interval, truth from Data-Generator)")
    for row in table.itertuples():
        low, high = row.elasticity - 1.645 * row.elasticity_se, row.elasticity + 1.645 * row.elasticity_se
        mark = "ok" if low <= row.true_elasticity <= high else "  "
        print(f"  {row.category:<22} {row.elasticity:5.2f}  [{low:4.2f}, {high:4.2f}]  truth {row.true_elasticity:4.2f}"
              f"  {mark}")
    error = (table["elasticity"] - table["true_elasticity"]).abs().mean()
    print(f"  mean absolute error {error:.2f}")


def show_totals(name: str, row) -> None:
    print(f"  {name:<9} profit {money(row['profit_before'])} -> {money(row['profit_after'])} "
          f"({pct(row['profit_change'])}), revenue {pct(row['revenue_change'])}, units {pct(row['units_change'])}; "
          f"raise {int(row['raise'])}, lower {int(row['lower'])}, keep {int(row['keep'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="all", choices=["all", "elasticity", "propose", "simulate"])
    defaults = engine.Rules()
    parser.add_argument("--min-margin", type=float, default=defaults.min_margin)
    parser.add_argument("--max-above-market", type=float, default=defaults.max_above_market)
    parser.add_argument("--max-step", type=float, default=defaults.max_step)
    parser.add_argument("--data", type=Path, default=data.RAW_DIR, help="directory with the Parquet tables")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="directory for the CSV and JSON results")
    args = parser.parse_args()

    try:
        shop = data.load(args.data)
    except FileNotFoundError as error:
        raise SystemExit(str(error)) from None
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    source = shop.truth.get("source", {})
    print(f"Lumo shop data: Data-Generator {source.get('tag', '?')}, seed {source.get('seed', '?')}; "
          f"{len(shop.products):,} products, {len(shop.orders):,} order lines, "
          f"{len(shop.competitor_prices):,} competitor price periods{' (mock)' if shop.competitors_are_mock else ''}")

    table = elasticity.estimate(shop)
    table.to_csv(output / "elasticity.csv", index=False)
    if args.command in ("all", "elasticity"):
        show_elasticity(table)
    if args.command == "elasticity":
        return

    snap = engine.snapshot(shop, table)
    rules = engine.Rules(min_margin=args.min_margin, max_above_market=args.max_above_market, max_step=args.max_step)
    proposals = engine.propose(snap, rules)
    proposals.to_csv(output / "proposals.csv", index=False, float_format="%.4f")
    simulate.totals(proposals, "category").to_csv(output / "categories.csv", index=False, float_format="%.4f")
    if args.command in ("all", "propose"):
        print(f"\nProposals for {len(proposals):,} products on sale on {shop.end_date:%Y-%m-%d} "
              f"(min margin {rules.min_margin:.0%}, at most {rules.max_above_market:+.0%} over the competitor median, "
              f"steps up to {rules.max_step:.0%})")
        show_totals("rules", simulate.totals(proposals).iloc[0])
        for row in proposals.sort_values("profit_after", key=lambda s: s - proposals["profit_before"],
                                         ascending=False).head(3).itertuples():
            print(f"  {row.product_name[:40]:<40} {row.current_price:8.0f} -> {row.proposed_price:8.0f}  {row.reason}")
        print("  saved output/proposals.csv and output/categories.csv")
    if args.command == "propose":
        return

    print("\nScenarios")
    frame = simulate.scenarios(snap)
    frame.to_csv(output / "scenarios.csv", index=False, float_format="%.4f")
    for row in frame.to_dict("records"):
        show_totals(row["scenario"], row)
    base = engine.propose(snap, simulate.SCENARIOS["base"])
    truth = simulate.totals(simulate.evaluate(base, shop.true_elasticity())).iloc[0]
    spread = simulate.uncertainty(base, table)
    low, high = spread["profit_change"].quantile([0.05, 0.95])
    print(f"\nBase scenario profit change: estimated {pct(simulate.totals(base).iloc[0]['profit_change'])} "
          f"(90% interval {pct(low)} to {pct(high)}), with the true elasticity {pct(truth['profit_change'])}")

    summary = {
        "data": {**source, "products": len(shop.products), "products_on_sale": len(snap),
                 "order_lines": len(shop.orders), "competitor_price_periods": len(shop.competitor_prices)},
        "elasticity_mean_absolute_error": float((table["elasticity"] - table["true_elasticity"]).abs().mean()),
        "elasticity_truth_in_90_interval": int(((table["true_elasticity"] - table["elasticity"]).abs()
                                                <= 1.645 * table["elasticity_se"]).sum()),
        "categories": len(table),
        "scenarios": {row["scenario"]: {k: row[k] for k in ("profit_change", "revenue_change", "units_change",
                                                             "raise", "lower", "keep")}
                      for row in frame.to_dict("records")},
        "base_true_profit_change": float(truth["profit_change"]),
        "base_true_revenue_change": float(truth["revenue_change"]),
        "base_profit_change_interval": [float(low), float(high)],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print("Saved output/elasticity.csv, proposals.csv, categories.csv, scenarios.csv and summary.json")


if __name__ == "__main__":
    main()
