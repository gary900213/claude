"""用吉祥物產生頻道頭像與橫幅。

    python -m yt_calm.mascot.branding
輸出到 yt_calm/mascot/branding/
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from yt_calm.make_video import find_font, load_mascot, make_background

OUT = Path(__file__).resolve().parent / "branding"
CHANNEL = "暖糰的心情小站"
TAGLINE = "累了，就來這裡休息一下"
PALETTE = ["#f3d9c6", "#c9b6e4"]


def avatar() -> None:
    img = make_background(PALETTE, (800, 800), 7).convert("RGBA")
    m = load_mascot("happy", 560)
    img.alpha_composite(m, ((800 - m.width) // 2, 140))
    img.convert("RGB").save(OUT / "avatar_800.png")


def banner(font_path: str) -> None:
    W, H = 2560, 1440
    img = make_background(PALETTE, (W, H), 11).convert("RGBA")
    m = load_mascot("wave", 400)
    # YouTube 在所有裝置都會顯示的安全區：中間 1546 x 423
    sx, sy = (W - 1546) // 2, (H - 423) // 2
    img.alpha_composite(m, (sx + 40, sy + 10))
    d = ImageDraw.Draw(img)
    tx = sx + 40 + m.width + 50
    d.text((tx, sy + 90), CHANNEL, font=ImageFont.truetype(font_path, 120), fill=(90, 64, 56))
    d.text((tx + 6, sy + 250), TAGLINE, font=ImageFont.truetype(font_path, 62), fill=(120, 96, 110))
    img.convert("RGB").save(OUT / "banner_2560x1440.png")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    font, _ = find_font()
    avatar()
    banner(font)
    print("ok", sorted(p.name for p in OUT.iterdir()))
