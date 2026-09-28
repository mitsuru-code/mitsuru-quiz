"""マルコ・ポーロ物語（約2分）を、絵巻画像をカメラでたどる動画にするスクリプト。

使い方（詳しくは PC手順.md）:
    pip install -r requirements.txt
    python make_video.py              # out/marco_polo_YYYYMMDD_HHMM.mp4 を出力（1920x1080 / 30fps / ナレーション・BGM・字幕付き）
    python make_video.py --preview    # 各場面の中間フレームを preview_NN.png に出力（音声は長さだけ推定、API不要）

素材:
    - scroll.jpg: 絵巻風の元画像（生成AI画像）。場面ごとに一部を切り出して映す
    - scenes/NN.png（任意）: 場面 NN の差し替え画像。置くとその場面は切り出しの代わりにこの画像を映す
      （素材プロンプト.md の画像を生成して置けば、その場面だけ高精細になる）
    - ナレーション音声: Gemini API の音声生成（TTS）。キーは環境変数 GEMINI_API_KEY か .env に書く
      合成結果は .cache/ に保存し、同じ文面・声なら API を再度呼ばない
"""
import base64
import glob
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    """このフォルダの .env（KEY=VALUE 形式）を環境変数に取り込む。既存の環境変数が優先"""
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as fp:
        for line in fp:
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()
CACHE = os.path.join(HERE, ".cache")
OUT_DIR = os.environ.get("VIDEO_OUT_DIR") or os.path.join(HERE, "out")  # Googleドライブ等の同期フォルダも指定可
TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Charon")
TTS_STYLE = os.environ.get("GEMINI_TTS_STYLE", "歴史ドキュメンタリーのナレーターとして、落ち着いた温かい声で、ゆっくり自然な間をとって読んでください")
TTS_SR = 24000  # Gemini TTS の出力は 24kHz / 16bit / モノラル PCM
SRC = os.path.join(HERE, "scroll.jpg")
W, H, FPS, SR = 1920, 1080, 30, 44100
LEAD, GAP, TAIL = 0.8, 1.6, 3.0  # 各場面の話し始めまでの間・話し終わり後の間・最後の余韻（秒）
XFADE = 0.6  # 場面切り替えのクロスフェード（秒）
REF_W, REF_H = 1408, 768  # カメラ座標の基準サイズ（元画像のピクセル）

