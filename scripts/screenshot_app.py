"""
Screenshot of the Dash app for the README (docs/img/app.png): the rules, the headline numbers and the proposals.

Starts the app on 127.0.0.1 on a spare port, opens it in headless Chrome or Edge through the DevTools protocol, waits
for the numbers, saves the PNG and stops the app. Needs the data from scripts/get_data.py and `websockets`
(requirements-dev.txt).

    python scripts/screenshot_app.py
"""
from __future__ import annotations

import asyncio
import base64
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

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img" / "app.png"
APP_PORT, DEBUG_PORT = 8599, 9334
WIDTH, HEIGHT, SCALE = 1440, 1240, 1.0
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def find_browser() -> str:
    for candidate in filter(None, [os.environ.get("CHROME"), *BROWSERS]):
        path = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if path:
            return path
    sys.exit("Chrome, Chromium or Edge not found. Set CHROME to the browser executable.")


def wait_for(url: str, seconds: float = 90) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"{url} did not answer in {seconds:.0f} s")


async def capture(browser: str) -> None:
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", f"--remote-debugging-port={DEBUG_PORT}",
                               f"--user-data-dir={profile}", "--hide-scrollbars", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
    try:
        wait_for(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024) as ws:
            counter = 0

            async def send(method: str, **params):
                nonlocal counter
                counter += 1
                await ws.send(json.dumps({"id": counter, "method": method, "params": params}))
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("id") == counter:
                        return message.get("result", {})

            await send("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT, deviceScaleFactor=SCALE,
                       mobile=False)
            await send("Page.navigate", url=f"http://127.0.0.1:{APP_PORT}/")
            ready = ("[...document.querySelectorAll('.dg-stat-value')].filter(e => e.textContent).length === 5 && "
                     "document.querySelectorAll('.pe-table tbody tr').length > 0")
            for _ in range(240):
                result = await send("Runtime.evaluate", expression=ready, returnByValue=True)
                if result.get("result", {}).get("value"):
                    break
                await asyncio.sleep(0.5)
            else:
                raise SystemExit("The app did not show its numbers in 120 s")
            await send("Runtime.evaluate", expression="document.getElementById('rules').scrollIntoView()")
            await asyncio.sleep(2)  # fonts and layout settle
            shot = await send("Page.captureScreenshot", format="png", captureBeyondViewport=False)
            OUT.write_bytes(base64.b64decode(shot["data"]))
    finally:
        chrome.terminate()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    browser = find_browser()
    env = {**os.environ, "MPLBACKEND": "Agg"}
    env["PE_PORT"] = str(APP_PORT)
    app = subprocess.Popen([sys.executable, "-m", "ui.app"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
    try:
        wait_for(f"http://127.0.0.1:{APP_PORT}/")
        asyncio.run(capture(browser))
    finally:
        if os.name == "nt":  # the venv python is a launcher: stop its child too
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(app.pid)], capture_output=True)
        else:
            app.terminate()
        app.wait(timeout=20)
    print(f"Saved {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
