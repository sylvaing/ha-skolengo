"""Make the README screenshots from docs/screenshots/demo.html (invented data, no real account).

Needs Google Chrome. Run from the repository root: uv run python scripts/make_screenshots.py
"""

from __future__ import annotations

import http.server
import subprocess
import tempfile
import threading
from functools import partial
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SHOTS = {
    "homework.png": "card=homework",
    "timetable.png": "card=timetable",
    "messages.png": "card=messages",
    "dark.png": "theme=dark",
}
MARGIN = 16  # px kept around the cards (at 1x)
SCALE = 2


def _crop(path: Path) -> None:
    """Crop to the cards, keeping a small margin of page background."""
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        background = Image.new("RGB", rgb.size, rgb.getpixel((2, 2)))
        box = ImageChops.difference(rgb, background).getbbox()
        if box:
            m = MARGIN * SCALE
            box = (
                max(box[0] - m, 0),
                max(box[1] - m, 0),
                min(box[2] + m, rgb.width),
                min(box[3] + m, rgb.height),
            )
            rgb = rgb.crop(box)
        rgb.save(path, optimize=True)


def main() -> None:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/docs/screenshots/demo.html"
    try:
        with tempfile.TemporaryDirectory() as profile:
            for name, query in SHOTS.items():
                width = 1340 if query.startswith("theme") else 460
                subprocess.run(
                    [
                        CHROME,
                        "--headless=new",
                        "--disable-gpu",
                        "--hide-scrollbars",
                        f"--user-data-dir={profile}",
                        f"--force-device-scale-factor={SCALE}",
                        f"--window-size={width},1100",
                        "--virtual-time-budget=2000",
                        f"--screenshot={OUT / name}",
                        f"{base}?{query}",
                    ],
                    check=True,
                    capture_output=True,
                )
                _crop(OUT / name)
                with Image.open(OUT / name) as im:
                    print(name, im.size)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
