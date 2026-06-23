#!/usr/bin/env python
"""Generate the 8 base-state diamond images used by the at-bat cards.

Build-time only — requires Pillow (not a runtime dependency of the bot). The
bot ships the resulting PNGs and attaches them; it never imports Pillow.

    venv/bin/python scripts/gen_base_images.py

Writes BaseballConsumer/assets/bases/bases_{1st}{2nd}{3rd}.png for all 8
combinations, where each digit is 1 (runner on) or 0 (empty).
"""
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'BaseballConsumer', 'assets', 'bases')

SS = 4                      # supersample factor for smooth edges
SIZE = 180                  # final image size (px)
# The diamond is drawn small inside a larger transparent square so it renders
# compact in Discord's fixed-size thumbnail box. RADIUS_FRAC is the distance
# from center to each base as a fraction of the canvas (diamond spans 2x that).
RADIUS_FRAC = 0.18
BASE_FRAC = 0.055           # base marker half-width as a fraction of the canvas

OCCUPIED = (235, 110, 31, 255)   # Astros orange
OCCUPIED_EDGE = (150, 66, 12, 255)
EMPTY_FILL = (255, 255, 255, 0)  # transparent
EMPTY_EDGE = (140, 140, 140, 255)
PATH = (140, 140, 140, 255)
HOME = (200, 200, 200, 255)


def _diamond(cx, cy, half):
    return [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)]


def render(first, second, third):
    s = SIZE * SS
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx = cy = s // 2
    r = int(s * RADIUS_FRAC)
    half = int(s * BASE_FRAC)
    width = max(2, int(s * 0.008))
    # 2B top, 1B right, 3B left, home bottom.
    pts = {
        'second': (cx, cy - r),
        'first': (cx + r, cy),
        'third': (cx - r, cy),
        'home': (cx, cy + r),
    }

    # Base paths first, so bases sit on top.
    order = ['home', 'first', 'second', 'third', 'home']
    d.line([pts[k] for k in order], fill=PATH, width=width)

    # Home plate — a small neutral marker (not a runner base).
    hp = pts['home']
    d.polygon(_diamond(hp[0], hp[1], int(half * 0.7)), outline=HOME, width=width)

    for key, occupied in (('first', first), ('second', second), ('third', third)):
        cxy = pts[key]
        poly = _diamond(cxy[0], cxy[1], half)
        if occupied:
            d.polygon(poly, fill=OCCUPIED, outline=OCCUPIED_EDGE, width=width)
        else:
            d.polygon(poly, fill=EMPTY_FILL, outline=EMPTY_EDGE, width=width)

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for first in (0, 1):
        for second in (0, 1):
            for third in (0, 1):
                img = render(first, second, third)
                name = 'bases_{}{}{}.png'.format(first, second, third)
                img.save(os.path.join(OUT_DIR, name))
                print('wrote', name)


if __name__ == '__main__':
    main()
