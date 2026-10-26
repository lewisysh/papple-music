"""Draw the DMG window background (1x and @2x) for scripts/build-macapp.sh.

Run with: uv run --no-project --with pillow --with numpy python packaging/macos/dmg/make-background.py
Layout (points): 640x420 window, app icon centred at (165, 205), Applications at (475, 205).
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
W, H = 640, 420
APP, APPS = (165, 205), (475, 205)
RED = (250, 45, 72)

DISPLAY = "/Library/Fonts/SF-Pro-Display-Bold.otf"
TEXT = "/System/Library/Fonts/SFNS.ttf"
KOREAN = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def font(path: str, size: float, index: int = 0) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, round(size), index=index)
    except OSError:
        return ImageFont.truetype(TEXT, round(size))


def draw(scale: int) -> Image.Image:
    s = lambda v: round(v * scale)
    img = Image.new("RGB", (s(W), s(H)))
    top, bottom = (252, 249, 247), (240, 233, 229)
    px = img.load()
    for y in range(s(H)):
        t = y / (s(H) - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(s(W)):
            px[x, y] = row

    # Soft glows: red behind the app, a hint of pear green behind Applications.
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for (cx, cy), color, r in ((APP, (*RED, 46), 120), (APPS, (140, 190, 90, 30), 110)):
        g.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(s(60)))
    img = Image.alpha_composite(img.convert("RGBA"), glow)

    d = ImageDraw.Draw(img)
    # Title
    title = font(DISPLAY, s(26))
    d.text((s(W / 2), s(52)), "Papple Music", font=title, fill=(29, 29, 31), anchor="mm")
    tag = font(TEXT, s(10.5))
    text = "ENHANCED DOWNLOADER"
    spacing = s(2.2)
    widths = [d.textlength(ch, font=tag) for ch in text]
    x = s(W / 2) - (sum(widths) + spacing * (len(text) - 1)) / 2
    for ch, w in zip(text, widths):
        d.text((x, s(78)), ch, font=tag, fill=RED, anchor="lm")
        x += w + spacing

    # Arrow from the app to Applications: a shallow arc with a rounded head.
    x0, x1, y = APP[0] + 78, APPS[0] - 78, APP[1] - 6
    pts = []
    for i in range(41):
        t = i / 40
        pts.append((s(x0 + (x1 - x0) * t), s(y - math.sin(math.pi * t) * 12)))
    arrow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    a = ImageDraw.Draw(arrow)
    a.line(pts, fill=(*RED, 230), width=s(3.2), joint="curve")
    for px_, py_ in (pts[0], pts[-1]):
        r = s(1.6)
        a.ellipse([px_ - r, py_ - r, px_ + r, py_ + r], fill=(*RED, 230))
    # Chevron head, aimed a little flatter than the arc's final tangent.
    ex, ey = pts[-1]
    ang = math.atan2(pts[-1][1] - pts[-12][1], pts[-1][0] - pts[-12][0])
    head = [(ex - math.cos(ang + side * 0.62) * s(12), ey - math.sin(ang + side * 0.62) * s(12)) for side in (-1, 1)]
    a.line([head[0], (ex, ey), head[1]], fill=(*RED, 230), width=s(3.2), joint="curve")
    for hx, hy in head:
        a.ellipse([hx - s(1.6), hy - s(1.6), hx + s(1.6), hy + s(1.6)], fill=(*RED, 230))
    img = Image.alpha_composite(img, arrow)

    # Instructions under the icons and their labels.
    d = ImageDraw.Draw(img)
    d.text((s(W / 2), s(342)), "Papple Music을 Applications 폴더로 끌어다 놓으세요",
           font=font(KOREAN, s(13), index=2), fill=(80, 76, 74), anchor="mm")
    d.text((s(W / 2), s(364)), "Drag Papple Music onto Applications to install",
           font=font(TEXT, s(12)), fill=(134, 128, 125), anchor="mm")
    # A touch of noise so the soft glows don't band.
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    arr += np.random.default_rng(7).uniform(-1.5, 1.5, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


if __name__ == "__main__":
    draw(1).save(HERE / "background.png", optimize=True)
    draw(2).save(HERE / "background@2x.png", optimize=True)
    print("wrote", HERE / "background.png", HERE / "background@2x.png")
