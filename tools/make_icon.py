"""Generates ui/3dsort.ico, the app icon.

An SD card seen from the front, with the HOME menu grid on it: the whole app in
one shape. Drawn at 4x and downsampled so the small sizes stay clean, and the
16px layer is drawn separately because the grid turns to mush below 32px.

    python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "ui" / "3dsort.ico"
SIZES = [256, 128, 64, 48, 32, 16]

RED = (211, 30, 64, 255)        # --red
RED_DARK = (168, 21, 50, 255)   # --red2
CREAM = (253, 245, 232, 255)    # --bg
CARD = (255, 253, 248, 255)     # --card
GOLD = (214, 168, 61, 255)      # contact pads
INK = (74, 63, 53, 255)         # --ink


def rr(d, box, r, fill, outline=None, w=0):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)


def draw_card(px):
    """The full icon: red SD card body, cut corner, gold pads, tile grid."""
    s = px * 4                      # supersample
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 64.0                    # design grid unit (icon designed on 64x64)

    # card body: an SD card is notched on its top LEFT corner
    left, top, right, bottom = 6 * u, 3 * u, 58 * u, 61 * u
    cut = 11 * u
    body = [(left + cut, top), (right, top), (right, bottom), (left, bottom),
            (left, top + cut)]
    d.polygon(body, fill=RED)
    # bevel: a darker edge on the cut reads as plastic, not a flat blob
    d.line([(left, top + cut), (left + cut, top)],
           fill=RED_DARK, width=max(1, int(u)))

    # gold contact pads along the top right
    for i in range(4):
        x = right - (5 + i * 5.2) * u
        rr(d, [x, top + 2.5 * u, x + 3.2 * u, top + 8.5 * u], u * 0.8, GOLD)

    # label area: the HOME menu grid
    gx0, gy0 = left + 4 * u, top + 13 * u
    gw, gh = (right - left) - 8 * u, (bottom - top) - 19 * u
    rr(d, [gx0, gy0, gx0 + gw, gy0 + gh], 3 * u, CREAM)

    cols, rows = 4, 3
    pad = 1.6 * u
    tw = (gw - pad * (cols + 1)) / cols
    th = (gh - pad * (rows + 1)) / rows
    # one tile is red: the icon you just moved. That is what the app does.
    accent = (1, 1)
    for r_i in range(rows):
        for c_i in range(cols):
            x = gx0 + pad + c_i * (tw + pad)
            y = gy0 + pad + r_i * (th + pad)
            fill = RED if (c_i, r_i) == accent else CARD
            rr(d, [x, y, x + tw, y + th], tw * 0.28, fill,
               outline=INK if (c_i, r_i) != accent else None,
               w=max(1, int(u * 0.5)) if (c_i, r_i) != accent else 0)

    return img.resize((px, px), Image.LANCZOS)


def draw_small():
    """16px: card silhouette, a 2x2 grid and one red tile. Full detail smears."""
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 16.0
    left, top, right, bottom = 1 * u, 0.5 * u, 15 * u, 15.5 * u
    cut = 4 * u
    d.polygon([(left + cut, top), (right, top), (right, bottom), (left, bottom),
               (left, top + cut)], fill=RED)
    gx0, gy0, gx1, gy1 = left + 1.6 * u, top + 4.5 * u, right - 1.6 * u, bottom - 1.6 * u
    rr(d, [gx0, gy0, gx1, gy1], u, CREAM)
    tw = (gx1 - gx0 - 1.5 * u) / 2
    for i in range(2):
        for j in range(2):
            x = gx0 + 0.5 * u + i * (tw + 0.5 * u)
            y = gy0 + 0.5 * u + j * (tw + 0.5 * u)
            rr(d, [x, y, x + tw, y + tw], tw * 0.3,
               RED if (i, j) == (0, 0) else CARD,
               outline=None if (i, j) == (0, 0) else INK,
               w=0 if (i, j) == (0, 0) else max(1, int(u * 0.35)))
    return img.resize((16, 16), Image.LANCZOS)


def main():
    layers = [draw_small() if px == 16 else draw_card(px) for px in SIZES]
    layers[0].save(OUT, format="ICO",
                   sizes=[(px, px) for px in SIZES], append_images=layers[1:])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, sizes {SIZES})")


if __name__ == "__main__":
    main()