# (見出し, 字幕, 読み上げ, カメラ[(区間内の割合, cx, cy, 横幅px)])
# 字幕と読み上げを分けているのは Open JTalk の読み誤り対策（日本→にほん 等）
# カメラ座標は元画像 1408x768 のピクセル。None は場面専用の演出（タイトル・ジパング）
SCENES = [
    ("", "マルコ・ポーロ物語", "マルコ・ポーロ物語。ヴェネツィアの商人が見た、東方の世界。",
     [(0.0, 704, 384, 1408), (1.0, 704, 384, 1250)]),
    ("1271年 ヴェネツィア", "1271年、17歳のマルコ・ポーロは、商人の父と叔父とともにヴェネツィアを旅立ちました",
     "千二百七十一年、十七歳のマルコ・ポーロは、商人の父と叔父とともに、ヴェネツィアを旅立ちました。",
     [(0.0, 1285, 150, 400), (1.0, 1265, 150, 330)]),
    ("目的地は大ハーンの国", "目指すはモンゴル帝国の皇帝フビライ・ハンの国。ローマ教皇の手紙を届ける旅でした",
     "目指すは、モンゴル帝国の皇帝、フビライ・ハンの国。ローマ教皇の手紙を届ける旅でした。",
     [(0.0, 180, 150, 330), (1.0, 290, 150, 360)]),
    ("シルクロードの難路", "ペルシャを抜け、パミールの山々や砂漠のふちを越える旅は3年半におよびました",
     "ペルシャを抜け、パミールの山々や、砂漠のふちを越える旅は、三年半におよびました。",
     [(0.0, 960, 150, 400), (1.0, 1085, 160, 340)]),
    ("草原の民との出会い", "道中では、草原に生きる遊牧民や、ラクダの隊商と出会います",
     "道中では、草原に生きる遊牧民や、ラクダの隊商と出会います。",
     [(0.0, 950, 640, 330), (1.0, 1120, 640, 360)]),
    ("1275年 元の都・上都", "1275年、一行はついに元の夏の都「上都」に到着します",
     "千二百七十五年、一行はついに、げんの夏の都、じょうとに到着します。",
     [(0.0, 640, 150, 380), (1.0, 760, 155, 340)]),
    ("大ハーンに仕える", "フビライ・ハンは、語学に優れた若いマルコを気に入り、そばに仕えさせました",
     "フビライ・ハンは、語学にすぐれた若いマルコを気に入り、そばに仕えさせました。",
     [(0.0, 700, 395, 420), (1.0, 700, 355, 250)]),
    ("中国各地への使節", "マルコは使節として各地をめぐり、紙のお金や燃える黒い石（石炭）など、驚きを記録します",
     "マルコは使節として各地をめぐり、紙のお金や、燃える黒い石など、ヨーロッパにない驚きを記録します。",
     [(0.0, 440, 640, 380), (1.0, 610, 640, 380)]),
    ("1292年 海路で帰国へ", "滞在は17年。モンゴルの姫をペルシャへ送り届ける役目を得て、船で帰路につきます",
     "滞在は十七年。モンゴルの姫を、ペルシャへ送り届ける役目を得て、船で帰路につきます。",
     [(0.0, 300, 395, 400), (1.0, 400, 395, 360)]),
    ("1295年 24年ぶりの帰郷", "1295年、24年ぶりにヴェネツィアへ。変わり果てた姿に家族も気づかなかったといいます",
     "千二百九十五年、二十四年ぶりに、ヴェネツィアへ。変わり果てた姿に、家族も気づかなかったといいます。",
     [(0.0, 275, 640, 330), (1.0, 265, 630, 280)]),
    ("牢獄で生まれた本", "ジェノヴァとの戦いで捕虜になり、牢獄で作家ルスティケッロに旅を語る。これが『東方見聞録』です",
     "ジェノヴァとの戦いで捕虜になり、牢獄で作家ルスティケッロに旅を語ります。これが、東方見聞録です。",
     [(0.0, 125, 640, 320), (1.0, 115, 625, 250)]),
    ("黄金の国ジパング", "本の中で日本は「黄金の国ジパング」と紹介されました。ただしマルコは日本には来ていません",
     "本の中で、にほんは、黄金の国ジパングと紹介されました。ただし、マルコは、にほんには来ていません。",
     None),
    ("世界を動かした旅", "『東方見聞録』は、のちにコロンブスをはじめ多くの探検家の心を動かしました",
     "東方見聞録は、のちに、コロンブスをはじめ、多くの探検家の心を動かしました。",
     [(0.0, 1270, 420, 380), (0.45, 1270, 420, 360), (1.0, 704, 384, 1408)]),
]

C_INK = (40, 26, 14)
C_PAPER = (243, 231, 204)
C_GOLD = (226, 184, 92)


# ---------------------------------------------------------------- 共通
def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def find_font(mincho=False):
    pats = (["*ipamp*", "*ipam.*", "*NotoSerifCJK*", "*yumin*", "*msmincho*"] if mincho else [])
    pats += ["*ipagp*", "*ipag.*", "*NotoSansCJK*", "*BIZ-UDGothic*", "*meiryo*", "*YuGoth*", "*msgothic*"]
    dirs = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"), "C:/Windows/Fonts"]
    for p in pats:
        for d in dirs:
            hit = glob.glob(os.path.join(d, "**", p), recursive=True)
            if hit:
                return sorted(hit)[0]
    sys.exit("日本語フォントが見つかりません（IPAフォント等を入れてください）")


FONT = find_font()
FONT_M = find_font(mincho=True)


