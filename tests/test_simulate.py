import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import write_shop

from pricing_engine import data, elasticity, engine, simulate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def shop_dir(tmp_path_factory, products):
    directory = tmp_path_factory.mktemp("shop")
    write_shop(directory, products)
    return directory


@pytest.fixture(scope="module")
def setup(shop_dir):
    shop = data.load(shop_dir)
    table = elasticity.estimate(shop)
    snap = engine.snapshot(shop, table)
    return shop, table, snap


def test_totals_add_up(setup):
    _, _, snap = setup
    proposals = engine.propose(snap)
    total = simulate.totals(proposals).iloc[0]
    assert total["profit_after"] == pytest.approx(proposals["profit_after"].sum())
    assert total["profit_change"] == pytest.approx(total["profit_after"] / total["profit_before"] - 1)
    assert total["products"] == len(proposals) == total["raise"] + total["lower"] + total["keep"]
    by_category = simulate.totals(proposals, "category")
    assert by_category["revenue_after"].sum() == pytest.approx(total["revenue_after"])
    assert "category" in by_category.columns


def test_evaluate_with_the_same_elasticity_changes_nothing(setup):
    _, _, snap = setup
    proposals = engine.propose(snap)
    same = proposals.groupby("category")["elasticity"].first()
    again = simulate.evaluate(proposals, same)
    for column in ("units_after", "revenue_after", "profit_after"):
        assert np.allclose(again[column], proposals[column])


def test_evaluate_with_more_sensitive_demand_sells_less_after_raises(setup):
    _, _, snap = setup
    proposals = engine.propose(snap)
    raised = proposals[proposals["action"] == "raise"]
    sensitive = simulate.evaluate(raised, raised.groupby("category")["elasticity"].first() + 1)
    assert (sensitive["units_after"] < raised["units_after"]).all()


def test_scenarios_follow_their_rules(setup):
    _, _, snap = setup
    frame = simulate.scenarios(snap).set_index("scenario")
    assert list(frame.index) == ["cautious", "base", "bold"]
    assert frame.loc["cautious", "max_step"] < frame.loc["bold", "max_step"]
    assert (frame["products"] == len(snap)).all()


def test_uncertainty_without_spread_is_a_point(setup):
    _, table, snap = setup
    proposals = engine.propose(snap)
    fixed = table.assign(elasticity_se=1e-12)
    spread = simulate.uncertainty(proposals, fixed, draws=50)
    expected = simulate.totals(proposals).iloc[0]["profit_change"]
    assert np.allclose(spread["profit_change"], expected)
    assert len(simulate.uncertainty(proposals, table, draws=50)["profit_change"].unique()) > 1


def test_command_line_writes_every_result(shop_dir, tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--data", str(shop_dir), "--output", str(tmp_path)],
                            capture_output=True, text=True, env={**os.environ, "MPLBACKEND": "Agg"})
    assert result.returncode == 0, result.stderr
    for name in ("elasticity.csv", "proposals.csv", "categories.csv", "scenarios.csv", "summary.json"):
        assert (tmp_path / name).exists()
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert set(summary["scenarios"]) == {"cautious", "base", "bold"}
    proposals = pd.read_csv(tmp_path / "proposals.csv")
    assert proposals["reason"].notna().all()
    assert "Scenarios" in result.stdout


def test_command_line_without_data_says_what_to_run(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--data", str(tmp_path), "--output", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "get_data.py" in result.stderr
