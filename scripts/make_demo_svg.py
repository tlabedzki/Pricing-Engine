"""
Build docs/img/app-demo.svg and app-demo-dark.svg, the animated demo at the top of the README.

    python scripts/make_demo_svg.py [--shots DIR] [--reuse] [--quality 72] [--res 1.25]

The demo is an illustration made of screenshots of the real app, not a recording. One loop of 14.5 s: the page
scrolls from the top to the rules, the cursor drags the limit over the competitor median from +5% to +10% and the
largest price step from 10% to 15% (the value next to each slider follows the drag, the headline numbers change
after the release, like the app's updatemode "mouseup"), the page scrolls to the proposals, the cursor shows the
lowered prices and opens the Categories tab, whose two bar charts grow in, then the page scrolls through both charts
and back to the top. The same story as the Pricing-Engine card on the GitHub profile, in the README's browser frame.

The script starts the Dash app on 127.0.0.1 and takes full-page screenshots 960 CSS px wide at device scale factor 2
(headless Chrome or Edge through the DevTools protocol) in each state: the base rules, every whole value of the
competitor limit from +6% to +10%, every largest step from 11% to 15%, then the lowered prices and the Categories tab.
The headline numbers of every state come from the pricing engine in this script (`pricing_engine.report.kpis`), the
same code the app and the README use, and the script stops if the app shows other numbers. Track, bar and thumb of
the two sliders, the cursor, the clicks and the scrollbar are vectors.

Only CSS animations of transform and opacity inside the SVG, no script and no external file: GitHub shows README
images through <img>. With prefers-reduced-motion the image shows the rules after both drags and their numbers,
without motion. The two files differ only in the browser frame (light and dark GitHub theme), so each <picture>
source is its own file (Firefox freezes the animation of one SVG shown twice with different colour schemes).
--shots keeps the screenshots and their geometry in DIR; --reuse builds from them without starting the app; two
builds from the same screenshots give the same bytes.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
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

from pricing_engine import data, elasticity, engine, report  # noqa: E402
from pricing_engine import theme as look  # noqa: E402
from ui.app import STATS, rule_text  # noqa: E402

OUT_DIR = ROOT / "docs" / "img"
DEBUG_PORT, APP_PORT = 9335, 8597
CSS_W, DSF = 960, 2  # app page width in CSS px, screenshot pixels per CSS px
VIEW = 640  # CSS px of the page in view
W = 1000  # SVG width
K = W / CSS_W
BAR = 36  # browser bar above the page
LIMIT = 500 * 1024  # bytes per SVG
EASE = "cubic-bezier(.65,0,.35,1)"
EASE_OUT = "cubic-bezier(.22,1,.36,1)"
INK = look.INK
CURSOR = "M0 0V17.2L4.3 13.3L7.2 20.1L10.3 18.8L7.5 12.2H13.2Z"  # arrow, tip at 0,0
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
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

# The rules of each screenshot: base, the competitor limit moved one point at a time, then the largest step.
STATES = {"base": (5, 10), **{f"above-{v}": (v, 10) for v in range(6, 11)},
          **{f"step-{v}": (10, v) for v in range(11, 16)}, "bold-lower": (10, 15), "bold-categories": (10, 15)}

# Timeline (seconds). Scroll positions in CSS px of the page, tuned to LAYOUT (checked against the screenshots).
T = 14.5
Y_TOP, Y_RULES, Y_TABLE, Y_CHARTS = 0, 610, 1130, 1720
LAYOUT = {"rules_section": 489, "stats": 1148, "view": 1280, "show": 1347}
SCROLL = [(0, Y_TOP), (0.7, Y_TOP), (1.8, Y_RULES), (6.2, Y_RULES), (7.3, Y_TABLE), (10.6, Y_TABLE),
          (11.8, Y_CHARTS), (13.0, Y_CHARTS), (T, Y_TOP)]
PRESS_ABOVE, RELEASE_ABOVE = 2.35, 3.35
PRESS_STEP, RELEASE_STEP = 4.2, 5.2
LAG = 0.3  # the app recalculates after the release
CLICK_LOWER, CLICK_CATEGORIES = 7.75, 8.95
GROW = [(9.2, 10.0), (11.3, 12.1)]  # the two category charts grow in
DRAGS = {"above": [(0, 5), (PRESS_ABOVE, 5), (RELEASE_ABOVE, 10)],
         "step": [(0, 10), (PRESS_STEP, 10), (RELEASE_STEP, 15)]}


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
  const box = e => { const r = e.getBoundingClientRect();
    return {x: r.left, y: r.top + scrollY, w: r.width, h: r.height}; };
  const text = e => { const r = document.createRange(); r.selectNodeContents(e); return box(r); };
  const css = (e, pseudo) => { const s = getComputedStyle(e, pseudo);
    return {color: s.color, background: s.backgroundColor, border: s.borderTopColor,
            border_width: parseFloat(s.borderTopWidth) || 0, height: s.height, size: parseFloat(s.fontSize)}; };
  const rules = {};
  for (const el of document.querySelectorAll('.pe-rule')) {
    const value = el.querySelector('.pe-rule-value');
    const thumb = el.querySelector('.mantine-Slider-thumb');
    const track = el.querySelector('.mantine-Slider-track');
    const bar = el.querySelector('.mantine-Slider-bar');
    rules[value.id.replace('-value', '')] = {value: text(value), value_text: value.textContent,
      head: box(el.querySelector('.pe-rule-head')), thumb: box(thumb), thumb_style: css(thumb), track: box(track),
      track_style: css(track, '::before'), bar: box(bar), bar_style: css(bar),
      min: +thumb.getAttribute('aria-valuemin'), max: +thumb.getAttribute('aria-valuemax'),
      now: +thumb.getAttribute('aria-valuenow')};
  }
  const segments = id => Object.fromEntries([...document.querySelectorAll(`#${id} label`)]
    .map(l => [l.textContent.trim(), box(l)]));
  const plots = [...document.querySelectorAll('#view-categories .js-plotly-plot')].map(gd => {
    const b = box(gd), s = gd._fullLayout._size, xa = gd._fullLayout.xaxis;
    return {box: b, plot: {x: b.x + s.l, y: b.y + s.t, w: s.w, h: s.h}, zero: b.x + s.l + xa.l2p(0)};
  });
  const notes = [...document.querySelectorAll('.dg-stat-note')].map(e => e.textContent);
  return JSON.stringify({rules, stats: box(document.getElementById('stats')),
    stat_values: [...document.querySelectorAll('.dg-stat-value')].map(e => e.textContent), stat_notes: notes,
    view: box(document.getElementById('view')), view_segments: segments('view'),
    show: box(document.getElementById('show')), show_segments: segments('show'),
    proposals: box(document.getElementById('view-proposals')),
    rules_section: box(document.getElementById('rules')), plots,
    page_bg: getComputedStyle(document.querySelector('.dg-page')).backgroundColor,
    height: document.documentElement.scrollHeight});
})()"""

