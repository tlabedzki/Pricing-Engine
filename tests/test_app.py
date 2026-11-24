import pytest

from pricing_engine import data

pytestmark = pytest.mark.skipif(not (data.RAW_DIR / "product_data.parquet").exists(),
                                reason="needs the shop data from scripts/get_data.py")


def test_app_runs_and_reacts_to_the_rules():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(data.ROOT / "app" / "streamlit_app.py"), default_timeout=180).run()
    assert not app.exception
    profit = app.metric[0].value
    app.sidebar.slider[1].set_value(0).run()  # no price above the competitor median
    assert not app.exception
    assert app.metric[0].value != profit
