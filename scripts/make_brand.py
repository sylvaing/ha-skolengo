"""Draw the integration's brand images (our own design, no third-party trademark).

Run: uv run python scripts/make_brand.py  → custom_components/skolengo/brand/*.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "skolengo" / "brand"
SS = 4  # supersampling for smooth edges
BLUE, BLUE_DARK, WHITE, ACCENT = (63, 81, 181), (40, 53, 147), (255, 255, 255), (255, 193, 7)
PAGE, LINE = (232, 234, 246), (159, 168, 218)
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no TrueType font found")


def draw_icon(size: int) -> Image.Image:
    """A rounded square with an open book and a check mark (homework done)."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BLUE)
    # gradient-ish lower band
    d.rounded_rectangle((0, int(s * 0.55), s - 1, s - 1), radius=int(s * 0.22), fill=BLUE_DARK)
    d.rectangle((0, int(s * 0.55), s - 1, int(s * 0.75)), fill=BLUE_DARK)
    d.rectangle((0, int(s * 0.5), s - 1, int(s * 0.56)), fill=BLUE)
    # open book: two pages
    cx, top, bottom = s / 2, s * 0.30, s * 0.72
    w = s * 0.30
    d.polygon([(cx, top + s * 0.04), (cx - w, top), (cx - w, bottom - s * 0.04), (cx, bottom)], fill=WHITE)
    d.polygon([(cx, top + s * 0.04), (cx + w, top), (cx + w, bottom - s * 0.04), (cx, bottom)], fill=PAGE)
    d.line([(cx, top + s * 0.04), (cx, bottom)], fill=BLUE_DARK, width=max(1, int(s * 0.012)))
    # text lines on the left page
    for i in range(4):
        y = top + s * (0.09 + i * 0.075)
        d.line([(cx - w * 0.82, y), (cx - w * 0.18, y + s * 0.012)], fill=LINE, width=int(s * 0.018))
    # check mark on the right page
    d.line(
        [(cx + w * 0.22, s * 0.50), (cx + w * 0.45, s * 0.58), (cx + w * 0.82, s * 0.38)],
        fill=ACCENT,
        width=int(s * 0.045),
        joint="curve",
    )
    return img.resize((size, size), Image.Resampling.LANCZOS)


def draw_logo(height: int, dark: bool = False) -> Image.Image:
    """The icon followed by "ENT" (logo: landscape, transparent background)."""
    s = height * SS
    font = _font(int(s * 0.62))
    text = "ENT"
    text_w = int(font.getlength(text))
    gap = int(s * 0.18)
    img = Image.new("RGBA", (s + gap + text_w + int(s * 0.05), s), (0, 0, 0, 0))
    img.paste(draw_icon(s), (0, 0))
    d = ImageDraw.Draw(img)
    d.text((s + gap, s / 2), text, font=font, fill=WHITE if dark else BLUE_DARK, anchor="lm")
    return img.resize((img.width // SS, height), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(256).save(OUT / "icon.png", optimize=True)
    draw_icon(512).save(OUT / "icon@2x.png", optimize=True)
    draw_logo(128).save(OUT / "logo.png", optimize=True)
    draw_logo(256).save(OUT / "logo@2x.png", optimize=True)
    draw_logo(128, dark=True).save(OUT / "dark_logo.png", optimize=True)
    draw_logo(256, dark=True).save(OUT / "dark_logo@2x.png", optimize=True)
    for path in sorted(OUT.glob("*.png")):
        with Image.open(path) as im:
            print(path.name, im.size)


if __name__ == "__main__":
    main()
