"""把題庫裡的一支腳本做成完整影片（全部使用免費工具）。

流程：edge-tts 旁白 → numpy 合成背景音樂 → Pillow 畫背景與縮圖 → ffmpeg 加字幕輸出 MP4。

用法：
    python -m yt_calm.make_video                 # 自動挑下一個還沒發布的主題
    python -m yt_calm.make_video --topic 002_anxiety
    python -m yt_calm.make_video --list          # 看題庫與發布狀態
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
TOPICS_DIR = ROOT / "topics"
PUBLISHED = ROOT / "published.json"
MASCOT_DIR = ROOT / "mascot" / "png"
MASCOT_H = 300  # 影片中吉祥物高度（像素）

SR = 44100
W, H = 1920, 1080
FPS = 24
INTRO = 5.0  # 片頭標題秒數
OUTRO = 6.0
LINE_GAP = 1.8  # 每句之間停頓
PAUSE = 5.0  # 腳本中空字串 "" 代表較長的停頓

VOICE = os.environ.get("YT_VOICE", "zh-TW-HsiaoChenNeural")
RATE = os.environ.get("YT_RATE", "-12%")
PITCH = os.environ.get("YT_PITCH", "-2Hz")


# ---------------------------------------------------------------- 題庫
def load_topics() -> list[dict]:
    return [json.loads(p.read_text("utf-8")) for p in sorted(TOPICS_DIR.glob("*.json"))]


def load_published() -> dict:
    if PUBLISHED.exists():
        return json.loads(PUBLISHED.read_text("utf-8"))
    return {}


def pick_topic(topic_id: str | None) -> dict:
    topics = load_topics()
    if topic_id:
        for t in topics:
            if t["id"] == topic_id:
                return t
        sys.exit(f"找不到主題 {topic_id}")
    done = load_published()
    for t in topics:
        if t["id"] not in done:
            return t
    sys.exit("題庫已經全部發布完了，請在 yt_calm/topics/ 新增腳本。")


# ---------------------------------------------------------------- 工具
def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def find_font() -> tuple[str, str]:
    """回傳 (字型檔路徑, 字型家族名)，優先 Noto Sans CJK TC。"""
    for family in ("Noto Sans CJK TC", "Noto Sans TC", "WenQuanYi Zen Hei"):
        out = subprocess.run(
            ["fc-match", "-f", "%{file}|%{family[0]}", f"{family}:style=Regular"],
            capture_output=True, text=True,
        ).stdout
        path, _, fam = out.partition("|")
        if path and family.split()[0].lower() in fam.lower():
            return path, fam
    sys.exit("找不到中文字型，請安裝 fonts-noto-cjk")


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def write_wav(path: Path, stereo: np.ndarray) -> None:
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- 旁白
async def _tts(text: str, out: Path) -> None:
    import edge_tts

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH, proxy=proxy)
    for attempt in range(4):
        try:
            await comm.save(str(out))
            return
        except Exception:  # 網路偶爾失敗就重試
            if attempt == 3:
                raise
            await asyncio.sleep(2 * (attempt + 1))


def build_voice(lines: list[str], work: Path) -> tuple[np.ndarray, list[tuple[float, float, str]]]:
    """回傳 (單聲道旁白, 字幕時間表)。時間已包含片頭。"""
    chunks = [np.zeros(int(INTRO * SR), np.float32)]
    cues = []
    t = INTRO
    for i, line in enumerate(lines):
        if not line.strip():
            chunks.append(np.zeros(int(PAUSE * SR), np.float32))
            t += PAUSE
            continue
        mp3 = work / f"l{i:03d}.mp3"
        wav = work / f"l{i:03d}.wav"
        asyncio.run(_tts(line, mp3))
        run(["ffmpeg", "-y", "-i", str(mp3), "-ac", "1", "-ar", str(SR), str(wav)])
        audio = read_wav(wav)
        # 去掉頭尾靜音，讓節奏由我們控制
        idx = np.flatnonzero(np.abs(audio) > 0.01)
        if idx.size:
            audio = audio[max(idx[0] - 800, 0): idx[-1] + 2000]
        dur = len(audio) / SR
        cues.append((t, t + dur, line))
        chunks.append(audio)
        chunks.append(np.zeros(int(LINE_GAP * SR), np.float32))
        t += dur + LINE_GAP
    chunks.append(np.zeros(int(OUTRO * SR), np.float32))
    return np.concatenate(chunks), cues


# ---------------------------------------------------------------- 背景音樂
def ambient_music(seconds: float, seed: int) -> np.ndarray:
    """柔和的環境音墊（自己合成，沒有版權問題）。回傳立體聲 (n, 2)。"""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    # 和弦（Hz）：Cmaj7 → Am7 → Fmaj7 → G6，低八度溫暖一點
    chords = [
        [130.81, 164.81, 196.00, 246.94],
        [110.00, 130.81, 164.81, 196.00],
        [87.31, 130.81, 174.61, 220.00],
        [98.00, 123.47, 146.83, 164.81],
    ]
    rng.shuffle(chords)
    chord_len = 12.0
    out = np.zeros((n, 2), np.float32)
    xfade = 4.0
    for k in range(int(math.ceil(seconds / chord_len)) + 1):
        start = k * chord_len - xfade
        s0, s1 = max(int(start * SR), 0), min(int((start + chord_len + 2 * xfade) * SR), n)
        if s0 >= s1:
            continue
        seg_t = t[s0:s1]
        local = seg_t - start
        span = chord_len + 2 * xfade
        env = np.clip(np.minimum(local / xfade, (span - local) / xfade), 0, 1)
        env = env * env * (3 - 2 * env)  # smoothstep
        for j, f in enumerate(chords[k % len(chords)]):
            for detune, pan in ((-0.6, 0.25), (0.6, 0.75)):
                ph = rng.uniform(0, 2 * np.pi)
                lfo = 0.75 + 0.25 * np.sin(2 * np.pi * (0.05 + 0.02 * j) * seg_t + ph)
                tone = np.sin(2 * np.pi * (f + detune) * seg_t + ph)
                tone += 0.25 * np.sin(2 * np.pi * 2 * (f + detune) * seg_t + ph)
                sig = (tone * lfo * env).astype(np.float32) * 0.05
                out[s0:s1, 0] += sig * (1 - pan)
                out[s0:s1, 1] += sig * pan
    # 一點點柔和的「空氣聲」（低通過的雜訊）
    noise = rng.standard_normal((n, 2)).astype(np.float32)
    kernel = np.ones(400, np.float32) / 400
    for c in range(2):
        noise[:, c] = np.convolve(noise[:, c], kernel, mode="same")
    out += noise * 0.08
    # 淡入淡出
    fade = int(4 * SR)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    out[:fade] *= ramp
    out[-fade:] *= ramp[::-1]
    return out / (np.abs(out).max() + 1e-9)


def mix_audio(voice: np.ndarray, seed: int) -> np.ndarray:
    music = ambient_music(len(voice) / SR, seed)
    v = voice / (np.abs(voice).max() + 1e-9) * 0.85
    # 有人聲時把音樂壓低（簡易 ducking）
    env = np.convolve(np.abs(v), np.ones(int(0.3 * SR)) / (0.3 * SR), mode="same")
    duck = 1 - 0.45 * np.clip(env / (env.max() + 1e-9) * 3, 0, 1)
    mixed = np.stack([v, v], axis=1) + music * 0.22 * duck[:, None]
    return mixed / max(1.0, np.abs(mixed).max() / 0.95)


# ---------------------------------------------------------------- 畫面
def make_background(palette: list[str], size: tuple[int, int], seed: int) -> Image.Image:
    rng = random.Random(seed)
    w, h = size
    c1, c2 = (np.array(hex_rgb(c), np.float32) for c in palette)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = np.clip((xx / w * 0.4 + yy / h * 0.8), 0, 1)[..., None]
    base = c1 * (1 - g) + c2 * g
    img = Image.fromarray(base.astype(np.uint8), "RGB")
    # 柔焦光點
    glow = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(glow)
    light = tuple(min(255, int(v * 1.6 + 60)) for v in c2)
    for _ in range(14):
        r = rng.randint(int(h * 0.05), int(h * 0.22))
        x, y = rng.randint(0, w), rng.randint(0, h)
        a = rng.uniform(0.15, 0.45)
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(v * a) for v in light))
    glow = glow.filter(ImageFilter.GaussianBlur(h * 0.06))
    img = Image.fromarray(np.clip(np.asarray(img, np.int16) + np.asarray(glow, np.int16), 0, 255).astype(np.uint8))
    # 暗角，讓字更清楚
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    vig = np.clip(1 - 0.35 * r ** 2, 0.55, 1)[..., None]
    return Image.fromarray((np.asarray(img, np.float32) * vig).astype(np.uint8))


def ass_time(s: float) -> str:
    cs = int(round(s * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(path: Path, topic: dict, cues: list[tuple[float, float, str]], total: float, family: str) -> None:
    title = topic["title"].split("｜")
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Line,{family},66,&H00FFFFFF,&H00FFFFFF,&H50000000,&H64000000,0,0,0,0,100,100,4,0,1,2,3,5,160,160,0,1
Style: Title,{family},96,&H00FFFFFF,&H00FFFFFF,&H50000000,&H64000000,1,0,0,0,100,100,6,0,1,2,4,5,120,120,0,1
Style: Sub,{family},46,&H30FFFFFF,&H00FFFFFF,&H50000000,&H64000000,0,0,0,0,100,100,4,0,1,1,2,5,120,120,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 0,{ass_time(0.3)},{ass_time(INTRO - 0.3)},Title,,0,0,0,,{{\\fad(800,700)\\pos({W // 2},{H // 2 - 50})}}{title[-1]}"]
    if len(title) > 1:
        ev.append(f"Dialogue: 0,{ass_time(0.8)},{ass_time(INTRO - 0.3)},Sub,,0,0,0,,{{\\fad(800,700)\\pos({W // 2},{H // 2 + 70})}}{title[0]}")
    for s, e, text in cues:
        ev.append(f"Dialogue: 0,{ass_time(s - 0.15)},{ass_time(e + 0.6)},Line,,0,0,0,,{{\\fad(350,450)}}{text}")
    end = cues[-1][1] + 1.5 if cues else INTRO
    ev.append(f"Dialogue: 0,{ass_time(end)},{ass_time(total - 0.5)},Sub,,0,0,0,,{{\\fad(800,1200)}}謝謝你的陪伴　🌙")
    path.write_text(head + "\n".join(ev) + "\n", "utf-8")


def load_mascot(name: str, height: int) -> Image.Image:
    im = Image.open(MASCOT_DIR / f"{name}.png").convert("RGBA")
    return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)


def make_thumbnail(bg: Image.Image, text: str, font_path: str, out: Path, pose: str) -> None:
    img = bg.resize((1280, 720), Image.LANCZOS).convert("RGBA")
    m = load_mascot(pose, 430)
    img.alpha_composite(m, (1280 - m.width - 30, 720 - m.height - 40))
    cx = (1280 - m.width) / 2 + 40  # 文字放在吉祥物左邊的空間置中
    lines = text.split("\n")
    size = 140 if max(len(l) for l in lines) <= 4 else 110
    font = ImageFont.truetype(font_path, size)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    total_h = len(lines) * size * 1.2
    y = (720 - total_h) / 2
    for l in lines:
        tw = d.textlength(l, font=font)
        x = cx - tw / 2
        d.text((x + 5, y + 6), l, font=font, fill=(0, 0, 0, 110))
        d.text((x, y), l, font=font, fill=(255, 255, 255, 255))
        y += size * 1.2
    shadow = layer.filter(ImageFilter.GaussianBlur(3))
    img = Image.alpha_composite(img, shadow)
    img = Image.alpha_composite(img, layer)
    img.convert("RGB").save(out, quality=92)


# ---------------------------------------------------------------- 主程式
def make(topic: dict, out_root: Path) -> Path:
    out = out_root / topic["id"]
    out.mkdir(parents=True, exist_ok=True)
    seed = sum(map(ord, topic["id"]))
    font_path, family = find_font()
    pose = topic.get("mascot", "calm")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        print(f"[1/4] 產生旁白（{VOICE}）…")
        voice, cues = build_voice(topic["lines"], work)
        total = len(voice) / SR
        print(f"[2/4] 合成背景音樂，總長 {total:.0f} 秒…")
        write_wav(work / "mix.wav", mix_audio(voice, seed))
        print("[3/4] 繪製背景與縮圖…")
        bg = make_background(topic["palette"], (int(W * 1.12), int(H * 1.12)), seed)
        bg.save(work / "bg.png")
        make_thumbnail(bg, topic.get("thumbnail_text", topic["title"]), font_path, out / "thumbnail.jpg", pose)
        load_mascot(pose, MASCOT_H).save(work / "m.png")
        load_mascot(f"{pose}_blink", MASCOT_H).save(work / "mb.png")
        write_ass(work / "subs.ass", topic, cues, total, family)
        print("[4/4] ffmpeg 輸出影片…")
        mx, my = int(W * 0.06), int(H * 0.06)
        # 吉祥物在右下角：慢慢「呼吸」上下浮動，每隔幾秒眨一次眼
        m_w = load_mascot(pose, MASCOT_H).width
        mxp, myp = W - m_w - 50, H - MASCOT_H - 30
        bob = f"{myp}+7*sin(2*PI*t/4.5)"
        fc = (
            f"[0:v]crop={W}:{H}:x='{mx}+{mx}*sin(2*PI*t/70)':y='{my}+{my}*cos(2*PI*t/53)'[bg];"
            f"[bg][1:v]overlay=x={mxp}:y='{bob}'[a];"
            f"[a][2:v]overlay=x={mxp}:y='{bob}':enable='lt(mod(t,5.3),0.18)'[b];"
            f"[b]ass={work / 'subs.ass'}:fontsdir={Path(font_path).parent},"
            f"fade=in:st=0:d=1.5,fade=out:st={total - 2.5:.2f}:d=2.5,format=yuv420p[v]"
        )
        run([
            "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(work / "bg.png"),
            "-loop", "1", "-framerate", str(FPS), "-i", str(work / "m.png"),
            "-loop", "1", "-framerate", str(FPS), "-i", str(work / "mb.png"),
            "-i", str(work / "mix.wav"), "-filter_complex", fc, "-map", "[v]", "-map", "3:a",
            "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out / "video.mp4"),
        ])
    desc = topic["description"] + (
        "\n\n🎧 建議戴上耳機，在安靜的地方收聽。"
        "\n\n本影片旁白為 AI 合成語音，背景音樂為程式合成之原創音樂。"
        "\n\n#" + " #".join(topic["tags"][:3])
    )
    meta = {"id": topic["id"], "title": topic["title"], "description": desc, "tags": topic["tags"]}
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    print(f"完成：{out}/video.mp4（{total / 60:.1f} 分鐘）")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--out", default="out/yt_calm")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("需要安裝 ffmpeg")
    if a.list:
        done = load_published()
        for t in load_topics():
            print(("✅ " if t["id"] in done else "⬜ ") + t["id"], t["title"])
        return
    out = make(pick_topic(a.topic), Path(a.out))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"dir={out}\n")


if __name__ == "__main__":
    main()
