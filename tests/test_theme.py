"""The portfolio look: the Streamlit theme matches src/pricing_engine/theme.py and Inter is served from the repo."""
import sys
import tomllib

import pytest

from pricing_engine import data, theme

CONFIG = tomllib.loads((data.ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
FONTS = data.ROOT / "app" / "static" / "fonts"


def test_theme_colours_match_the_shared_tokens():
    t = CONFIG["theme"]
    assert t["primaryColor"] == theme.PRIMARY == "#006e79"
    assert t["textColor"] == theme.INK
    assert t["backgroundColor"] == theme.PAGE
    assert t["secondaryBackgroundColor"] == theme.WASH
    assert t["borderColor"] == theme.LINE
    assert t["chartCategoricalColors"][:3] == [theme.PRIMARY, theme.ACCENT, theme.MIST]


def test_inter_comes_from_files_in_the_repo_and_no_font_service():
    t = CONFIG["theme"]
    assert CONFIG["server"]["enableStaticServing"] is True
    assert t["font"].startswith("Inter") and t["headingFont"].startswith("Inter")
    faces = t["fontFaces"]
    assert {face["family"] for face in faces} == {"Inter"}
    for face in faces:
        assert face["url"].startswith("app/static/fonts/")
        assert (data.ROOT / face["url"]).is_file()
    assert faces[-1]["unicodeRange"] == "U+0030-0039"  # the tabular digits face wins for 0-9
    assert (FONTS / "OFL-inter.txt").is_file()
    text = (data.ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "googleapis" not in text and "gstatic" not in text


def test_digits_face_has_tabular_digits_at_every_weight():
    pytest.importorskip("brotli")
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = TTFont(FONTS / "inter-digits-tnum-wght-normal.woff2")
    cmap = font.getBestCmap()
    assert sorted(cmap) == list(range(0x30, 0x3A))
    assert "fvar" in font  # still variable: the same digits at 400, 500 and 700
    for weight in (400, 700):
        static = instancer.instantiateVariableFont(TTFont(FONTS / "inter-digits-tnum-wght-normal.woff2"),
                                                   {"wght": weight})
        widths = {static["hmtx"][cmap[code]][0] for code in range(0x30, 0x3A)}
        assert len(widths) == 1


def test_digits_face_matches_its_build_script():
    pytest.importorskip("brotli")
    import io

    from fontTools.ttLib import TTFont

    sys.path.insert(0, str(data.ROOT / "scripts"))
    import inter_font

    built = TTFont(io.BytesIO(inter_font.build_digits()))
    stored = TTFont(FONTS / "inter-digits-tnum-wght-normal.woff2")
    assert built.getBestCmap() == stored.getBestCmap()
    assert built["hmtx"].metrics == stored["hmtx"].metrics
