"""Tests of the Dash app (ui/): layout, callbacks, table, download and figures, on a tiny generated shop."""
from functools import cache

import pytest
from conftest import write_shop

from pricing_engine import data, elasticity, engine, report
from ui import app as ui_app
from ui import figures
from ui import theme as t

REAL_PREPARE = ui_app.prepare


@pytest.fixture(scope="module")
def shop_app(tmp_path_factory, products):
    """The app with a tiny shop instead of the Data-Generator files (CI has no data)."""
    directory = tmp_path_factory.mktemp("raw")
    write_shop(directory, products)
    shop = data.load(directory)
    table = elasticity.estimate(shop)
    prepared = (shop.truth.get("source", {}), table, engine.snapshot(shop, table), shop.true_elasticity())
    original = ui_app.prepare
    ui_app.prepare = cache(lambda: prepared)
    ui_app.proposals_for.cache_clear()
    yield ui_app, prepared
    ui_app.prepare = original
    ui_app.proposals_for.cache_clear()


def ids(component) -> set[str]:
    """Every component id in a layout tree."""
    found = set()
    stack = [component]
    while stack:
        node = stack.pop()
        if isinstance(node, list | tuple):
            stack.extend(node)
            continue
        if not hasattr(node, "to_plotly_json"):
            continue
        if isinstance(getattr(node, "id", None), str) and node.id:
            found.add(node.id)
        stack.append(getattr(node, "children", None))
    return found


def text_of(component) -> str:
    if isinstance(component, str | int | float):
        return str(component)
    if isinstance(component, list | tuple):
        return " ".join(text_of(c) for c in component)
    return text_of(getattr(component, "children", "") or "")


def test_layout_has_the_rules_the_result_and_the_three_views(shop_app):
    app, _ = shop_app
    found = ids(app.page())
    assert {"margin", "above", "step", "caution", "categories", "stats", "view", "show", "table",
            "view-proposals", "view-categories", "view-elasticity", "download-button"} <= found


def test_headline_numbers_are_the_engine_numbers(shop_app):
    app, (_, _, snap, truth) = shop_app
    stats, charts, *values = app.update_result(15, 5, 10, 0, None)
    expected = report.kpis(engine.propose(snap, engine.Rules()), truth)
    shown = [s.children[0].children for s in stats]
    assert shown == [expected[key] for key, _, _ in app.STATS]
    assert stats[0].children[2].children == f"{expected['profit_delta']} vs today"
    assert values == ["15%", "+5%", "10%", "0.00 SE"]
    assert len(charts) == 2


def test_moving_a_rule_changes_the_numbers(shop_app):
    app, _ = shop_app
    base = app.update_result(15, 5, 10, 0, None)[0][0].children[0].children
    strict = app.update_result(15, 0, 10, 0, None)[0][0].children[0].children
    assert base != strict


def test_categories_filter_limits_the_products(shop_app):
    app, (_, _, snap, _) = shop_app
    category = sorted(snap["category"].unique())[0]
    caption = text_of(app.update_table("all", 15, 5, 10, 0, [category])[1])
    assert f"{(snap['category'] == category).sum():,} products" in caption


def test_table_shows_the_chosen_action_with_the_largest_gain_first(shop_app):
    app, _ = shop_app
    scroll, caption = app.update_table("raise", 15, 5, 10, 0, None)
    table = scroll.children
    header = [th.children for th in table.children[0].children.children]
    assert header == ["Product", "Price", "Proposed", "Profit / year", "Why"]
    rows = table.children[1].children
    assert 0 < len(rows) <= app.TABLE_ROWS
    gains = [float(r.children[3].children.replace(",", "").replace(" zł", "")) for r in rows]
    assert gains == sorted(gains, reverse=True)
    assert all(r.children[4].children.startswith("Raise") for r in rows)
    assert all("pe-up" in r.children[2].className for r in rows)


def test_address_sets_the_rules_within_the_slider_range():
    values = ui_app.start_values("?above=10&step=15&caution=0.3&margin=99")
    assert values == {"margin": 40, "above": 10, "step": 15, "caution": 0.25}
    assert ui_app.start_values("?above=x") == {"margin": 15, "above": 5, "step": 10, "caution": 0}
    assert ui_app.start_values(None) == ui_app.start_values("")


def test_one_view_at_a_time():
    assert ui_app.switch_view("categories") == [{"display": "none"}, {}, {"display": "none"}]
    assert ui_app.switch_view(None)[0] == {}


def test_download_has_every_product(shop_app):
    app, (_, _, snap, _) = shop_app
    sent = app.download(1, 15, 5, 10, 0, None)
    assert sent["filename"] == "proposals.csv"
    assert sent["content"].count("\n") == len(snap) + 1


def test_figures_use_the_portfolio_colours(shop_app):
    _, (_, table, snap, _) = shop_app
    proposals = engine.propose(snap, engine.Rules())
    (title, _), fig = figures.categories(proposals)
    assert "gains the most" in title
    assert set(fig.data[0].marker.color) <= {t.PRIMARY, t.ACCENT}
    (title, _), fig = figures.decision_rules(proposals, engine.Rules())
    assert [bar.marker.color for bar in fig.data[:3]] == [t.PRIMARY, t.ACCENT, t.MIST]
    (title, _), fig = figures.elasticity(table)
    assert title.startswith("The estimate hits the truth in")
    assert fig.layout.font.family.startswith("'Inter'")


def test_missing_data_shows_how_to_get_it(monkeypatch):
    def missing():
        raise FileNotFoundError("Run python scripts/get_data.py first.")

    monkeypatch.setattr(ui_app, "prepare", missing)
    page = ui_app.page()
    assert "get_data.py" in text_of(page.children)
    assert "stats" not in ids(page)


@pytest.mark.skipif(not (data.RAW_DIR / "product_data.parquet").exists(),
                    reason="needs the shop data from scripts/get_data.py")
def test_headline_numbers_on_data_generator_1_7_1(monkeypatch):
    """
    The app's numbers for the default rules and for ?above=10&step=15 on Data-Generator v1.7.1 (net prices without
    23% VAT). On v1.6.0 they were 8.09M, 21.11M, 67,828, 20.5k, +3.0% and 8.40M, 20.82M, 65,841, 26.5k, +7.2%.
    """
    monkeypatch.setattr(ui_app, "prepare", REAL_PREPARE)
    ui_app.proposals_for.cache_clear()
    for rules, expected in (
        ((15, 5, 10, 0), ["8.33M", "21.34M", "67,701", "20.8k", "+3.1%"]),
        ((15, 10, 15, 0), ["8.66M", "21.05M", "65,746", "26.7k", "+7.2%"]),
    ):
        stats = ui_app.update_result(*rules, None)[0]
        assert [s.children[0].children for s in stats] == expected