def font(size, mincho=False):
    return ImageFont.truetype(FONT_M if mincho else FONT, size)


# ---------------------------------------------------------------- 音声
def _post_voice(x):
    """前後の無音を詰め、低域のこもりを取り、発話ごとの音量をそろえる"""
    from scipy.signal import butter, sosfiltfilt

    idx = np.where(np.abs(x) > 0.01)[0]
    if len(idx):
        x = x[max(idx[0] - int(0.02 * SR), 0): idx[-1] + int(0.15 * SR)]
    x = sosfiltfilt(butter(2, 70, "high", fs=SR, output="sos"), x)
    rms = np.sqrt(np.mean(x[np.abs(x) > np.abs(x).max() * 0.05] ** 2)) + 1e-9
    x = np.tanh(x / rms * 0.16 * 1.4) / 1.4
    fade = int(0.02 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade * 4:] *= np.linspace(1, 0, fade * 4)
    return x


def gemini_tts(text):
    """Gemini API で1場面分を合成し、SR Hz の float 配列を返す（.cache に保存して再利用）"""
    from scipy.signal import resample_poly

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY が未設定です（.env を確認。--preview なら API なしで画面だけ確認できます）")
    os.makedirs(CACHE, exist_ok=True)
    h = hashlib.sha1(f"{TTS_MODEL}|{TTS_VOICE}|{TTS_STYLE}|{text}".encode()).hexdigest()[:16]
    path = os.path.join(CACHE, f"gemini_{h}.pcm")
    if not os.path.exists(path):
        body = json.dumps({
            "contents": [{"parts": [{"text": f"{TTS_STYLE}：\n{text}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": TTS_VOICE}}},
            },
        }).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent"
        for attempt in range(4):  # 無料枠の回数制限(429)や一時的な失敗に備えて待って再試行
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                  "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    res = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 503) or attempt == 3:
                    sys.exit(f"Gemini TTS エラー HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
                wait = 20 * (attempt + 1)
                print(f"HTTP {e.code}: {wait}秒待って再試行します", flush=True)
                time.sleep(wait)
        data = res["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        with open(path, "wb") as fp:
            fp.write(base64.b64decode(data))
    with open(path, "rb") as fp:
        pcm = np.frombuffer(fp.read(), dtype="<i2").astype(np.float64) / 32768
    return _post_voice(resample_poly(pcm, 147, 80))  # 24000 → 44100 Hz


def voices(dry):
    """場面ごとの読み上げ音声（float, SR Hz）。dry=True なら文字数から長さを推定した無音"""
    if dry:
        return [np.zeros(int(len(s[2]) / 7.0 * SR)) for s in SCENES]
    out = []
    for i, (_, _, text, _) in enumerate(SCENES):
        print(f"voice {i:02d}/{len(SCENES) - 1:02d}", flush=True)
        out.append(gemini_tts(text))
    return out


def bgm(n):
    """絹の道っぽいドリアンのドローン＋ゆっくりしたアルペジオ（D ドリアン）"""
    tt = np.arange(n) / SR
    out = np.zeros((n, 2))
    drone = sum(np.sin(2 * np.pi * f * tt + k) * g for k, (f, g) in enumerate([(73.4, 1), (110, 0.6), (146.8, 0.5)]))
    drone *= 0.55 + 0.45 * np.sin(2 * np.pi * tt / 11.0) ** 2
    out += drone[:, None] * 0.05
    scale = [293.7, 329.6, 349.2, 392.0, 440.0, 493.9, 523.3, 587.3]
    rng = np.random.default_rng(5)
    t, i = 1.0, 0
    while t < n / SR - 2:
        f = scale[[0, 2, 4, 3, 1, 4, 5, 7, 4, 2, 3, 0][i % 12]] * (0.5 if rng.random() < 0.3 else 1)
        s0 = int(t * SR)
        tl = np.arange(min(int(2.4 * SR), n - s0)) / SR
        w = (np.sin(2 * np.pi * f * tl) + 0.35 * np.sin(4 * np.pi * f * tl) + 0.12 * np.sin(6 * np.pi * f * tl))
        w *= np.exp(-tl * 2.2) * np.minimum(1, tl / 0.004) * 0.03
        pan = 0.3 + 0.4 * rng.random()
        out[s0:s0 + len(tl), 0] += w * (1 - pan)
        out[s0:s0 + len(tl), 1] += w * pan
        t += 0.75 if i % 4 != 3 else 1.5
        i += 1
    return out / (np.abs(out).max() + 1e-9)


def build_audio(dry):
    clips = voices(dry)
    starts, durs, cur = [], [], 0.0
    for c in clips:
        d = LEAD + len(c) / SR + GAP
        starts.append(cur)
        durs.append(d)
        cur += d
    durs[-1] += TAIL
    total = cur + TAIL
    n = int(total * SR)
    voice = np.zeros(n)
    for s, c in zip(starts, clips):
        i = int((s + LEAD) * SR)
        voice[i:i + len(c)] += c
    active = ndimage.maximum_filter1d((np.abs(voice) > 0.01).astype(float), int(SR * 0.6))
    duck = 1 - 0.55 * ndimage.gaussian_filter1d(active, SR * 0.3)
    tt = np.arange(n) / SR
    fade = np.clip(np.minimum(tt / 1.5, (total - tt) / 2.5), 0, 1)
    mix = bgm(n) * (0.45 * duck * fade)[:, None] + voice[:, None]
    mix /= max(np.abs(mix).max(), 1.0)
    return mix * 0.95, starts, durs, total


# ---------------------------------------------------------------- 映像
def load_sources():
    src = Image.open(SRC).convert("RGB")
    k = src.width / REF_W
    # 拡大に耐えるよう 3 倍に拡大してから軽くシャープにしておく（毎フレームはこれを切り出す）
    up = 3
    big = src.resize((src.width * up, src.height * up), Image.LANCZOS)
    big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    alts = {}
    for i in range(len(SCENES)):
        p = os.path.join(HERE, "scenes", f"{i:02d}.png")
        if os.path.exists(p):
            alts[i] = Image.open(p).convert("RGB")
    return big, k * up, alts


def cover(img, zoom=1.0, fx=0.5, fy=0.5):
    """img を 16:9 に切り抜いて W x H に（zoom>1 で拡大、fx,fy は注目点）"""
    iw, ih = img.size
    cw = min(iw, ih * W / H) / zoom
    ch = cw * H / W
    cx = min(max(iw * fx, cw / 2), iw - cw / 2)
    cy = min(max(ih * fy, ch / 2), ih - ch / 2)
    return img.resize((W, H), Image.BICUBIC, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))


def cam_view(big, k, moves, u):
    for (u0, *a), (u1, *b) in zip(moves, moves[1:]):
        if u0 <= u <= u1:
            e = ease((u - u0) / max(u1 - u0, 1e-6))
            cx, cy = (p + (q - p) * e for p, q in zip(a[:2], b[:2]))
            w = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * e)
            break
    else:
        cx, cy, w = moves[-1][1:]
    w *= k
    h = w * H / W
    cx, cy = cx * k, cy * k
    bw, bh = big.size
    if w >= bw:  # 全体表示は上下に余白（和紙色）を付けて収める
        h_img = bw * H / w
        canvas = Image.new("RGB", (W, H), (58, 44, 30))
        canvas.paste(big.resize((W, int(round(h_img * W / bw))), Image.BICUBIC),
                     (0, int((H - h_img * W / bw) / 2)))
        return canvas
    if h > bh:  # 元画像は16:9より横長なので、縦がはみ出す幅は縦いっぱいに制限
        h = bh
        w = h * W / H
    cx = min(max(cx, w / 2), bw - w / 2)
    cy = min(max(cy, h / 2), bh - h / 2)
    return big.resize((W, H), Image.BILINEAR, box=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))


