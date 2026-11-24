"""
Render the README charts to docs/img/ and write the README numbers between its `<!-- generated:... -->` markers.

    python scripts/make_charts.py              # Polish notation (README of the private repo)
    python scripts/make_charts.py --lang en    # English notation, for the public release

Needs the data from scripts/get_data.py. Charts use the light palette of the dataviz skill on a solid white background,
so they look the same in GitHub's light and dark themes. Two runs give the same bytes.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pricing_engine import data, elasticity, engine, simulate  # noqa: E402

IMG = ROOT / "docs" / "img"
README = ROOT / "README.md"

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
INK, INK_2, MUTED, GRID, AXIS, KEEP = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#b5b3ab"
DPI = 200
WIDTH = 8.0

TEXT = {
    "pl": {
        "elasticity_title": "Szacunek elastyczności trafia w prawdę w {hits} z {n} kategorii",
        "elasticity_sub": "Punkt: szacunek z danych z 90% przedziałem. Romb: prawdziwa wartość z Data-Generatora.",
        "estimate": "szacunek", "truth": "prawda", "elasticity_axis": "elastyczność ceny (o ile % spada popyt po "
                                                                      "podwyżce o 1%)",
        "index_title": "W progu +5% nad konkurencją: dziś {before} produktów, po zmianach {share}",
        "index_sub": "Rozkład indeksu ceny: nasza cena / mediana cen konkurencji, produkty z co najmniej jedną ofertą.",
        "before": "dziś", "after": "po propozycjach", "index_axis": "indeks ceny", "median": "mediana konkurencji",
        "limit": "próg +5%", "products_axis": "produkty",
        "rules_title": "Cenę najczęściej zatrzymuje próg konkurencji albo maksymalny krok",
        "rules_sub": "Liczba produktów według reguły, która zdecydowała o propozycji (scenariusz bazowy).",
        "raise": "podnieś", "lower": "obniż", "keep": "zostaw",
        "rule_names": {
            "market_cap": "próg +5% nad konkurencją", "step_up": "maks. krok w górę (10%)",
            "step_down": "maks. krok w dół (10%)", "market_conflict": "minimalna marża ponad progiem konkurencji",
            "margin_conflict": "marża poniżej 15% mimo maks. kroku", "profit_optimum": "najwyższy zysk w regułach",
            "margin_floor": "minimalna marża 15%",
        },
        "scenario_title": "Scenariusz bazowy: {profit} zysku brutto przy {revenue} obrotu",
        "scenario_sub": "Zmiana rocznego zysku brutto i obrotu netto. Romb: zysk liczony z prawdziwą elastycznością.",
        "profit": "zysk brutto", "revenue": "obrót netto", "true_profit": "zysk przy prawdziwej elastyczności",
        "scenarios": {"cautious": "ostrożny", "base": "bazowy", "bold": "odważny"},
        "categories_title": "Najwięcej zyskuje {top}: {top_value}",
        "categories_sub": "Zmiana rocznego zysku brutto w kategorii, scenariusz bazowy.",
        "change_axis": "zmiana",
        "categories": {
            "Automotive": "Motoryzacja", "Baby & Kids": "Dziecko", "Beauty": "Uroda",
            "Books & Media": "Książki i media",
            "Clothing": "Odzież", "DIY Tools": "Narzędzia", "Electronics": "Elektronika", "Furniture": "Meble",
            "Health": "Zdrowie", "Home & Garden": "Dom i ogród", "Jewelry & Accessories": "Biżuteria",
            "Office": "Biuro", "Pet Supplies": "Zwierzęta", "Sports": "Sport", "Toys": "Zabawki",
        },
    },
    "en": {
        "elasticity_title": "The elasticity estimate hits the truth in {hits} of {n} categories",
        "elasticity_sub": "Dot: estimate from the data with a 90% interval. "
                          "Diamond: the true value from Data-Generator.",
        "estimate": "estimate", "truth": "truth",
        "elasticity_axis": "price elasticity (how many % demand falls after a 1% price rise)",
        "index_title": "Within +5% of the competitors: {before} of products today, {share} after the changes",
        "index_sub": "Price index: our price / median competitor price, products with at least one competitor offer.",
        "before": "today", "after": "after proposals", "index_axis": "price index", "median": "competitor median",
        "limit": "limit +5%", "products_axis": "products",
        "rules_title": "The competitor limit or the largest step stops most prices",
        "rules_sub": "Products by the rule that decided the proposal (base scenario).",
        "raise": "raise", "lower": "lower", "keep": "keep",
        "rule_names": {
            "market_cap": "limit +5% over competitors", "step_up": "largest step up (10%)",
            "step_down": "largest step down (10%)", "market_conflict": "minimum margin above the competitor limit",
            "margin_conflict": "margin below 15% after the largest step",
            "profit_optimum": "highest profit in the rules",
            "margin_floor": "minimum margin 15%",
        },
        "scenario_title": "Base scenario: {profit} gross profit at {revenue} revenue",
        "scenario_sub": "Change in yearly gross profit and net revenue. Diamond: profit with the true elasticity.",
        "profit": "gross profit", "revenue": "net revenue", "true_profit": "profit with the true elasticity",
        "scenarios": {"cautious": "cautious", "base": "base", "bold": "bold"},
        "categories_title": "{top} gains the most: {top_value}",
        "categories_sub": "Change in yearly gross profit per category, base scenario.",
        "change_axis": "change",
        "categories": {},
    },
}


class Format:
    def __init__(self, lang: str):
        self.lang = lang

    def number(self, value: float, decimals: int = 0) -> str:
        text = f"{value:,.{decimals}f}"
        if self.lang == "pl":
            text = text.replace(",", " ").replace(".", ",")
        return text

    def pct(self, value: float, decimals: int = 1, sign: bool = True) -> str:
        sign = sign and round(value * 100, decimals) != 0
        text = f"{value * 100:{'+' if sign else ''}.{decimals}f}%"
        text = text.replace("-", "−")
        return text.replace(".", ",") if self.lang == "pl" else text

    def money(self, value: float) -> str:
        if self.lang == "pl":
            return f"{self.number(value / 1e6, 2)} mln zł"
        return f"PLN {value / 1e6:.2f}M"


def style() -> None:
    plt.rcParams.update({
        "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK_2,
        "xtick.color": INK_2, "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "figure.facecolor": "#ffffff", "axes.facecolor": "#ffffff", "savefig.facecolor": "#ffffff",
        "svg.hashsalt": "pricing-engine", "legend.frameon": False,
    })


def save(fig, name: str) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / name, dpi=DPI, bbox_inches="tight", pad_inches=0.3, metadata={"Software": None})
    plt.close(fig)


def new_figure(height: float, top: float):
    fig, ax = plt.subplots(figsize=(WIDTH, height))
    fig.subplots_adjust(left=0.0, right=1.0, top=top, bottom=0.0)
    return fig, ax


def place_titles(fig, ax, title: str, subtitle: str) -> None:
    """Title and subtitle aligned with the left edge of the tick labels, above the plot."""
    fig.canvas.draw()
    left = min(t.get_window_extent().x0 for t in ax.get_yticklabels() if t.get_text()) / fig.bbox.width
    fig.text(left, 1.0, title, ha="left", va="bottom", fontsize=13.5, family="Segoe UI Semibold", color=INK)
    fig.text(left, 0.995, subtitle, ha="left", va="top", fontsize=9.5, color=INK_2)


def label_category(text: dict, category: str) -> str:
    return text["categories"].get(category, category)


def chart_elasticity(table: pd.DataFrame, text: dict, fmt: Format) -> dict:
    t = table.sort_values("true_elasticity").reset_index(drop=True)
    low = t["elasticity"] - 1.645 * t["elasticity_se"]
    high = t["elasticity"] + 1.645 * t["elasticity_se"]
    hit = (t["true_elasticity"] >= low) & (t["true_elasticity"] <= high)
    fig, ax = new_figure(5.6, 0.9)
    y = np.arange(len(t))
    ax.hlines(y, low, high, color=BLUE, linewidth=2, alpha=0.45, capstyle="round")
    ax.scatter(t["elasticity"], y, s=46, color=BLUE, zorder=3, label=text["estimate"], edgecolor="white", linewidth=1.2)
    ax.scatter(t["true_elasticity"], y, s=52, marker="D", color=ORANGE, zorder=4, label=text["truth"],
               edgecolor="white", linewidth=1.2)
    ax.set_yticks(y, [label_category(text, c) for c in t["category"]])
    for tick, ok in zip(ax.get_yticklabels(), hit, strict=True):
        tick.set_color(INK if ok else RED)
    ax.set_xlabel(text["elasticity_axis"])
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(high.max(), t["true_elasticity"].max()) + 0.15)
    ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.2))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt.number(v, 1)))
    ax.legend(loc="lower right", handletextpad=0.3)
    title = text["elasticity_title"].format(hits=int(hit.sum()), n=len(t))
    place_titles(fig, ax, title, text["elasticity_sub"])
    save(fig, "elasticity-vs-truth.png")
    return {"hits": int(hit.sum()), "n": len(t), "misses": t.loc[~hit, "category"].tolist()}


def chart_index(proposals: pd.DataFrame, text: dict, fmt: Format, rules: engine.Rules) -> dict:
    p = proposals[proposals["offers"] > 0]
    bins = np.arange(0.70, 1.40001, 0.01)
    before = np.histogram(p["index_before"], bins)[0]
    after = np.histogram(p["index_after"], bins)[0]
    within = float((p["index_after"] <= 1 + rules.max_above_market + 1e-9).mean())
    within_before = float((p["index_before"] <= 1 + rules.max_above_market + 1e-9).mean())
    fig, ax = new_figure(3.9, 0.86)
    ax.stairs(before, bins, color=MUTED, linewidth=2, label=text["before"])
    ax.stairs(after, bins, color=BLUE, linewidth=2, label=text["after"])
    top = max(before.max(), after.max())
    for x, label, side in ((1.0, text["median"], "right"), (1 + rules.max_above_market, text["limit"], "left")):
        ax.axvline(x, color=INK_2, linewidth=1, linestyle=(0, (3, 3)))
        shift = -0.004 if side == "right" else 0.004
        ax.text(x + shift, top * 1.02, label, color=INK_2, fontsize=9, va="bottom", ha=side)
    ax.set_ylim(0, top * 1.12)
    ax.set_xlabel(text["index_axis"])
    ax.set_ylabel(text["products_axis"])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt.number(v, 2)))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt.number(v)))
    ax.legend(loc="upper left")
    title = text["index_title"].format(share=fmt.pct(within, 0, sign=False),
                                       before=fmt.pct(within_before, 0, sign=False))
    place_titles(fig, ax, title, text["index_sub"])
    save(fig, "price-index.png")
    return {"within_after": within, "within_before": within_before}


def chart_rules(proposals: pd.DataFrame, text: dict, fmt: Format) -> dict:
    table = pd.crosstab(proposals["binding"], proposals["action"]).reindex(columns=["raise", "lower", "keep"],
                                                                          fill_value=0)
    table = table.loc[table.sum(axis=1).sort_values().index]
    fig, ax = new_figure(3.9, 0.86)
    y = np.arange(len(table))
    left = np.zeros(len(table))
    for action, color in (("raise", BLUE), ("lower", ORANGE), ("keep", KEEP)):
        values = table[action].to_numpy()
        ax.barh(y, values, left=left, color=color, height=0.62, label=text[action], edgecolor="white", linewidth=1.5)
        left += values
    for yi, total in zip(y, left, strict=True):
        ax.text(total + left.max() * 0.01, yi, fmt.number(total), va="center", fontsize=9, color=INK_2)
    ax.set_yticks(y, [text["rule_names"].get(b, b) for b in table.index])
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, left.max() * 1.12)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt.number(v)))
    ax.set_xlabel(text["products_axis"])
    ax.legend(loc="lower right", ncols=3)
    place_titles(fig, ax, text["rules_title"], text["rules_sub"])
    save(fig, "decision-rules.png")
    shares = table.sum(axis=1) / table.values.sum()
    return {"rule_share": shares.to_dict(), "rule_counts": table.sum(axis=1).to_dict()}


def chart_scenarios(frame: pd.DataFrame, true_profit: float, text: dict, fmt: Format) -> None:
    f = frame.set_index("scenario").loc[["bold", "base", "cautious"]]
    fig, ax = new_figure(3.3, 0.80)
    y = np.arange(len(f))
    h = 0.34
    ax.barh(y + h / 2, f["profit_change"], height=h, color=BLUE, label=text["profit"], edgecolor="white", linewidth=1)
    ax.barh(y - h / 2, f["revenue_change"], height=h, color=ORANGE, label=text["revenue"], edgecolor="white",
            linewidth=1)
    base = list(f.index).index("base")
    ax.scatter([true_profit], [base + h / 2], marker="D", s=46, color=INK, zorder=4, label=text["true_profit"],
               edgecolor="white", linewidth=1)
    span = max(f["profit_change"].max(), true_profit) - min(f["revenue_change"].min(), 0)
    for yi, (profit, revenue) in enumerate(zip(f["profit_change"], f["revenue_change"], strict=True)):
        end = max(profit, true_profit) if yi == base else profit
        ax.text(end + span * 0.03, yi + h / 2, fmt.pct(profit), va="center",
                fontsize=9, color=INK_2)
        ax.text(min(revenue, 0) - span * 0.015, yi - h / 2, fmt.pct(revenue), va="center", ha="right", fontsize=9,
                color=INK_2)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_yticks(y, [text["scenarios"][s] for s in f.index])
    ax.grid(axis="y", visible=False)
    lo = min(f["revenue_change"].min(), 0) - span * 0.16
    ax.set_xlim(lo, max(f["profit_change"].max(), true_profit) + span * 0.14)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt.pct(v, 0)))
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=3, fontsize=9, handletextpad=0.4,
              columnspacing=1.4, borderaxespad=0.2)
    b = f.loc["base"]
    place_titles(fig, ax, text["scenario_title"].format(profit=fmt.pct(b["profit_change"]),
                                                        revenue=fmt.pct(b["revenue_change"])), text["scenario_sub"])
    save(fig, "scenarios.png")


def chart_categories(by_category: pd.DataFrame, text: dict, fmt: Format) -> dict:
    t = by_category.sort_values("profit_change").reset_index(drop=True)
    fig, ax = new_figure(4.8, 0.89)
    y = np.arange(len(t))
    colors = np.where(t["profit_change"] >= 0, BLUE, RED)
    ax.barh(y, t["profit_change"], color=colors, height=0.62, edgecolor="white", linewidth=1)
    span = t["profit_change"].max() - min(t["profit_change"].min(), 0)
    for yi, value in zip(y, t["profit_change"], strict=True):
        ax.text(value + (span * 0.012 if value >= 0 else -span * 0.012), yi, fmt.pct(value), va="center",
                ha="left" if value >= 0 else "right", fontsize=9, color=INK_2)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_yticks(y, [label_category(text, c) for c in t["category"]])
    ax.grid(axis="y", visible=False)
    ax.set_xlim(min(t["profit_change"].min(), 0) - span * 0.12, t["profit_change"].max() + span * 0.14)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt.pct(v, 0)))
    ax.set_xlabel(text["change_axis"])
    top = t.iloc[-1]
    place_titles(fig, ax, text["categories_title"].format(top=label_category(text, top["category"]),
                                                          top_value=fmt.pct(top["profit_change"])),
                 text["categories_sub"])
    save(fig, "categories.png")
    return {"top": top["category"], "worst": t.iloc[0]["category"],
            "negative": t.loc[t["profit_change"] < 0, "category"].tolist()}


def replace_blocks(blocks: dict[str, str]) -> None:
    if not README.exists():
        return
    text = README.read_text(encoding="utf-8")
    for name, body in blocks.items():
        pattern = re.compile(rf"(<!-- generated:{name} -->\n).*?(\n<!-- /generated:{name} -->)", re.S)
        if pattern.search(text):
            text = pattern.sub(lambda m, b=body: m.group(1) + b + m.group(2), text)
    README.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", choices=["pl", "en"], default="pl")
    args = parser.parse_args()
    text, fmt = TEXT[args.lang], Format(args.lang)
    style()

    shop = data.load()
    table = elasticity.estimate(shop)
    snap = engine.snapshot(shop, table)
    rules = simulate.SCENARIOS["base"]
    proposals = engine.propose(snap, rules)
    frame = simulate.scenarios(snap)
    truth = simulate.totals(simulate.evaluate(proposals, shop.true_elasticity())).iloc[0]
    spread = simulate.uncertainty(proposals, table)
    by_category = simulate.totals(proposals, "category")

    facts = {"elasticity": chart_elasticity(table, text, fmt)}
    facts["index"] = chart_index(proposals, text, fmt, rules)
    facts["rules"] = chart_rules(proposals, text, fmt)
    chart_scenarios(frame, float(truth["profit_change"]), text, fmt)
    facts["categories"] = chart_categories(by_category, text, fmt)

    try:
        from readme_blocks import blocks  # scripts/ is on sys.path when this file runs
    except ImportError:
        return
    replace_blocks(blocks(args.lang, fmt, shop, table, snap, proposals, frame, truth, spread, by_category, facts))
    print(f"Saved {len(list(IMG.glob('*.png')))} charts to docs/img/ and the README numbers ({args.lang})")


if __name__ == "__main__":
    main()