READY_JS = ("[...document.querySelectorAll('.dg-stat-value')].filter(e => e.textContent).length === 5 && "
            "document.querySelectorAll('.pe-table tbody tr').length > 5 && "
            "document.getElementById('above-value').textContent === {above!r} && "
            "document.getElementById('step-value').textContent === {step!r}")
CENTRE_JS = ("(() => {{ const l = [...document.querySelectorAll('#{group} label')]"
             ".find(e => e.textContent.trim() === {label!r}); l.scrollIntoView({{block: 'center'}}); "
             "const r = l.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
CHARTS_JS = "document.querySelectorAll('#view-categories .js-plotly-plot .main-svg').length >= 2"


async def capture(browser: str, shots: Path) -> None:
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", f"--remote-debugging-port={DEBUG_PORT}",
                               f"--user-data-dir={profile}", "--hide-scrollbars", "--lang=en-US", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
    geometry = {}
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

            async def js(expression: str, wait: bool = False):
                result = await send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=wait)
                if "exceptionDetails" in result:
                    raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description"))
                return result.get("result", {}).get("value")

            async def until(expression: str, what: str) -> None:
                for _ in range(240):
                    if await js(expression):
                        return
                    await asyncio.sleep(0.5)
                raise SystemExit(f"The app did not show {what} in 120 s")

            async def mouse(kind: str, x: float, y: float, **extra) -> None:
                await send("Input.dispatchMouseEvent", type=kind, x=x, y=y, **extra)

            async def click(group: str, label: str) -> None:
                x, y = await js(CENTRE_JS.format(group=group, label=label))
                await asyncio.sleep(0.3)
                await mouse("mouseMoved", x, y)
                await mouse("mousePressed", x, y, button="left", clickCount=1)
                await mouse("mouseReleased", x, y, button="left", clickCount=1)
                await mouse("mouseMoved", 2, 2)
                await asyncio.sleep(2.5)

            async def shoot(name: str) -> None:
                await js("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")
                await mouse("mouseMoved", 2, 2)
                await asyncio.sleep(0.6)
                height = await js("document.documentElement.scrollHeight")
                shot = await send("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                                  clip={"x": 0, "y": 0, "width": CSS_W, "height": height, "scale": 1})
                (shots / f"{name}.png").write_bytes(base64.b64decode(shot["data"]))
                geometry[name] = json.loads(await js(GEOMETRY_JS))
                print(name, height, " | ".join(geometry[name]["stat_values"]))

            await send("Emulation.setDeviceMetricsOverride", width=CSS_W, height=900, deviceScaleFactor=DSF,
                       mobile=False)
            for name, (above, step) in STATES.items():
                if name == "bold-lower":
                    await click("show", "lower")
                elif name == "bold-categories":
                    await click("view", "Categories")
                    await until(CHARTS_JS, "the Categories charts")
                    await asyncio.sleep(1.5)
                else:
                    await send("Page.navigate", url=f"http://127.0.0.1:{APP_PORT}/?above={above}&step={step}")
                    await asyncio.sleep(2)
                    await until(READY_JS.format(above=rule_text("above", above), step=rule_text("step", step)),
                                f"its numbers for {name}")
                    await js("document.documentElement.style.scrollBehavior = 'auto'")
                    await js("document.fonts.ready.then(() => true)", wait=True)
                    await asyncio.sleep(1.5)
                await shoot(name)
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
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


def numbers() -> dict[tuple[int, int], dict]:
    """The headline numbers of each set of rules from the engine, formatted like the app."""
    shop = data.load()
    table = elasticity.estimate(shop)
    snap = engine.snapshot(shop, table)
    truth = shop.true_elasticity()
    return {rules: report.kpis(engine.propose(snap, engine.Rules(max_above_market=rules[0] / 100,
                                                                  max_step=rules[1] / 100)), truth)
            for rules in sorted(set(STATES.values()))}


def check(geo: dict, values: dict) -> None:
    """Stop when the screenshots are not the states of STATES, show other numbers than the engine gives here or
    have another layout than the timeline was tuned to."""
    if set(geo) != set(STATES):
        sys.exit("The screenshots are not the states of this script: run without --reuse.")
    for name, (above, step) in STATES.items():
        state, expected = geo[name], values[(above, step)]
        shown = list(zip(state["stat_values"], state["stat_notes"], strict=True))
        wanted = [(expected[key], note.format(**expected)) for key, _, note in STATS]
        if shown != wanted:
            sys.exit(f"The app shows {shown} for {name}, the engine gives {wanted}: retake the screenshots.")
        for rule, value in (("above", above), ("step", step)):
            if state["rules"][rule]["value_text"] != rule_text(rule, value):
                sys.exit(f"The app shows {rule} = {state['rules'][rule]['value_text']} for {name}.")
        for key, y in LAYOUT.items():
            if name == "bold-categories" and key == "show":  # the Categories tab hides the table filter
                continue
            if abs(state[key]["y"] - y) > 3:
                sys.exit(f"{name}: {key} at y = {state[key]['y']:.0f} instead of {y}: retune the timeline.")


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


def tr(x: float, y: float) -> str:
    return f"translate({x:.1f}px,{y:.1f}px)"


def css_color(value: str) -> str:
    """rgb(1, 2, 3) to #010203."""
    parts = [int(float(p)) for p in value[value.index("(") + 1:value.index(")")].split(",")[:3]]
    return "#{:02x}{:02x}{:02x}".format(*parts)


def build(shots: Path, quality: int, res: float) -> tuple[dict[str, str], dict]:
    geo = json.loads((shots / "geometry.json").read_text(encoding="utf-8"))
    values = numbers()
    check(geo, values)
    base, bold, cats = geo["base"], geo["step-15"], geo["bold-categories"]
    images = {name: Image.open(shots / f"{name}.png").convert("RGB") for name in geo}
    for name, im in images.items():
        if im.width != CSS_W * DSF:
            sys.exit(f"{name}.png is not {CSS_W} CSS px at device scale factor {DSF}: run without --reuse.")
    page_bg = css_color(base["page_bg"])

    def image(name: str, x0: float, y0: float, x1: float, y1: float) -> str:
        """Part of a screenshot (CSS px box) as a WebP <image> in page px."""
        crop = images[name].crop((round(x0 * DSF), round(y0 * DSF), round(x1 * DSF), round(y1 * DSF)))
        size = (max(1, round((x1 - x0) * K * res)), max(1, round((y1 - y0) * K * res)))
        buffer = io.BytesIO()
        crop.resize(size, Image.LANCZOS).save(buffer, "WEBP", quality=quality, method=6)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return (f'<image x="{x0 * K:.2f}" y="{y0 * K:.2f}" width="{(x1 - x0) * K:.2f}" height="{(y1 - y0) * K:.2f}" '
                f'preserveAspectRatio="none" href="data:image/webp;base64,{encoded}"/>')

    def switch_on(t: float, fade: float = 0.22) -> list:
        """Opacity: hidden until t, then shown to the end of the loop (the loop starts hidden again)."""
        return [(0, 0, "linear"), (t, 0, EASE), (t + fade, 1, "linear")]

    m = Motion(T)
    page: list[str] = []  # page coordinates, moved by the scroll
    view: list[str] = []  # fixed in the view: cursor, click rings, scrollbar

    # 1. the page: base rules down to the numbers, below them the proposals after the new rules
    split = Y_RULES + VIEW + 4
    page.append(image("base", 0, 0, CSS_W, split))
    page.append(image("step-15", 0, split, CSS_W, Y_TABLE + VIEW + 4))
    # the headline numbers after each release
    s = base["stats"]
    for name, t in (("above-10", RELEASE_ABOVE + LAG), ("step-15", RELEASE_STEP + LAG)):
        page.append(f'<g class="{m.track("opacity", switch_on(t), 1)}">'
                    f'{image(name, s["x"] - 4, s["y"] - 4, s["x"] + s["w"] + 4, s["y"] + s["h"] + 4)}</g>')
    # the proposals of the lowered prices, then the Categories tab with its charts
    proposals = bold["proposals"]
    page.append(f'<g class="{m.track("opacity", switch_on(CLICK_LOWER + 0.2), 0)}">'
                f'{image("bold-lower", 0, proposals["y"] - 6, CSS_W, Y_TABLE + VIEW + 4)}</g>')
    grow = []
    for (t0, t1), plot in zip(GROW, cats["plots"], strict=True):
        p = plot["plot"]
        x0, x1 = plot["zero"] + 1.5, p["x"] + p["w"]
        cls = m.track("transform", [(0, "scaleX(1)", "linear"), (t0, "scaleX(1)", EASE_OUT),
                                    (t1, "scaleX(0)", "linear")], "scaleX(0)")
        # anchored at the right edge: shrinking to it uncovers the bars from zero outwards, as if they grew
        grow.append(f'<g transform="translate({x1 * K:.2f} {p["y"] * K:.2f})"><rect class="{cls}" '
                    f'x="{-(x1 - x0) * K:.2f}" width="{(x1 - x0) * K:.2f}" height="{p["h"] * K:.2f}" '
                    f'fill="{page_bg}"/></g>')
    page.append(f'<g class="{m.track("opacity", switch_on(CLICK_CATEGORIES + 0.15, 0.18), 0)}">'
                f'{image("bold-categories", 0, cats["view"]["y"] - 4, CSS_W, cats["height"])}{"".join(grow)}</g>')

    # 2. the two sliders: a patch over each, then track, bar and thumb as vectors moving with the drag
    times = [round(i / 50, 2) for i in range(int(T * 50) + 1)]
    thumbs = {}
    for rule, stops in DRAGS.items():
        r = base["rules"][rule]
        tx, tw = r["track"]["x"], r["track"]["w"]
        cy = r["thumb"]["y"] + r["thumb"]["h"] / 2
        radius = r["thumb"]["w"] / 2
        bar_x, end = r["bar"]["x"], tx + tw + radius
        line_h = r["bar"]["h"]

        def x_of(v: float, r=r, tx=tx, tw=tw) -> float:
            return tx + (v - r["min"]) / (r["max"] - r["min"]) * tw

        page.append(f'<rect x="{(bar_x - 8) * K:.2f}" y="{(cy - radius - 4) * K:.2f}" '
                    f'width="{(end - bar_x + 16) * K:.2f}" height="{(2 * radius + 8) * K:.2f}" fill="{page_bg}"/>')
        bar = f'y="{(cy - line_h / 2) * K:.2f}" height="{line_h * K:.2f}" rx="{line_h * K / 2:.2f}"'
        full = end - bar_x
        page.append(f'<rect x="{bar_x * K:.2f}" width="{full * K:.2f}" {bar} '
                    f'fill="{css_color(r["track_style"]["background"])}"/>')
        moving = [t for t in times if stops[1][0] <= t <= stops[2][0]]
        keys = sorted({0.0, T, *[t for t, _ in stops], *moving})
        rest_x, final_x = x_of(stops[0][1]), x_of(stops[-1][1])  # without motion: the final point
        fill = m.track("transform", [(t, f"scaleX({(x_of(path_value(stops, t)) + radius - bar_x) / full:.4f})",
                                      "linear") for t in keys], f"scaleX({(final_x + radius - bar_x) / full:.4f})")
        page.append(f'<g transform="translate({bar_x * K:.2f} 0)"><rect class="{fill}" width="{full * K:.2f}" {bar} '
                    f'fill="{css_color(r["bar_style"]["background"])}"/></g>')
        move = m.track("transform", [(t, tr((x_of(path_value(stops, t)) - rest_x) * K, 0), "linear") for t in keys],
                       tr((final_x - rest_x) * K, 0))
        ts = r["thumb_style"]
        ring = ts["border_width"]
        page.append(f'<g class="{move}"><circle cx="{rest_x * K:.2f}" cy="{cy * K:.2f}" '
                    f'r="{(radius - ring / 2) * K:.2f}" fill="{css_color(ts["background"])}" '
                    f'stroke="{css_color(ts["border"])}" stroke-width="{ring * K:.2f}"/></g>')
        # the value next to the label follows the drag: one screenshot crop per whole value
        lo, hi = stops[0][1], stops[-1][1]
        widest = max(geo[f"{rule}-{v}"]["rules"][rule]["value"]["w"] for v in range(lo + 1, hi + 1))
        vb = r["value"]
        right = vb["x"] + vb["w"]
        for v in range(lo + 1, hi + 1):
            on = [round(path_value(stops, t) + 1e-9) == v for t in times]
            track = [(0, int(on[0]), "linear")]
            for i in range(1, len(times)):
                if on[i] != on[i - 1]:
                    track += [(times[i] - 0.001, int(on[i - 1]), "linear"), (times[i], int(on[i]), "linear")]
            crop = image(f"{rule}-{v}", right - widest - 6, vb["y"] - 3, right + 3, vb["y"] + vb["h"] + 3)
            page.append(f'<g class="{m.track("opacity", track, int(v == hi))}">{crop}</g>')
        thumbs[rule] = lambda v, x_of=x_of, cy=cy: (x_of(v), cy)

    # 3. the scroll: the page glides between the views, a scrollbar thumb follows
    scroll_stops = [(t, y, EASE if i + 1 < len(SCROLL) and SCROLL[i + 1][1] != y else "linear")
                    for i, (t, y) in enumerate(SCROLL)]
    scroll = m.track("transform", [(t, tr(0, -y * K), e) for t, y, e in scroll_stops], tr(0, -Y_RULES * K))
    height = cats["height"]
    thumb_h = VIEW * VIEW / height
    room = VIEW - thumb_h - 6

    def thumb_y(y: float) -> float:
        return y / (height - VIEW) * room

    bar = m.track("transform", [(t, tr(0, thumb_y(y) * K), e) for t, y, e in scroll_stops],
                  tr(0, thumb_y(Y_RULES) * K))
    view.append(f'<rect class="{bar}" x="{(CSS_W - 7) * K:.2f}" y="{3 * K:.2f}" width="{4 * K:.2f}" '
                f'height="{thumb_h * K:.2f}" rx="{2 * K:.2f}" fill="{INK}" opacity="0.28"/>')

    # 4. the cursor (view coordinates): rest, drag one rule, drag the other, "lower", "Categories", rest
    def at_view(xy: tuple[float, float], y_scroll: float) -> tuple[float, float]:
        return xy[0], xy[1] - y_scroll

    def centre(b: dict, y_scroll: float) -> tuple[float, float]:
        return b["x"] + b["w"] / 2, b["y"] + b["h"] / 2 - y_scroll

    rest = (720, 400)
    grab1 = at_view(thumbs["above"](5), Y_RULES)
    grab2 = at_view(thumbs["step"](10), Y_RULES)
    lower = centre(base["show_segments"]["lower"], Y_TABLE)
    categories = centre(base["view_segments"]["Categories"], Y_TABLE)
    path = [(0, rest, "linear"), (1.6, rest, EASE), (PRESS_ABOVE - 0.12, grab1, "linear")]
    path += [(t, at_view(thumbs["above"](path_value(DRAGS["above"], t)), Y_RULES), "linear")
             for t in times if PRESS_ABOVE <= t <= RELEASE_ABOVE]
    path += [(3.55, at_view(thumbs["above"](10), Y_RULES), EASE), (PRESS_STEP - 0.12, grab2, "linear")]
    path += [(t, at_view(thumbs["step"](path_value(DRAGS["step"], t)), Y_RULES), "linear")
             for t in times if PRESS_STEP <= t <= RELEASE_STEP]
    path += [(7.05, at_view(thumbs["step"](15), Y_RULES), EASE), (CLICK_LOWER - 0.1, lower, "linear"),
             (8.35, lower, EASE), (CLICK_CATEGORIES - 0.1, categories, "linear"),
             (12.4, categories, EASE), (13.6, rest, "linear")]
    cursor_move = m.track("transform", [(t, tr(x * K, y * K), e) for t, (x, y), e in path],
                          tr(rest[0] * K, rest[1] * K))
    cursor_show = m.track("opacity", [(0, 1, "linear")], 0)
    press = [(0, "scale(1)", "linear")]
    for down, up in ((PRESS_ABOVE, RELEASE_ABOVE), (PRESS_STEP, RELEASE_STEP), (CLICK_LOWER, CLICK_LOWER + 0.12),
                     (CLICK_CATEGORIES, CLICK_CATEGORIES + 0.12)):
        press += [(down - 0.08, "scale(1)", EASE_OUT), (down, "scale(.88)", "linear"), (up, "scale(.88)", EASE_OUT),
                  (up + 0.18, "scale(1)", "linear")]
    cursor_press = m.track("transform", press, "scale(1)")
    accent = css_color(base["rules"]["above"]["bar_style"]["background"])
    for t0, (x, y) in ((PRESS_ABOVE, grab1), (PRESS_STEP, grab2), (CLICK_LOWER, lower),
                       (CLICK_CATEGORIES, categories)):
        ring = m.track("transform", [(t0, "scale(.2)", EASE_OUT), (t0 + 0.5, "scale(1)", "linear"),
                                     (t0 + 0.51, "scale(.2)", "linear")], "scale(1)")
        fade = m.track("opacity", [(t0 - 0.01, 0, "linear"), (t0, 0.45, EASE_OUT), (t0 + 0.5, 0, "linear")], 0)
        view.append(f'<g transform="translate({x * K:.1f} {y * K:.1f})"><g class="{fade}"><circle class="{ring}" '
                    f'r="18" fill="{accent}" fill-opacity="0.35"/></g></g>')
    view.append(f'<g class="{cursor_show}"><g class="{cursor_move}"><g class="{cursor_press}">'
                f'<path d="{CURSOR}" transform="scale(1.15)" fill="{INK}" stroke="#ffffff" stroke-width="1.3" '
                f'stroke-linejoin="round" filter="url(#shadow)"/></g></g></g>')

    shown = {"base": values[STATES["base"]], "above": values[STATES["above-10"]], "bold": values[STATES["step-15"]]}
    alt = (f"Pricing Engine app, illustrated: the competitor limit is dragged from +5% to +10% and the largest price "
           f"step from 10% to 15%, yearly gross profit moves from {shown['base']['profit']} to "
           f"{shown['above']['profit']} and {shown['bold']['profit']} PLN, then the lowered prices and the profit "
           f"change per category.")
    vh = VIEW * K
    H = BAR + vh
    css = "".join(m.css) + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    content = (f'<g clip-path="url(#view)"><g transform="translate(0 {BAR})"><g class="{scroll}">{"".join(page)}</g>'
               f'{"".join(view)}</g></g>')
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
            f'<g clip-path="url(#frame)"><rect width="{W}" height="{H:.1f}" fill="{page_bg}"/>{content}'
            f'<rect width="{W}" height="{BAR}" fill="{c["bar"]}"/>'
            f'<line x1="0" y1="{BAR - 0.5}" x2="{W}" y2="{BAR - 0.5}" stroke="{c["border"]}"/>{dots}'
            f'<rect x="{W / 2 - pill_w / 2}" y="{BAR / 2 - 11}" width="{pill_w}" height="22" rx="11" '
            f'fill="{c["pill"]}" stroke="{c["border"]}"/>'
            f'<text x="{W / 2}" y="{BAR / 2 + 4.3}" text-anchor="middle" font-size="12.5" fill="{c["pill_text"]}" '
            f'style="font-family:ui-monospace,SFMono-Regular,Consolas,monospace">{host}</text></g>'
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1:.1f}" rx="10" fill="none" stroke="{c["border"]}"/>'
            f'</svg>')
    return out, shown