def vignette():
    y, x = np.mgrid[0:H, 0:W]
    r = np.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2))
    return np.clip(1.08 - 0.32 * r ** 2, 0.55, 1.0)[..., None].astype(np.float32)


_ZIP = {}


def zipangu(big, k, u):
    """ジパングの場面: 絵巻をぼかして暗くし、光る金文字と金粉を重ねる"""
    if "bg" not in _ZIP:
        bg = cam_view(big, k, [(0, 704, 384, 1408)], 0).filter(ImageFilter.GaussianBlur(10))
        bg = Image.blend(bg, Image.new("RGB", (W, H), (20, 14, 8)), 0.55)
        isl = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(isl)
        d.text((W / 2, 400), "黄金の国", font=font(150, True), fill=255, anchor="mm")
        d.text((W / 2, 590), "ジパング", font=font(190, True), fill=255, anchor="mm")
        isl = isl.filter(ImageFilter.GaussianBlur(1))
        _ZIP["bg"], _ZIP["isl"] = bg, isl
        rng = np.random.default_rng(11)
        _ZIP["dust"] = rng.uniform([0, 0, 0], [W, H, 2 * math.pi], (160, 3))
    img = _ZIP["bg"].copy()
    glow = _ZIP["isl"].filter(ImageFilter.GaussianBlur(28))
    a = ease(u / 0.25)
    img.paste(C_GOLD, (0, 0), glow.point(lambda v: int(v * 0.6 * a)))
    gold = Image.new("RGB", (W, H), (0, 0, 0))
    grad = np.linspace(0, 1, H)[:, None, None] * np.array([-40, -50, -30]) + np.array([245, 205, 110])
    gold = Image.fromarray(np.broadcast_to(grad, (H, W, 3)).astype(np.uint8))
    img.paste(gold, (0, 0), _ZIP["isl"].point(lambda v: int(v * a)))
    d = ImageDraw.Draw(img)
    for x, y, ph in _ZIP["dust"]:
        yy = (y - u * 160) % H
        s = 2 + 2 * (0.5 + 0.5 * math.sin(ph + u * 12))
        d.ellipse((x - s, yy - s, x + s, yy + s), fill=(255, 226, 150))
    d.text((W / 2, 200), "Zipangu", font=font(56, True), fill=(250, 225, 160), anchor="mm")
    return img


