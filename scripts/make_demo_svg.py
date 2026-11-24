"""
Build docs/img/app-demo.svg and app-demo-dark.svg, the animated demo at the top of the README.

    python scripts/make_demo_svg.py [--shots DIR] [--reuse] [--quality 72]

The demo is an illustration, not a recording. The script starts the Dash app on 127.0.0.1 and takes screenshots of
its Rules and Result sections in three sets of rules: the base rules, the competitor limit moved to +10% and then the
largest step to 15% (headless Chrome or Edge through the DevTools protocol). The moving parts are vectors: the
cursor, the two sliders it drags with their values, and the five headline numbers. Those numbers come from the
pricing engine in this script (`pricing_engine.report.kpis`), the same code the app and the README use, and the
script stops if the app shows other numbers. The part of the page under the numbers changes with a cross-fade.

Only CSS animations inside the SVG, no script: GitHub shows README images through <img>. With prefers-reduced-motion
the image shows the base rules without motion. The two files differ only in the browser frame (light and dark GitHub
theme). --shots keeps the screenshots and their geometry in DIR; --reuse builds from them without starting the app.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import inter_font  # noqa: E402  (scripts/ is on sys.path when this file runs)

from pricing_engine import data, elasticity, engine, report  # noqa: E402
from pricing_engine import theme as look  # noqa: E402
from ui.app import STATS, rule_text  # noqa: E402

OUT_DIR = ROOT / "docs" / "img"
DEBUG_PORT, APP_PORT = 9335, 8597
VW, VH = 1200, 740  # browser viewport in CSS px
SCALE = 1.25  # screenshot pixels per CSS px
W = 1000  # SVG width; the viewport is scaled by W / VW
BAR = 36  # browser bar above the page
LIMIT = 500 * 1024  # bytes per SVG
EASE = "cubic-bezier(.65,0,.35,1)"
EASE_OUT = "cubic-bezier(.22,1,.36,1)"
PRIMARY = look.PRIMARY
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]
FRAMES = {  # browser frame in GitHub's light and dark theme; the app keeps its own light page
    "light": {"bar": "#f6f8fa", "border": "#d0d7de", "dot": "#d0d7de", "pill": "#ffffff", "pill_text": "#57606a"},
    "dark": {"bar": "#161b22", "border": "#30363d", "dot": "#484f58", "pill": "#0d1117", "pill_text": "#8b949e"},
}
# The story: base rules, then the competitor limit dragged from +5% to +10%, then the largest step from 10% to 15%.
STATES = {
    "base": {"above": 5, "step": 10},
    "above": {"above": 10, "step": 10},
    "bold": {"above": 10, "step": 15},
}
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def find_browser() -> str:
    for candidate in filter(None, [os.environ.get("CHROME"), *BROWSERS]):
        path = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if path:
            return path
    sys.exit("Chrome, Chromium or Edge not found. Set CHROME to the browser executable.")


def wait_for(url: str, seconds: float = 120) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"{url} did not answer in {seconds:.0f} s")


# ---- 1. screenshots ----------------------------------------------------------------------------------------------

GEOMETRY_JS = """(() => {
  const box = e => { const r = e.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; };
  const text = e => { const r = document.createRange(); r.selectNodeContents(e); return box(r); };
  const style = e => { const s = getComputedStyle(e);
    return {color: s.color, background: s.backgroundColor, size: parseFloat(s.fontSize), weight: s.fontWeight,
            spacing: parseFloat(s.letterSpacing) || 0, border: s.borderTopColor,
            border_width: parseFloat(s.borderTopWidth) || 0}; };
  const rules = {};
  document.querySelectorAll('.pe-rule').forEach(el => {
    const thumb = el.querySelector('.mantine-Slider-thumb');
    const value = el.querySelector('.pe-rule-value');
    rules[value.id.replace('-value', '')] = {
      thumb: box(thumb), thumb_style: style(thumb), track: box(el.querySelector('.mantine-Slider-track')),
      bar: box(el.querySelector('.mantine-Slider-bar')), value: text(value), value_text: value.textContent,
      value_style: style(value), min: +thumb.getAttribute('aria-valuemin'), max: +thumb.getAttribute('aria-valuemax'),
      now: +thumb.getAttribute('aria-valuenow')};
  });
  const stats = [...document.querySelectorAll('.dg-stat')].map(el => {
    const value = el.querySelector('.dg-stat-value'), note = el.querySelector('.dg-stat-note');
    return {value: text(value), value_text: value.textContent, value_style: style(value),
            note: text(note), note_text: note.textContent, note_style: style(note)};
  });
  return JSON.stringify({rules, stats, view: box(document.getElementById('view'))});
})()"""

READY_JS = ("[...document.querySelectorAll('.dg-stat-value')].filter(e => e.textContent).length === 5 && "
            "document.querySelectorAll('.pe-table tbody tr').length > 0 && "
            "document.getElementById('above-value').textContent === {above!r} && "
            "document.getElementById('step-value').textContent === {step!r}")
SCROLL_JS = ("window.scrollTo(0, document.getElementById('rules').getBoundingClientRect().top + window.scrollY - 28); "
             "document.activeElement && document.activeElement.blur()")


async def capture(browser: str, shots: Path) -> None:
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", f"--remote-debugging-port={DEBUG_PORT}",
                               f"--user-data-dir={profile}", "--hide-scrollbars", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
    geometry = {"viewport": [VW, VH], "scale": SCALE, "states": {}}
    try:
        wait_for(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        page = next(t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
                    if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=500 * 1024 * 1024) as ws:
            counter = 0

            async def send(method: str, **params):
                nonlocal counter
                counter += 1
                await ws.send(json.dumps({"id": counter, "method": method, "params": params}))
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("id") == counter:
                        if "error" in message:
                            raise RuntimeError(f"{method}: {message['error']}")
                        return message.get("result", {})

            async def js(expression: str):
                result = await send("Runtime.evaluate", expression=expression, returnByValue=True)
                if "exceptionDetails" in result:
                    raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description"))
                return result.get("result", {}).get("value")

            await send("Emulation.setDeviceMetricsOverride", width=VW, height=VH, deviceScaleFactor=SCALE,
                       mobile=False)
            for name, rules in STATES.items():
                await send("Page.navigate", url=f"http://127.0.0.1:{APP_PORT}/?above={rules['above']}"
                                                f"&step={rules['step']}")
                await asyncio.sleep(2)
                ready = READY_JS.format(above=rule_text("above", rules["above"]),
                                        step=rule_text("step", rules["step"]))
                for _ in range(240):
                    if await js(ready):
                        break
                    await asyncio.sleep(0.5)
                else:
                    raise SystemExit(f"The app did not show its numbers for {name} in 120 s")
                await js("document.fonts.ready.then(() => true)")
                await js(SCROLL_JS)
                await asyncio.sleep(1.5)
                shot = await send("Page.captureScreenshot", format="png", captureBeyondViewport=False)
                (shots / f"{name}.png").write_bytes(base64.b64decode(shot["data"]))
                geometry["states"][name] = json.loads(await js(GEOMETRY_JS))
    finally:
        chrome.terminate()
        shutil.rmtree(profile, ignore_errors=True)
    (shots / "geometry.json").write_text(json.dumps(geometry, indent=1), encoding="utf-8")


def take_screenshots(shots: Path) -> None:
    browser = find_browser()
    env = {**os.environ, "MPLBACKEND": "Agg", "PE_PORT": str(APP_PORT)}
    app = subprocess.Popen([sys.executable, "-m", "ui.app"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
    try:
        wait_for(f"http://127.0.0.1:{APP_PORT}/")
        asyncio.run(capture(browser, shots))
    finally:
        if os.name == "nt":  # the venv python is a launcher: stop its child too
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
        else:
            app.terminate()
        app.wait(timeout=20)


def numbers() -> dict[str, dict]:
    """The headline numbers of each state from the engine, formatted like the app."""
    shop = data.load()
    table = elasticity.estimate(shop)
    snap = engine.snapshot(shop, table)
    truth = shop.true_elasticity()
    out = {}
    for name, rules in STATES.items():
        proposals = engine.propose(snap, engine.Rules(max_above_market=rules["above"] / 100,
                                                      max_step=rules["step"] / 100))
        out[name] = report.kpis(proposals, truth)
    return out


# ---- 2. animation ------------------------------------------------------------------------------------------------

class Motion:
    """CSS keyframes on one timeline. Each track: (seconds, value, easing to the next stop)."""

    def __init__(self, total: float):
        self.total = total
        self.css: list[str] = []
        self.count = 0

    def track(self, prop: str, stops: list, rest) -> str:
        """A class animating prop through stops; rest is the value without motion (prefers-reduced-motion)."""
        self.count += 1
        name = f"m{self.count}"
        stops = sorted(stops, key=lambda s: s[0])
        if stops[0][0] > 0:
            stops.insert(0, (0, stops[0][1], "linear"))
        if stops[-1][0] < self.total:
            stops.append((self.total, stops[-1][1], "linear"))
        frames = "".join(f"{s / self.total * 100:.3f}%{{{prop}:{value};animation-timing-function:{ease}}}"
                         for s, value, ease in stops)
        self.css.append(f"@keyframes {name}{{{frames}}}.{name}{{{prop}:{rest};"
                        f"animation:{name} {self.total:g}s linear 0s infinite both}}")
        return name


def tr(x: float, y: float) -> str:
    return f"translate({x:.1f}px,{y:.1f}px)"


def ease_io(u: float) -> float:
    return 4 * u**3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def path_value(stops: list[tuple[float, float]], t: float) -> float:
    """Value at time t of a path through (time, value) stops, eased between them and held outside."""
    if t <= stops[0][0]:
        return stops[0][1]
    for (t0, v0), (t1, v1) in zip(stops, stops[1:], strict=False):
        if t <= t1:
            return v0 + (v1 - v0) * ease_io((t - t0) / (t1 - t0)) if t1 > t0 else v1
    return stops[-1][1]


def font_faces(text: str, weights: set[int]):
    """Inter (the app's font, ui/assets/fonts) at each weight the vector texts use, only the characters in text,
    with tabular digits like the app. Returns the @font-face rules and one of the fonts (same line metrics)."""
    rules, font = [], None
    for weight in sorted(weights):
        family = f"PeInter{weight}"
        rule, font = inter_font.embedded_face(family, weight, text)
        rules.append(rule + f".w{weight}{{font-family:{family},Inter,'Segoe UI',sans-serif}}")
    return "".join(rules), font


def weight_of(style: dict) -> int:
    return int(float(style["weight"]))


def spacing(style: dict, k: float) -> str:
    return f' letter-spacing="{style.get("spacing", 0) * k:.2f}"' if style.get("spacing") else ""


def webp(image: Image.Image, quality: int) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "WEBP", quality=quality, method=6)
    return base64.b64encode(buffer.getvalue()).decode()


def hex_color(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def css_color(value: str) -> str:
    """rgb(1, 2, 3) to #010203."""
    return hex_color([int(float(p)) for p in value[value.index("(") + 1:value.index(")")].split(",")[:3]])


CURSOR = "M0 0V17.2L4.3 13.3L7.2 20.1L10.3 18.8L7.5 12.2H13.2Z"  # arrow, tip at 0,0


def check_numbers(geo: dict, values: dict) -> None:
    """Stop when the app showed other headline numbers or rule values than the engine gives here."""
    for name, state in geo["states"].items():
        shown = [(s["value_text"], s["note_text"]) for s in state["stats"]]
        expected = [(values[name][key], note.format(**values[name])) for key, _, note in STATS]
        if shown != expected:
            sys.exit(f"The app shows {shown} for {name}, the engine gives {expected}: retake the screenshots.")
        for rule in ("above", "step"):
            if state["rules"][rule]["value_text"] != rule_text(rule, STATES[name][rule]):
                sys.exit(f"The app shows {rule} = {state['rules'][rule]['value_text']} for {name}.")


def opacity_windows(m: Motion, windows: list[tuple[float, float]], rest: int, fade: float = 0.25) -> str:
    """Opacity 1 inside each (start, end) window and 0 outside, with short fades; a window may start at 0."""
    stops = [(0, 1 if windows[0][0] <= 0 else 0, "linear")]
    for start, end in windows:
        if start > 0:
            stops += [(start, 0, EASE), (start + fade, 1, "linear")]
        if end < m.total:
            stops += [(end, 1, EASE), (end + fade, 0, "linear")]
    return m.track("opacity", stops, rest)


def build(shots: Path, quality: int) -> tuple[dict[str, str], float, dict]:
    geo = json.loads((shots / "geometry.json").read_text(encoding="utf-8"))
    if geo["viewport"] != [VW, VH] or geo["scale"] != SCALE:
        sys.exit("The screenshots were taken with another viewport or scale: run without --reuse.")
    values = numbers()
    check_numbers(geo, values)
    k = W / VW
    vh = VH * k
    H = BAR + vh
    base = geo["states"]["base"]
    shot = {name: Image.open(shots / f"{name}.png").convert("RGB") for name in STATES}
    px = shot["base"].width / VW  # screenshot pixels per CSS px

    def pixel(x: float, y: float) -> str:
        return hex_color(shot["base"].getpixel((int(x * px), int(y * px))))

    # Timeline (seconds): hold the base rules, drag the competitor limit, hold, drag the largest step, hold, reset.
    t_move1, t_press1, t_release1 = 1.9, 2.7, 3.9
    t_move2, t_press2, t_release2 = 5.7, 6.5, 7.5
    t_away, t_reset, t_reset_end = 10.4, 10.9, 11.8
    lag = 0.3  # the app recalculates after the release
    T = 13.2
    m = Motion(T)
    show = {
        "base": opacity_windows(m, [(0, t_release1 + lag), (t_reset_end + lag, T)], 1),
        "above": opacity_windows(m, [(t_release1 + lag, t_release2 + lag)], 0),
        "bold": opacity_windows(m, [(t_release2 + lag, t_reset_end + lag)], 0),
    }

    # Inter for every vector text, at the weights the app uses, with its line metrics for the baselines
    texts = "".join(s["value_text"] + s["note_text"] for state in geo["states"].values() for s in state["stats"])
    texts += "".join(v for s in STATES for v in values[s].values() if isinstance(v, str)) + "+-%.0123456789 SE"
    styles = [style for state in geo["states"].values() for s in state["stats"]
              for style in (s["value_style"], s["note_style"])]
    styles += [r["value_style"] for r in base["rules"].values()]
    face, font = font_faces(texts, {weight_of(style) for style in styles})
    upm = font["head"].unitsPerEm
    ascent, descent = font["hhea"].ascent / upm, -font["hhea"].descent / upm

    def baseline(b: dict, size: float) -> float:
        """Baseline of one line of text centred in its box b."""
        return (b["y"] + (b["h"] - (ascent + descent) * size) / 2 + ascent * size) * k

    # 1. the page: the base screenshot, the part under the numbers of the other states cross-faded on top
    layers = [f'<image width="{W}" height="{vh:.2f}" href="data:image/webp;base64,{webp(shot["base"], quality)}"/>']
    view_y = max(base["view"]["y"] - 8, 0)
    if view_y < VH:
        for name in ("above", "bold"):
            crop = shot[name].crop((0, int(view_y * px), shot[name].width, shot[name].height))
            layers.append(f'<g class="{show[name]}"><image x="0" y="{view_y * k:.2f}" width="{W}" '
                          f'height="{(VH - view_y) * k:.2f}" href="data:image/webp;base64,{webp(crop, quality)}"/></g>')

    # 2. the headline numbers: a patch over each value and note, then the numbers of each state
    for i in range(len(STATS)):
        parts = [geo["states"][s]["stats"][i] for s in STATES]
        x0 = min(min(p["value"]["x"], p["note"]["x"]) for p in parts) - 2
        x1 = max(max(p["value"]["x"] + p["value"]["w"], p["note"]["x"] + p["note"]["w"]) for p in parts) + 2
        for part in ("value", "note"):
            y0 = min(p[part]["y"] for p in parts) - 1
            y1 = max(p[part]["y"] + p[part]["h"] for p in parts) + 1
            layers.append(f'<rect x="{x0 * k:.2f}" y="{y0 * k:.2f}" width="{(x1 - x0) * k:.2f}" '
                          f'height="{(y1 - y0) * k:.2f}" fill="{pixel(x0 - 1, y0 + 1)}"/>')
    for name in STATES:
        parts = []
        for stat in geo["states"][name]["stats"]:
            for part in ("value", "note"):
                b, st = stat[part], stat[f"{part}_style"]
                parts.append(f'<text class="w{weight_of(st)}" x="{b["x"] * k:.2f}" y="{baseline(b, st["size"]):.2f}"'
                             f'{spacing(st, k)} font-size="{st["size"] * k:.2f}" fill="{css_color(st["color"])}">'
                             f'{stat[f"{part}_text"]}</text>')
        layers.append(f'<g class="{show[name]}">{"".join(parts)}</g>')

    # 3. the two sliders the cursor drags: a patch over track and value, then track, bar, thumb and value as vectors
    paths = {
        "above": [(0, 5), (t_press1, 5), (t_release1, 10), (t_reset, 10), (t_reset_end, 5)],
        "step": [(0, 10), (t_press2, 10), (t_release2, 15), (t_reset, 15), (t_reset_end, 10)],
    }
    times = [round(i / 50, 2) for i in range(int(T * 50) + 1)]
    thumbs = {}
    for rule, stops in paths.items():
        s = base["rules"][rule]
        tx, tw = s["track"]["x"], s["track"]["w"]
        cy = s["thumb"]["y"] + s["thumb"]["h"] / 2
        radius = s["thumb"]["w"] / 2
        page_bg = pixel(tx - radius - 8, cy)
        # the empty track: colour and thickness from the screenshot, right of the thumb
        right = tx + tw - 3
        rows = [d / px for d in range(int(-6 * px), int(6 * px) + 1)
                if hex_color(shot["base"].getpixel((int(right * px), int(cy * px) + d))) != page_bg]
        line_h = (max(rows) - min(rows) + 1 / px) if rows else 4.0
        line_y = cy + (max(rows) + min(rows)) / 2 if rows else cy
        empty = pixel(right, line_y)
        bar_x = min(s["bar"]["x"], tx)

        def x_of(v: float, s=s, tx=tx, tw=tw) -> float:
            return tx + (v - s["min"]) / (s["max"] - s["min"]) * tw

        y0, y1 = s["thumb"]["y"] - 3, s["thumb"]["y"] + s["thumb"]["h"] + 3
        left = bar_x - radius - 6
        layers.append(f'<rect x="{left * k:.2f}" y="{y0 * k:.2f}" width="{(tx + tw + radius + 6 - left) * k:.2f}" '
                      f'height="{(y1 - y0) * k:.2f}" fill="{page_bg}"/>')
        bar = (f'y="{(line_y - line_h / 2) * k:.2f}" height="{line_h * k:.2f}" rx="{line_h * k / 2:.2f}"')
        full = tx + tw - bar_x
        layers.append(f'<rect x="{bar_x * k:.2f}" width="{full * k:.2f}" {bar} fill="{empty}"/>')
        rest_x = x_of(stops[0][1])
        moving = [t for t in times if stops[1][0] <= t <= stops[2][0] or stops[3][0] <= t <= stops[4][0]]
        key_times = sorted({0.0, T, *[t for t, _ in stops], *moving})
        fill = m.track("transform", [(t, f"scaleX({(x_of(path_value(stops, t)) - bar_x) / full:.4f})", "linear")
                                     for t in key_times], f"scaleX({(rest_x - bar_x) / full:.4f})")
        layers.append(f'<g transform="translate({bar_x * k:.2f} 0)"><rect class="{fill}" width="{full * k:.2f}" '
                      f'{bar} fill="{PRIMARY}"/></g>')
        move = m.track("transform", [(t, tr((x_of(path_value(stops, t)) - rest_x) * k, 0), "linear")
                                     for t in key_times], tr(0, 0))
        ts = s["thumb_style"]
        ring = ts["border_width"]
        layers.append(f'<g class="{move}"><circle cx="{rest_x * k:.2f}" cy="{cy * k:.2f}" '
                      f'r="{(radius - ring / 2) * k:.2f}" fill="{css_color(ts["background"])}" '
                      f'stroke="{css_color(ts["border"])}" stroke-width="{ring * k:.2f}"/></g>')
        # the value next to the label: one text per whole value, shown while the dragged value rounds to it
        vb, vs = s["value"], s["value_style"]
        values_range = range(min(v for _, v in stops), max(v for _, v in stops) + 1)
        widest = max(geo["states"][n]["rules"][rule]["value"]["w"] for n in STATES)
        vx1 = vb["x"] + vb["w"]
        layers.append(f'<rect x="{(vx1 - widest - 6) * k:.2f}" y="{(vb["y"] - 1) * k:.2f}" '
                      f'width="{(widest + 8) * k:.2f}" height="{(vb["h"] + 2) * k:.2f}" '
                      f'fill="{pixel(vx1 - widest - 8, vb["y"] + 1)}"/>')
        labels = []
        for value in values_range:
            on = [math.floor(path_value(stops, t) + 0.5) == value for t in times]  # exactly one value shown
            track_stops = [(0, int(on[0]), "linear")]
            for i in range(1, len(times)):
                if on[i] != on[i - 1]:
                    track_stops += [(times[i] - 0.001, int(on[i - 1]), "linear"), (times[i], int(on[i]), "linear")]
            cls = m.track("opacity", track_stops, int(value == stops[0][1]))
            labels.append(f'<text class="{cls}" x="{vx1 * k:.2f}" y="{baseline(vb, vs["size"]):.2f}" '
                          f'text-anchor="end">{rule_text(rule, value)}</text>')
        layers.append(f'<g class="w{weight_of(vs)}" font-size="{vs["size"] * k:.2f}" '
                      f'fill="{css_color(vs["color"])}">{"".join(labels)}</g>')
        thumbs[rule] = lambda v, x_of=x_of, cy=cy: (x_of(v) * k, cy * k)

    # 4. the cursor: rest, the first thumb, drag, the second thumb, drag, away
    rest = (W * 0.42, vh * 0.62)
    grab1, grab2 = thumbs["above"](5), thumbs["step"](10)
    cursor_path = [(0, rest, "linear"), (t_move1, rest, EASE), (t_press1 - 0.15, grab1, "linear")]
    cursor_path += [(t, thumbs["above"](path_value(paths["above"], t)), "linear")
                    for t in times if t_press1 <= t <= t_release1]
    cursor_path += [(t_move2, thumbs["above"](10), EASE), (t_press2 - 0.15, grab2, "linear")]
    cursor_path += [(t, thumbs["step"](path_value(paths["step"], t)), "linear")
                    for t in times if t_press2 <= t <= t_release2]
    cursor_path += [(t_away, thumbs["step"](15), EASE), (t_away + 1.2, rest, "linear")]
    cursor_move = m.track("transform", [(t, tr(*xy), e) for t, xy, e in cursor_path], tr(*rest))
    cursor_show = m.track("opacity", [(0, 1, "linear")], 0)
    press = [(0, "scale(1)", "linear")]
    for down, up in ((t_press1, t_release1), (t_press2, t_release2)):
        press += [(down - 0.08, "scale(1)", EASE_OUT), (down, "scale(.88)", "linear"), (up, "scale(.88)", EASE_OUT),
                  (up + 0.18, "scale(1)", "linear")]
    cursor_press = m.track("transform", press, "scale(1)")
    for t0, (x, y) in ((t_press1, grab1), (t_press2, grab2)):
        ring = m.track("transform", [(t0, "scale(.2)", EASE_OUT), (t0 + 0.5, "scale(1)", "linear"),
                                     (t0 + 0.51, "scale(.2)", "linear")], "scale(1)")
        fade = m.track("opacity", [(t0 - 0.01, 0, "linear"), (t0, 0.45, EASE_OUT), (t0 + 0.5, 0, "linear")], 0)
        layers.append(f'<g transform="translate({x:.1f} {y:.1f})"><g class="{fade}"><circle class="{ring}" r="18" '
                      f'fill="{PRIMARY}" fill-opacity="0.35"/></g></g>')
    layers.append(f'<g class="{cursor_show}"><g class="{cursor_move}"><g class="{cursor_press}">'
                  f'<path d="{CURSOR}" transform="scale(1.15)" fill="{look.INK}" stroke="#ffffff" stroke-width="1.3" '
                  f'stroke-linejoin="round" filter="url(#shadow)"/></g></g></g>')

    first, last = values["base"], values["bold"]
    alt = (f"Pricing Engine app, illustrated: the competitor limit is dragged from +5% to +10% and the largest price "
           f"step from 10% to 15%; yearly gross profit moves from {first['profit']} PLN ({first['profit_delta']}) "
           f"to {last['profit']} PLN ({last['profit_delta']}).")
    css = (face + "".join(m.css) + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    page = "".join(layers)
    out = {}
    for theme, c in FRAMES.items():
        dots = "".join(f'<circle cx="{18 + i * 16}" cy="{BAR / 2}" r="5" fill="{c["dot"]}"/>' for i in range(3))
        host, pill_w = "127.0.0.1:8050", 150
        out[theme] = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H:.0f}" width="{W}" height="{H:.0f}" '
            f'role="img" aria-label="{alt}"><title>{alt}</title><defs><style>{css}</style>'
            f'<clipPath id="frame"><rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1:.1f}" rx="10"/></clipPath>'
            f'<clipPath id="view"><rect x="0" y="{BAR}" width="{W}" height="{vh:.1f}"/></clipPath>'
            f'<filter id="shadow" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="1.2" '
            f'stdDeviation="1.4" flood-color="#000" flood-opacity="0.35"/></filter></defs>'
            f'<g clip-path="url(#frame)"><rect width="{W}" height="{H:.1f}" fill="#ffffff"/>'
            f'<g clip-path="url(#view)"><g transform="translate(0 {BAR})">{page}</g></g>'
            f'<rect width="{W}" height="{BAR}" fill="{c["bar"]}"/>'
            f'<line x1="0" y1="{BAR - 0.5}" x2="{W}" y2="{BAR - 0.5}" stroke="{c["border"]}"/>{dots}'
            f'<rect x="{W / 2 - pill_w / 2}" y="{BAR / 2 - 11}" width="{pill_w}" height="22" rx="11" '
            f'fill="{c["pill"]}" stroke="{c["border"]}"/>'
            f'<text x="{W / 2}" y="{BAR / 2 + 4.3}" text-anchor="middle" font-size="12.5" fill="{c["pill_text"]}" '
            f'style="font-family:ui-monospace,SFMono-Regular,Consolas,monospace">{host}</text></g>'
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1:.1f}" rx="10" fill="none" stroke="{c["border"]}"/>'
            f'</svg>')
    return out, T, values


def make(shots: Path | None = None, reuse: bool = False, quality: int = 72) -> dict:
    """Screenshots (unless reuse), then both SVG files; returns the headline numbers of the three states."""
    shots = shots or ROOT / "output" / "demo-shots"
    shots.mkdir(parents=True, exist_ok=True)
    if not (reuse and (shots / "geometry.json").exists()):
        take_screenshots(shots)
    svgs, total, values = build(shots, quality)
    for theme, svg in svgs.items():
        path = OUT_DIR / ("app-demo.svg" if theme == "light" else "app-demo-dark.svg")
        path.write_text(svg, encoding="utf-8", newline="\n")
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB, loop {total:g} s")
        if path.stat().st_size > LIMIT:
            sys.exit(f"{path.name} is over {LIMIT // 1024} KB: lower --quality.")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shots", type=Path, help="keep the screenshots and geometry in this folder")
    parser.add_argument("--reuse", action="store_true", help="build from --shots without starting the app")
    parser.add_argument("--quality", type=int, default=72, help="WebP quality of the screenshots")
    args = parser.parse_args()
    make(args.shots, args.reuse, args.quality)


if __name__ == "__main__":
    main()