def make(shots: Path | None = None, reuse: bool = False, quality: int = 72, res: float = 1.25) -> dict:
    """Screenshots (unless reuse), then both SVG files; returns the headline numbers of the base rules ("base"),
    after the first drag ("above") and after both ("bold")."""
    shots = shots or ROOT / "output" / "demo-shots"
    shots.mkdir(parents=True, exist_ok=True)
    if not (reuse and (shots / "geometry.json").exists()):
        take_screenshots(shots)
    svgs, shown = build(shots, quality, res)
    for theme, svg in svgs.items():
        path = OUT_DIR / ("app-demo.svg" if theme == "light" else "app-demo-dark.svg")
        path.write_text(svg, encoding="utf-8", newline="\n")
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB, loop {T:g} s")
        if path.stat().st_size > LIMIT:
            sys.exit(f"{path.name} is over {LIMIT // 1024} KB: lower --quality or --res.")
    return shown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shots", type=Path, help="keep the screenshots and geometry in this folder")
    parser.add_argument("--reuse", action="store_true", help="build from --shots without starting the app")
    parser.add_argument("--quality", type=int, default=72, help="WebP quality of the screenshots")
    parser.add_argument("--res", type=float, default=1.25, help="image pixels per SVG pixel")
    args = parser.parse_args()
    make(args.shots, args.reuse, args.quality, args.res)


if __name__ == "__main__":
    main()