def overlay(head, sub, is_title):
    """場面ごとの文字（RGBA）"""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    if is_title:
        d.rounded_rectangle((460, 330, 1460, 700), 24, fill=(30, 20, 10, 190), outline=C_GOLD + (255,), width=3)
        d.text((W / 2, 470), "マルコ・ポーロ物語", font=font(104, True), fill=(250, 236, 200), anchor="mm")
        d.text((W / 2, 585), "ヴェネツィアから大ハーンの国へ　二十四年の旅", font=font(40, True),
               fill=C_GOLD, anchor="mm")
        return ov
    if head:
        f = font(46, True)
        tw = d.textlength(head, font=f)
        d.rounded_rectangle((40, 40, 40 + tw + 64, 124), 14, fill=(30, 20, 10, 200))
        d.rectangle((40, 40, 50, 124), fill=C_GOLD + (255,))
        d.text((82, 82), head, font=f, fill=(250, 236, 200), anchor="lm")
    f = font(44)
    lines = wrap(sub, f, W - 260)
    lh = 64
    box_h = lh * len(lines) + 40
    y0 = H - 60 - box_h
    d.rounded_rectangle((90, y0, W - 90, H - 60), 18, fill=(20, 13, 6, 185))
    for j, line in enumerate(lines):
        d.text((W / 2, y0 + 20 + lh * j + lh / 2), line, font=f, fill=(255, 255, 255), anchor="mm")
    return ov


