"""Regenerate the PNG interface icons in assets/icons (needs Pillow): python assets/brand/make_icons.py"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "icons"
SCALE = 8


def canvas(size):
    return Image.new("RGBA", (size * SCALE, size * SCALE), (0, 0, 0, 0))


def save(image, name, size):
    OUT.mkdir(exist_ok=True)
    image.resize((size, size), Image.LANCZOS).save(OUT / f"{name}.png")


def tile(size, fill, radius=0.26):
    image = canvas(size)
    s = size * SCALE
    ImageDraw.Draw(image).rounded_rectangle((0, 0, s - 1, s - 1), int(s * radius), fill=fill)
    return image


def claude(size, fg=(255, 159, 110), bg=(42, 26, 18)):
    """Warm sunburst: twelve tapered rays."""
    image = tile(size, bg)
    draw = ImageDraw.Draw(image)
    s = size * SCALE
    c = s / 2
    for i in range(12):
        a = math.radians(i * 30 + (7 if i % 2 else 0))
        length = s * (0.30 if i % 2 else 0.34)
        w = s * 0.045
        tip = (c + math.cos(a) * length, c + math.sin(a) * length)
        n = (-math.sin(a) * w, math.cos(a) * w)
        draw.polygon([(c + n[0], c + n[1]), tip, (c - n[0], c - n[1])], fill=fg)
    draw.ellipse((c - s * .07, c - s * .07, c + s * .07, c + s * .07), fill=fg)
    return image


def openai(size, fg=(94, 230, 168), bg=(16, 38, 28)):
    """Two interlaced hexagon outlines."""
    image = tile(size, bg)
    draw = ImageDraw.Draw(image)
    s = size * SCALE
    c = s / 2
    w = max(2, int(s * 0.06))
    for offset in (0, 30):
        points = [(c + math.cos(math.radians(offset + i * 60)) * s * 0.27,
                   c + math.sin(math.radians(offset + i * 60)) * s * 0.27) for i in range(7)]
        draw.line(points, fill=fg, width=w, joint="curve")
    return image


def line_icon(size, name, color):
    image = canvas(size)
    draw = ImageDraw.Draw(image)
    s = size * SCALE
    w = int(s * 0.075)
    m = s * 0.16
    if name == "overview":
        g = (s - 2 * m) / 2 - s * 0.05
        for dx in (0, 1):
            for dy in (0, 1):
                x, y = m + dx * (g + s * 0.1), m + dy * (g + s * 0.1)
                draw.rounded_rectangle((x, y, x + g, y + g), int(s * 0.06), outline=color, width=w)
    elif name == "models":
        c = s / 2
        top = [(c, m), (s - m, s * 0.33), (c, s * 0.5), (m, s * 0.33)]
        draw.line(top + [top[0]], fill=color, width=w, joint="curve")
        draw.line([(m, s * 0.33), (m, s * 0.67), (c, s - m), (s - m, s * 0.67), (s - m, s * 0.33)],
                  fill=color, width=w, joint="curve")
        draw.line([(c, s * 0.5), (c, s - m)], fill=color, width=w)
    elif name == "keys":
        r = s * 0.2
        cx, cy = m + r, s / 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=w)
        draw.line([(cx + r, cy), (s - m, cy)], fill=color, width=w)
        draw.line([(s - m - w / 2, cy), (s - m - w / 2, cy + s * 0.16)], fill=color, width=w)
        draw.line([(s - m - s * 0.17, cy), (s - m - s * 0.17, cy + s * 0.12)], fill=color, width=w)
    elif name == "help":
        draw.ellipse((m, m, s - m, s - m), outline=color, width=w)
        c = s / 2
        draw.arc((c - s * .12, s * .3, c + s * .12, s * .52), 180, 90, fill=color, width=w)
        draw.line([(c, s * .52), (c, s * .58)], fill=color, width=w)
        draw.ellipse((c - w * .7, s * .67, c + w * .7, s * .67 + w * 1.4), fill=color)
    elif name == "empty-models":
        return line_icon(size, "models", color)
    elif name == "empty-keys":
        return line_icon(size, "keys", color)
    return image


def main():
    # Provider icons (openai*.png, claude*.png) come from the official logos in vendor/ (tile-*.svg).
    for name in ("overview", "models", "keys", "help"):
        save(line_icon(18, name, (139, 139, 153)), name, 18)
        save(line_icon(18, name, (237, 237, 242)), name + "-active", 18)
    for name in ("models", "keys"):
        image = tile(64, (28, 28, 36), 0.3)
        glyph = line_icon(36, name, (163, 155, 255))
        image.alpha_composite(glyph, (14 * SCALE, 14 * SCALE))
        save(image, "empty-" + name, 64)


if __name__ == "__main__":
    main()
