"""頻道吉祥物「暖糰」：一顆頭上長著小嫩芽的麻糬精靈。

產生各種表情／動作的 SVG，並用 Playwright（Chromium）轉成透明背景 PNG。
PNG 會一起 commit 進 repo，所以 GitHub Actions 不需要再跑這支程式。

    python -m yt_calm.mascot.draw
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "png"

INK = "#5a4038"
BODY = "#fff6ea"
BODY_SHADE = "#ffe2c8"
BLUSH = "#ffaaa8"
LEAF = "#8fc58a"
LEAF_DARK = "#5f9a63"
HEART = "#ff8fa3"

DEFS = f"""
<defs>
  <radialGradient id="body" cx="45%" cy="35%" r="75%">
    <stop offset="0%" stop-color="#ffffff"/>
    <stop offset="55%" stop-color="{BODY}"/>
    <stop offset="100%" stop-color="{BODY_SHADE}"/>
  </radialGradient>
  <linearGradient id="leaf" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#b6e0a8"/>
    <stop offset="100%" stop-color="{LEAF}"/>
  </linearGradient>
</defs>"""

STROKE = f'stroke="{INK}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"'


def sprout() -> str:
    return f"""
  <path d="M200 128 C 198 110, 200 98, 204 86" fill="none" {STROKE}/>
  <path d="M203 94 C 188 70, 160 66, 146 76 C 156 96, 184 104, 203 94 Z" fill="url(#leaf)" {STROKE}/>
  <path d="M204 88 C 214 64, 244 56, 258 66 C 250 88, 224 98, 204 88 Z" fill="url(#leaf)" {STROKE}/>
  <path d="M168 81 C 180 86, 190 90, 200 92" fill="none" stroke="{LEAF_DARK}" stroke-width="3" stroke-linecap="round"/>
  <path d="M236 70 C 226 76, 216 82, 207 87" fill="none" stroke="{LEAF_DARK}" stroke-width="3" stroke-linecap="round"/>"""


def body() -> str:
    return f"""
  <ellipse cx="200" cy="362" rx="118" ry="13" fill="#000" opacity="0.10"/>
  <ellipse cx="158" cy="346" rx="28" ry="15" fill="{BODY_SHADE}" {STROKE}/>
  <ellipse cx="242" cy="346" rx="28" ry="15" fill="{BODY_SHADE}" {STROKE}/>
  <path d="M68 262 C 68 168, 126 124, 200 124 C 274 124, 332 168, 332 262
           C 332 322, 282 350, 200 350 C 118 350, 68 322, 68 262 Z"
        fill="url(#body)" {STROKE}/>
  <ellipse cx="150" cy="170" rx="34" ry="16" fill="#fff" opacity="0.85" transform="rotate(-20 150 170)"/>"""


def eyes(kind: str) -> str:
    if kind == "open":
        e = ""
        for x in (158, 242):
            e += f'<ellipse cx="{x}" cy="240" rx="12" ry="15" fill="{INK}"/>'
            e += f'<circle cx="{x - 4}" cy="234" r="4.5" fill="#fff"/>'
        return e
    if kind == "happy":  # ^ ^
        return "".join(
            f'<path d="M{x - 13} 245 Q{x} 228 {x + 13} 245" fill="none" {STROKE}/>' for x in (158, 242)
        )
    # closed：平靜地閉眼 ︶ ︶
    return "".join(
        f'<path d="M{x - 13} 237 Q{x} 250 {x + 13} 237" fill="none" {STROKE}/>' for x in (158, 242)
    )


def face(eye_kind: str, mouth: str = "w") -> str:
    m = {
        "w": f'<path d="M186 266 Q193 275 200 267 Q207 275 214 266" fill="none" {STROKE} stroke-width="5"/>',
        "o": f'<ellipse cx="200" cy="270" rx="6" ry="5" fill="{INK}"/>',
        "smile": f'<path d="M186 264 Q200 280 214 264" fill="none" {STROKE} stroke-width="5"/>',
    }[mouth]
    return (
        eyes(eye_kind)
        + f'<ellipse cx="128" cy="270" rx="21" ry="11" fill="{BLUSH}" opacity="0.75"/>'
        + f'<ellipse cx="272" cy="270" rx="21" ry="11" fill="{BLUSH}" opacity="0.75"/>'
        + m
    )


def arms(pose: str) -> str:
    a = lambda cx, cy, rot: f'<ellipse cx="{cx}" cy="{cy}" rx="17" ry="25" fill="{BODY}" {STROKE} transform="rotate({rot} {cx} {cy})"/>'
    if pose == "wave":
        return a(80, 285, 25) + a(338, 200, -35) + (
            f'<path d="M362 160 q10 -8 18 -2" fill="none" {STROKE} stroke-width="4"/>'
            f'<path d="M372 182 q12 -2 16 6" fill="none" {STROKE} stroke-width="4"/>'
        )
    if pose == "hug":
        heart = (
            f'<path d="M200 330 C 170 308, 158 292, 160 278 C 162 262, 186 258, 200 276 '
            f'C 214 258, 238 262, 240 278 C 242 292, 230 308, 200 330 Z" fill="{HEART}" {STROKE} stroke-width="6"/>'
            f'<ellipse cx="183" cy="281" rx="7" ry="4" fill="#fff" opacity="0.8" transform="rotate(-30 183 281)"/>'
        )
        return heart + a(158, 300, -50) + a(242, 300, 50)
    return a(80, 288, 25) + a(320, 288, -25)


def zzz() -> str:
    return "".join(
        f'<text x="{x}" y="{y}" font-family="Arial Rounded MT Bold, Arial, sans-serif" font-weight="900" '
        f'font-size="{s}" fill="#9db3e0" stroke="{INK}" stroke-width="3" paint-order="stroke">z</text>'
        for x, y, s in ((300, 140, 34), (330, 105, 44), (365, 62, 56))
    )


def svg(pose: str, eye_kind: str, mouth: str = "w", extra: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="20 0 400 380" width="800" height="760">'
        f"{DEFS}{body()}{sprout()}{face(eye_kind, mouth)}{arms(pose)}{extra}</svg>"
    )


# 名稱 → SVG。每個動作有「睜眼」和「眨眼」兩張，影片裡交替做眨眼動畫
VARIANTS = {
    "calm": svg("rest", "open"),
    "calm_blink": svg("rest", "closed"),
    "hug": svg("hug", "open"),
    "hug_blink": svg("hug", "closed"),
    "wave": svg("wave", "happy", "smile"),
    "wave_blink": svg("wave", "happy", "smile"),
    "sleep": svg("rest", "closed", "o", zzz()),
    "sleep_blink": svg("rest", "closed", "o", zzz()),
    "happy": svg("rest", "happy", "smile"),
}

RENDER_JS = r"""
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [inDir, outDir] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 800, height: 760 } });
  for (const f of fs.readdirSync(inDir).filter(f => f.endsWith('.svg'))) {
    await p.setContent(`<html><body style="margin:0;background:transparent">${fs.readFileSync(inDir + '/' + f, 'utf8')}</body></html>`);
    await p.locator('svg').screenshot({ path: `${outDir}/${f.replace('.svg', '.png')}`, omitBackground: true });
  }
  await b.close();
})();
"""


def main() -> None:
    svg_dir = HERE / "svg"
    svg_dir.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    for name, s in VARIANTS.items():
        (svg_dir / f"{name}.svg").write_text(s, "utf-8")
    js = HERE / "_render.js"
    js.write_text(RENDER_JS)
    try:
        subprocess.run(["node", str(js), str(svg_dir), str(OUT)], check=True)
    finally:
        js.unlink()
    print(json.dumps(sorted(p.name for p in OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
