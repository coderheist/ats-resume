"""
Generates the static image assets referenced by index.html and
site.webmanifest: the Open Graph social card and the PWA icon set.

Run once, or whenever the branding changes:

    python scripts/generate-og-assets.py

Requires Pillow (`pip install pillow`). It is deliberately NOT in
requirements.txt -- this is a one-off asset generator, not something the
app imports at runtime, and the PNGs it produces are committed to
public/. Nothing in the build depends on Pillow being installed.

Why generate rather than hand-design: og:image has a hard requirement
(1200x630, absolute URL, PNG or JPG) that every social crawler enforces,
and a missing or wrongly-sized image produces no preview card at all --
which silently removes the main reason to have Open Graph tags. Colours
come from src/styles/tokens.css so the card matches the actual product.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Straight from src/styles/tokens.css.
PAPER = (246, 245, 241)
PAPER_RAISED = (255, 255, 255)
INK = (27, 36, 48)
INK_SOFT = (91, 100, 114)
RULE = (216, 213, 204)
MATCH = (63, 110, 82)
MATCH_BG = (228, 238, 231)
MATCH_LINE = (185, 210, 193)
ACCENT = (228, 161, 27)
BRAND = (31, 77, 69)

OUT = Path(__file__).resolve().parent.parent / "public"


def _font(size: int, bold: bool = False):
    """Pillow ships only a tiny bitmap default font, which looks broken at
    display sizes. Try the common system faces first and fall back rather
    than failing the whole script -- a slightly different typeface on the
    social card is a far better outcome than no card."""
    candidates = [
        "seguisb.ttf" if bold else "segoeui.ttf",      # Windows
        "Arial Bold.ttf" if bold else "Arial.ttf",      # macOS
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",  # Linux
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def make_og_image() -> None:
    """1200x630 -- the size Facebook, LinkedIn, Slack and X all crop
    predictably. Anything else gets cropped differently per platform."""
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # Accent rule along the top edge.
    d.rectangle([0, 0, W, 8], fill=BRAND)

    title = _font(58, bold=True)
    lede = _font(27)
    small = _font(21, bold=True)
    tiny = _font(18)

    d.text((72, 92), "Resume Optimizer", font=small, fill=MATCH)

    d.text((72, 140), "Know exactly where", font=title, fill=INK)
    d.text((72, 208), "your resume stands.", font=title, fill=INK)

    for i, line in enumerate([
        "Free ATS resume checker. Score your resume against",
        "any job description and see what to fix first.",
    ]):
        d.text((72, 300 + i * 38), line, font=lede, fill=INK_SOFT)

    # A miniature of the real report card, rather than a stock graphic --
    # the same reasoning as the landing page hero showing live components.
    card = (700, 150, 1128, 500)
    _rounded(d, card, 10, fill=PAPER_RAISED, outline=RULE, width=2)

    d.text((732, 182), "JOB MATCH SCORE", font=tiny, fill=INK_SOFT)
    d.text((732, 212), "82", font=_font(76, bold=True), fill=MATCH)
    d.text((828, 258), "/ 100", font=_font(24), fill=INK_SOFT)

    pill = (900, 212, 1096, 252)
    _rounded(d, pill, 20, fill=MATCH_BG, outline=MATCH_LINE, width=1)
    d.text((922, 224), "Strong Match", font=_font(19, bold=True), fill=MATCH)

    # Gauge.
    _rounded(d, (732, 306, 1096, 320), 7, fill=(232, 229, 220))
    _rounded(d, (732, 306, 732 + int(364 * 0.82), 320), 7, fill=MATCH)

    for i, (label, val) in enumerate([("Technical Skills", 88), ("Experience", 74)]):
        y = 348 + i * 56
        d.text((732, y), label, font=tiny, fill=INK_SOFT)
        d.text((1040, y - 4), str(val), font=_font(24, bold=True), fill=INK)
        _rounded(d, (732, y + 26, 1010, 34 + y), 4, fill=(232, 229, 220))
        _rounded(d, (732, y + 26, 732 + int(278 * val / 100), 34 + y), 4, fill=ACCENT)

    d.text((72, 530), "resume-optimizer  ·  evidence-based, not a black box",
           font=_font(20), fill=INK_SOFT)

    img.save(OUT / "og-image.png", "PNG", optimize=True)
    print(f"  og-image.png            1200x630")


def make_icon(size: int, filename: str, maskable: bool = False) -> None:
    """Maskable icons need their content inside a safe zone -- Android
    crops them to whatever mask the launcher uses (circle, squircle,
    rounded square), so artwork drawn to the edges gets clipped."""
    img = Image.new("RGB", (size, size), BRAND)
    d = ImageDraw.Draw(img)

    inset = size * 0.28 if maskable else size * 0.22
    page = (inset, inset * 0.82, size - inset, size - inset * 0.82)
    d.rectangle(page, outline=(244, 234, 215), width=max(2, int(size * 0.055)))

    line_x0 = page[0] + (page[2] - page[0]) * 0.22
    line_x1 = page[0] + (page[2] - page[0]) * 0.78
    for i, frac in enumerate([0.30, 0.52, 0.74]):
        y = page[1] + (page[3] - page[1]) * frac
        x1 = line_x1 if i < 2 else line_x0 + (line_x1 - line_x0) * 0.6
        d.line([(line_x0, y), (x1, y)], fill=(244, 234, 215), width=max(2, int(size * 0.045)))

    img.save(OUT / filename, "PNG", optimize=True)
    print(f"  {filename:<24}{size}x{size}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Writing assets to {OUT}")
    make_og_image()
    make_icon(192, "icon-192.png")
    make_icon(512, "icon-512.png")
    make_icon(512, "icon-512-maskable.png", maskable=True)
    print("Done.")
