"""Inline fixture probe — measures classifier stats for each fixture
shape so we can pick clean separation thresholds.  Discarded after use.
"""
import io
import numpy as np
from PIL import Image, ImageDraw
import image_intelligence as ii


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def dark_ide():
    img = Image.new("RGB", (1200, 720), (18, 22, 28))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(42)
    y = 12
    while y < 708:
        length = int(rng.integers(low=300, high=1140))
        d.rectangle([20, y, 20 + length, y + 4], fill=(220, 220, 230))
        y += 18
    return img


def light_ide():
    img = Image.new("RGB", (1200, 720), (250, 250, 252))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(7)
    y = 12
    while y < 708:
        length = int(rng.integers(low=240, high=1120))
        d.rectangle([24, y, 24 + length, y + 3], fill=(20, 20, 28))
        y += 16
    return img


def ui_mockup():
    img = Image.new("RGB", (1200, 800), (245, 246, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 200, 800], fill=(25, 28, 38))
    for i in range(8):
        ny = 80 + i * 60
        d.rectangle([20, ny, 36, ny + 28], fill=(80, 200, 160))
        d.rectangle([48, ny + 8, 180, ny + 18], fill=(170, 175, 200))
    d.rectangle([200, 0, 1200, 60], fill=(255, 255, 255))
    d.rectangle([220, 22, 320, 38], fill=(80, 100, 240))
    d.rectangle([880, 18, 970, 42], fill=(80, 200, 160))
    d.rectangle([980, 18, 1070, 42], fill=(240, 100, 100))
    d.rectangle([1080, 18, 1170, 42], fill=(60, 80, 220))
    for row in range(2):
        for col in range(3):
            x = 240 + col * 280
            y = 100 + row * 220
            d.rectangle([x, y, x + 240, y + 180], fill=(255, 255, 255), outline=(180, 185, 200))
            d.rectangle([x + 16, y + 16, x + 100, y + 36], fill=(80, 200, 160))
            for i in range(5):
                ty = y + 50 + i * 16
                d.rectangle([x + 16, ty, x + 220, ty + 6], fill=(60, 70, 90))
            d.rectangle([x + 16, y + 150, x +  90, y + 168], fill=(60, 80, 220))
            d.rectangle([x + 100, y + 150, x + 170, y + 168], fill=(220, 100, 100))
    return img


for name, fn in [("dark_ide", dark_ide), ("light_ide", light_ide), ("ui_mockup", ui_mockup)]:
    img = fn()
    s = ii._stats(img)
    print(f"{name:12s}  sat={s['saturation']:6.2f}  bright={s['mean_brightness']:7.2f}  edges={s['edge_density']:6.2f}  rhythm={s['horizontal_rhythm']:6.2f}  nb={s['near_black']:.3f}  nw={s['near_white']:.3f}  classify={ii.classify_content(img)}")
