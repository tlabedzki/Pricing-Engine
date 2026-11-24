"""
Inter, the portfolio typeface, from the files in app/static/fonts/ (SIL Open Font License, OFL-inter.txt there).

    python scripts/inter_font.py    # rebuild app/static/fonts/inter-digits-tnum-wght-normal.woff2

The app gets Inter from those files through [[theme.fontFaces]] in .streamlit/config.toml, no font service. The
proposals table and the charts draw on a canvas, where CSS font-feature-settings do not reach, so the digits come
from a small extra face: Inter's tabular digits (zero.tf ... nine.tf) mapped to 0-9, served for U+0030-0039 only.
Every digit in the app is then tabular, also on the canvas. The README charts (matplotlib) and the animated demo use
static instances of the same files with the same tabular digits. Needs fontTools and brotli (requirements-dev.txt).
"""
from __future__ import annotations

import io
from functools import cache
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "app" / "static" / "fonts"
LATIN = FONTS / "inter-latin-wght-normal.woff2"
LATIN_EXT = FONTS / "inter-latin-ext-wght-normal.woff2"
DIGITS = FONTS / "inter-digits-tnum-wght-normal.woff2"
CACHE = ROOT / ".cache" / "fonts"
DIGIT_NAMES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def tabular_digits(font: TTFont) -> TTFont:
    """Map the characters 0-9 to Inter's tabular digit glyphs (the 'tnum' forms), in place."""
    for table in font["cmap"].tables:
        if table.isUnicode():
            for i, name in enumerate(DIGIT_NAMES):
                if 0x30 + i in table.cmap:
                    table.cmap[0x30 + i] = f"{name}.tf"
    return font


def save_woff2(font: TTFont) -> bytes:
    font.flavor = "woff2"
    font.recalcTimestamp = False  # two runs give the same bytes
    buffer = io.BytesIO()
    font.save(buffer)
    return buffer.getvalue()


def subset_font(font: TTFont, text: str) -> TTFont:
    options = subset.Options()
    options.layout_features = ["kern"]
    options.name_IDs = ["*"]
    sub = subset.Subsetter(options)
    sub.populate(text=text)
    sub.subset(font)
    return font


def build_digits() -> bytes:
    """The variable digit face (weights 100-900) for U+0030-0039."""
    return save_woff2(subset_font(tabular_digits(TTFont(LATIN)), "0123456789"))


@cache
def static_instance(weight: int, ext: bool = False) -> Path:
    """A static TTF of Inter at one weight, with tabular digits, cached in .cache/fonts/ for matplotlib.

    The Latin Extended file (Polish letters) is renamed to the family "Inter Ext" so matplotlib can use it as the
    fallback of "Inter" for the characters the Latin file does not have.
    """
    path = CACHE / f"inter{'-ext' if ext else ''}-{weight}.ttf"
    if not path.exists():
        font = instancer.instantiateVariableFont(TTFont(LATIN_EXT if ext else LATIN), {"wght": weight})
        tabular_digits(font)
        if ext:
            for record in font["name"].names:
                if record.nameID in (1, 4, 16, 3, 6):
                    text = record.toUnicode().replace("Inter", "Inter Ext", 1)
                    record.string = text.replace(" ", "") if record.nameID == 6 else text
        font.flavor = None
        font.recalcTimestamp = False
        CACHE.mkdir(parents=True, exist_ok=True)
        font.save(path)
    return path


def embedded_face(family: str, weight: int, text: str) -> tuple[str, TTFont]:
    """An @font-face rule with a base64 woff2 subset of Inter at one weight (tabular digits), and the font itself."""
    import base64

    font = instancer.instantiateVariableFont(TTFont(LATIN), {"wght": weight})
    subset_font(tabular_digits(font), text)
    data = base64.b64encode(save_woff2(font)).decode()
    return f"@font-face{{font-family:{family};src:url(data:font/woff2;base64,{data}) format('woff2')}}", font


if __name__ == "__main__":
    DIGITS.write_bytes(build_digits())
    print(f"Saved {DIGITS.relative_to(ROOT)} ({DIGITS.stat().st_size / 1024:.1f} KB)")