def wrap(text, f, width):
    """読点・句点のあとを優先して、幅に収まるよう折り返す"""
    lines, cur = [], ""
    for ch in text:
        if ImageDraw.Draw(Image.new("L", (1, 1))).textlength(cur + ch, font=f) > width:
            cut = max(cur.rfind("、"), cur.rfind("。"))
            if cut >= len(cur) * 0.5:
                lines.append(cur[:cut + 1])
                cur = cur[cut + 1:]
            else:
                lines.append(cur)
                cur = ""
        cur += ch
    lines.append(cur)
    return lines


def credit():
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = font(24)
    txt = "絵: 生成AI画像（史実の考証を経たものではありません）　音声: Gemini API（Google）"
    d.rounded_rectangle((W - 60 - d.textlength(txt, font=f) - 30, 36, W - 40, 84), 10, fill=(20, 13, 6, 170))
    d.text((W - 55, 60), txt, font=f, fill=(225, 210, 180), anchor="rm")
    return ov


class Renderer:
    def __init__(self, starts, durs):
        self.big, self.k, self.alts = load_sources()
        self.starts, self.durs = starts, durs
        self.ovs = [overlay(h, s, i == 0) for i, (h, s, _, _) in enumerate(SCENES)]
        self.vig = vignette()
        self.credit = credit()

    def scene_img(self, i, t):
        u = min(max((t - self.starts[i]) / self.durs[i], 0.0), 1.0)
        if i in self.alts:
            img = cover(self.alts[i], 1.0 + 0.08 * ease(u))
        elif SCENES[i][3] is None:
            img = zipangu(self.big, self.k, u)
        else:
            img = cam_view(self.big, self.k, SCENES[i][3], u)
        img = Image.fromarray((np.asarray(img, dtype=np.float32) * self.vig).astype(np.uint8))
        ov = self.ovs[i]
        a = ease((t - self.starts[i]) / 0.5)
        if a < 1:
            ov = ov.copy()
            ov.putalpha(ov.getchannel("A").point(lambda v: int(v * a)))
        img.paste(ov, (0, 0), ov)
        return img

    def frame(self, t):
        i = max(j for j, s in enumerate(self.starts) if t >= s)
        img = self.scene_img(i, t)
        end = self.starts[i] + self.durs[i]
        if i + 1 < len(SCENES) and t > end - XFADE:
            img = Image.blend(img, self.scene_img(i + 1, end), ease((t - (end - XFADE)) / XFADE))
        total = self.starts[-1] + self.durs[-1]
        if t > total - 4.0:  # 最後にクレジット
            ca = ease((t - (total - 4.0)) / 0.8)
            c = self.credit.copy()
            c.putalpha(c.getchannel("A").point(lambda v: int(v * ca)))
            img.paste(c, (0, 0), c)
        black = 1 - min(ease(t / 0.8), ease((total - t) / 1.2))
        if black > 0:
            img = Image.blend(img, Image.new("RGB", (W, H)), black)
        return img


def main():
    dry = "--preview" in sys.argv
    mix, starts, durs, total = build_audio(dry)
    print(f"total {total:.1f}s |", " ".join(f"{d:.1f}" for d in durs), flush=True)
    r = Renderer(starts, durs)
    if dry:
        for i, (s, d) in enumerate(zip(starts, durs)):
            r.frame(s + d * 0.5).save(os.path.join(HERE, f"preview_{i:02d}.png"))
        return

    os.makedirs(CACHE, exist_ok=True)
    wav = os.path.join(CACHE, "mix.wav")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    silent = os.path.join(CACHE, "video.mp4")
    writer = imageio_ffmpeg.write_frames(silent, (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                         macro_block_size=1, output_params=["-crf", "20", "-preset", "medium"])
    writer.send(None)
    n = int(total * FPS)
    for i in range(n):
        writer.send(np.asarray(r.frame(i / FPS)).tobytes())
        if i % 300 == 0:
            print(f"{i}/{n}", flush=True)
    writer.close()
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, time.strftime("marco_polo_%Y%m%d_%H%M.mp4"))
    subprocess.check_call([ff, "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out])
    print("done:", out)


if __name__ == "__main__":
    main()
