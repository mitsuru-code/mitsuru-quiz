# 豆知識ショート動画ジェネレータ（縦1080x1920 / 30fps / 45〜60秒）
# 使い方: python trivia_video.py scripts\xxx.json [出力.mp4] [--preview 秒,秒,...]
# ナレーション: Google Cloud TTS (Chirp3-HD)。キーは環境変数 GOOGLE_TTS_API_KEY。音声は tts_cache に保存し再課金しない
import re, base64, hashlib, json, math, os, random, subprocess, sys, wave, urllib.request, urllib.error
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import imageio_ffmpeg
import illust, visuals

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 30, 44100
VOICE = "ja-JP-Chirp3-HD-Kore"
RATE = 1.28

# ---------------- TTS ----------------
def api_key():
    k = os.environ.get("GOOGLE_TTS_API_KEY")
    if k: return k
    import winreg  # Windowsだけ（クラウドでは環境変数で渡す）
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
        return winreg.QueryValueEx(h, "GOOGLE_TTS_API_KEY")[0]

# 音声エンジン: "gemini"（Gemini 3.8 Flash TTS）/ "cloud"（Cloud TTS Chirp3-HD）。環境変数 TRIVIA_TTS で切替可
ENGINE = os.environ.get("TRIVIA_TTS", "cloud")  # Gemini APIの有効化後に "gemini" へ
GEMINI_MODEL, GEMINI_VOICE = "gemini-3.8-flash-tts", "Kore"
GEMINI_STYLE = "明るく親しみやすい雑学動画のナレーターとして、テンポよく、はっきり読み上げてください。文章は一字一句そのまま読み、言葉を足さないこと:"

def _gemini_tts(text, path):
    body = {"contents": [{"parts": [{"text": f"{GEMINI_STYLE}\n{text}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE}}}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                                 json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": api_key()})
    try: res = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e: sys.exit(f"Gemini TTS HTTP {e.code}: {e.read().decode()[:300]}")
    part = res["candidates"][0]["content"]["parts"][0]["inlineData"]
    rate = int((part.get("mimeType", "").split("rate=") + ["24000"])[1].split(";")[0])
    pcm = np.frombuffer(base64.b64decode(part["data"]), np.int16).astype(np.float64)
    x = np.arange(int(len(pcm) * SR / rate)) * rate / SR  # 24kHz → 44.1kHz
    out = np.interp(x, np.arange(len(pcm)), pcm).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(out.tobytes())

def tts(text):
    cache = os.path.join(HERE, "tts_cache"); os.makedirs(cache, exist_ok=True)
    tag = f"{GEMINI_MODEL}|{GEMINI_VOICE}|{GEMINI_STYLE}" if ENGINE == "gemini" else f"{VOICE}|{RATE}"
    path = os.path.join(cache, hashlib.sha1(f"{tag}|{text}".encode()).hexdigest()[:16] + ".wav")
    if not os.path.exists(path) and ENGINE == "gemini":
        _gemini_tts(text, path)
    if not os.path.exists(path):
        body = {"input": {"text": text}, "voice": {"languageCode": "ja-JP", "name": VOICE},
                "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": RATE}}
        req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "X-Goog-Api-Key": api_key()})
        try: audio = json.loads(urllib.request.urlopen(req).read())["audioContent"]
        except urllib.error.HTTPError as e: sys.exit(f"TTS HTTP {e.code}: {e.read().decode()[:200]}")
        open(path, "wb").write(base64.b64decode(audio))
    with wave.open(path) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768.0
        return pcm, len(pcm) / w.getframerate()

# ---------------- fonts / colors ----------------
from fonts import font  # Windowsは従来のフォント、クラウドはNotoで代用
JPB = lambda s: font("YuGothB.ttc", s)
JPM = lambda s: font("YuGothM.ttc", s)
EN = lambda s: font("segoeuib.ttf", s)

NAVY = (14, 20, 38)
GOLD = (255, 200, 90)
CORAL = (255, 122, 92)
MINT = (110, 225, 190)
CREAM = (248, 244, 232)
DIM = (120, 128, 150)

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def prog(t, a, b): return clamp((t - a) / (b - a)) if b > a else float(t >= a)
def eo(x): return 1 - (1 - x) ** 3
def eback(x):
    c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2

def paste(base, im, x, y):
    sx, sy = max(0, -x), max(0, -y); ex, ey = min(im.width, W - x), min(im.height, H - y)
    if ex > sx and ey > sy: base.alpha_composite(im.crop((sx, sy, ex, ey)), (x + sx, y + sy))

def with_alpha(im, a):
    if a >= 0.999: return im
    im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * a))); return im

def put(base, im, cx, cy, alpha=1.0, scale=1.0):
    if alpha <= 0.004: return
    if abs(scale - 1) > 1e-3:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BICUBIC)
    paste(base, with_alpha(im, alpha), int(cx - im.width / 2), int(cy - im.height / 2))

@lru_cache(None)
def label(text, fnt_name, size, fill, pad=0):
    fnt = font(fnt_name, size)
    l, t, r, b = fnt.getbbox(text)
    im = Image.new("RGBA", (r - l + 2 * pad + 4, b - t + 2 * pad + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - l + 2, pad - t + 2), text, font=fnt, fill=fill)
    return im

@lru_cache(None)
def chip(text, fg, bg, size=38):
    fnt = JPB(size); l, t, r, b = fnt.getbbox(text)
    w, h = r - l + 56, b - t + 30
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=bg)
    d.text((28 - l, 15 - t), text, font=fnt, fill=fg)
    return im

# ---------------- karaoke text block ----------------
NO_HEAD = "、。，．！？」）ー…っゃゅょァィゥェォッャュョ"
def wrap(text, fnt, maxw):
    # まず読点・句点などの区切りでまとめて改行し、収まらない塊だけ文字単位で折り返す
    import re
    chunks = [x for x in re.split(r"(?<=[、。！？!?」])", text) if x]
    if len(chunks) > 1:
        lines, cur = [], ""
        for ck in chunks:
            if fnt.getlength(cur + ck) <= maxw: cur += ck; continue
            if cur: lines.append(cur); cur = ""
            if fnt.getlength(ck) <= maxw: cur = ck
            else:
                sub = wrap_chars(ck, fnt, maxw); lines += sub[:-1]; cur = sub[-1]
        if cur: lines.append(cur)
        return lines
    return wrap_chars(text, fnt, maxw)

def wrap_chars(text, fnt, maxw):
    PART = "はがをにでとものへやかよね、"
    lines, cur = [], ""
    for ch in re.findall(r"[A-Za-z0-9.,%]+|.", text):  # 英数字の途中では折り返さない
        if cur and fnt.getlength(cur + ch) > maxw and ch[0] not in NO_HEAD:
            k = max((cur.rfind(p) for p in PART), default=-1)
            if k >= len(cur) - 5 and k >= 2:  # 助詞の後ろで折る
                lines.append(cur[:k + 1]); cur = cur[k + 1:] + ch
            else:
                lines.append(cur); cur = ch
        else: cur += ch
    if cur: lines.append(cur)
    return lines

class Block:
    """折り返し済みテキスト。読み上げ位置までを明るく、先を暗く描く"""
    def __init__(self, text, fnt, maxw, bright, dim, lh=1.45):
        lines = wrap(text, fnt, maxw)
        while maxw > 200 and not re.search(r"[、。！？!?」]", text[:-1]) and len(wrap(text, fnt, maxw - 20)) == len(lines):  # 行長をそろえて1〜2文字の孤立行を防ぐ
            maxw -= 20; lines = wrap(text, fnt, maxw)
        self.fnt, self.lines = fnt, lines
        self.lh = int(fnt.size * lh); self.n = len(text)
        self.w = int(max(fnt.getlength(s) for s in self.lines)) + 20
        self.h = self.lh * len(self.lines) + 20
        self.dim = Image.new("RGBA", (self.w, self.h)); self.br = Image.new("RGBA", (self.w, self.h))
        dd, db = ImageDraw.Draw(self.dim), ImageDraw.Draw(self.br)
        self.meta = []; idx = 0
        for i, s in enumerate(self.lines):
            x = (self.w - fnt.getlength(s)) / 2; y = 10 + i * self.lh
            dd.text((x, y), s, font=fnt, fill=dim); db.text((x, y), s, font=fnt, fill=bright)
            self.meta.append((idx, s, x, y)); idx += len(s)
    def draw(self, base, cx, cy, chars, alpha=1.0):
        if alpha <= 0.004: return
        x0, y0 = int(cx - self.w / 2), int(cy - self.h / 2)
        paste(base, with_alpha(self.dim, alpha), x0, y0)
        for idx, s, x, y in self.meta:
            k = int(clamp(chars - idx, 0, len(s)))
            if k <= 0: break
            wk = int(x + self.fnt.getlength(s[:k])) + 2
            paste(base, with_alpha(self.br.crop((0, int(y) - 6, wk, int(y) + self.lh)), alpha), x0, y0 + int(y) - 6)

# ---------------- background ----------------
# 背景テーマは投稿日ごとに切り替える（7種を日付で順番に。script["theme"] で指定も可）
THEMES = [
    {"name": "ミッドナイト", "top": (14, 20, 38), "bot": (24, 26, 60), "orbs": [GOLD, CORAL, MINT, (120, 140, 255)], "dot": CREAM},
    {"name": "深い森", "top": (8, 28, 22), "bot": (16, 50, 40), "orbs": [MINT, GOLD, (170, 230, 120)], "dot": (210, 245, 220)},
    {"name": "ワイン", "top": (34, 10, 24), "bot": (60, 20, 42), "orbs": [CORAL, (255, 150, 190), GOLD], "dot": (255, 225, 235)},
    {"name": "深海", "top": (4, 24, 36), "bot": (8, 52, 68), "orbs": [(90, 210, 240), MINT, (120, 150, 255)], "dot": (200, 240, 255)},
    {"name": "すみれ夜", "top": (20, 12, 42), "bot": (42, 24, 76), "orbs": [(170, 140, 255), (255, 150, 200), GOLD], "dot": (235, 225, 255)},
    {"name": "カフェ", "top": (32, 20, 12), "bot": (58, 38, 22), "orbs": [GOLD, (255, 160, 80), (240, 220, 180)], "dot": (255, 240, 215)},
    {"name": "チャコール", "top": (18, 20, 24), "bot": (38, 42, 50), "orbs": [CORAL, GOLD, (90, 210, 240)], "dot": CREAM},
]
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
def orb(r, col):
    im = Image.new("RGBA", (r * 4, r * 4)); ImageDraw.Draw(im).ellipse((r, r, 3 * r, 3 * r), fill=col + (70,))
    return im.filter(ImageFilter.GaussianBlur(r * 0.6))
BG_IMG = ORBS = DOTS = None; DOT_COL = CREAM
def setup_theme(script):
    global BG_IMG, ORBS, DOTS, DOT_COL
    from datetime import date
    if isinstance(script.get("theme"), int): i = script["theme"] % len(THEMES)
    else:
        pd = str(script.get("postDate") or date.today().strftime("%Y%m%d"))
        i = date(int(pd[:4]), int(pd[4:6]), int(pd[6:8])).toordinal() % len(THEMES)
    th = THEMES[i]
    g = (yy / H)[..., None]
    bg = np.array(th["top"], np.float32) * (1 - g) + np.array(th["bot"], np.float32) * g
    BG_IMG = Image.fromarray(bg.astype(np.uint8)).convert("RGBA")
    rng = random.Random(3 + i)  # 玉ボケの配置もテーマごとに変える
    ORBS = [(orb(rng.randint(90, 180), rng.choice(th["orbs"])), rng.uniform(0, W), rng.uniform(0, H),
             rng.uniform(0.1, 0.35), rng.uniform(0, 6)) for _ in range(7)]
    DOTS = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(10, 40), rng.uniform(1.5, 3.5), rng.random()) for _ in range(80)]
    DOT_COL = th["dot"]
    return th["name"]

def background(t, total):
    img = BG_IMG.copy()
    for im, x0, y0, sp, ph in ORBS:
        x = x0 + 120 * math.sin(t * sp + ph); y = (y0 - t * 25 * sp) % (H + 400) - 200
        paste(img, im, int(x - im.width / 2), int(y - im.height / 2))
    d = ImageDraw.Draw(img)
    for x0, y0, sp, sz, ph in DOTS:
        y = (y0 - sp * t) % H; a = int(60 + 80 * (0.5 + 0.5 * math.sin(t * 2 + ph * 9)))
        d.ellipse((x0 - sz, y - sz, x0 + sz, y + sz), fill=DOT_COL + (a,))
    # 上部の進捗バー（離脱防止）
    d.rounded_rectangle((60, 70, W - 60, 80), 5, fill=(255, 255, 255, 40))
    d.rounded_rectangle((60, 70, 60 + (W - 120) * t / total, 80), 5, fill=GOLD + (255,))
    return img

# ---------------- build timeline ----------------
def build(script):
    segs = [("hook", script["hook"]), ("intro", script["intro"]), ("question", script["question"]),
            ("conclusion", script["conclusion"])]
    segs += [("point", p["text"], i, p["head"]) for i, p in enumerate(script["points"])]
    segs += [("share", script["share"]), ("outro", script["outro"])]
    tl, t = [], 0.0  # 0秒から始める（最初の2秒で引きつける）
    images = visuals.load_images(script)
    if script.get("imageFolder"): print(f"images: {len(images)}枚 {sorted(images)}")
    for s in segs:
        pcm, d = tts(s[1])
        extra = {"hook": 0.3, "question": 1.4, "conclusion": 0.4, "outro": 0.6}.get(s[0], 0.25)
        lead = 0.05 if s[0] == "hook" else 0.25  # つかみは即座に読み始める
        dur = d + extra + lead
        key = f"point{s[2]}" if s[0] == "point" else s[0]
        vis = visuals.choose(script, key, images) if s[0] != "outro" else None
        tl.append(dict(kind=s[0], text=s[1], idx=s[2] if len(s) > 2 else None, head=s[3] if len(s) > 3 else None,
                       start=t, dur=dur, vstart=t + lead, vdur=d, pcm=pcm, vis=vis))
        t += dur
    return tl, t + 0.3

# ---------------- scenes ----------------
BLOCKS = {}
def block(seg, fnt, maxw, bright=CREAM, dim=DIM):
    key = (id(seg), fnt.size)
    if key not in BLOCKS: BLOCKS[key] = Block(seg["text"], fnt, maxw, bright, dim)
    return BLOCKS[key]

def hook_size(text, maxw=960):
    parts = [x for x in re.split(r"(?<=[、。！？!?」])", text) if x]
    for s in range(92, 55, -4):
        if all(JPB(s).getlength(x) <= maxw for x in parts): return s
    return 56

def spoken(seg, lt):  # 読み上げ済みの文字数
    return len(seg["text"]) * clamp((lt - (seg["vstart"] - seg["start"])) / (seg["vdur"] * 0.95))

def scene(img, seg, lt, script, n_points):
    k = seg["kind"]; d = seg["dur"]
    a = eo(prog(lt, 0, 0.25)) * (1 - prog(lt, d - 0.2, d))
    up = 50 * (1 - eo(prog(lt, 0, 0.35)))
    ch = spoken(seg, lt)
    il = seg.get("vis")
    Y = lambda no, yes: yes if il else no  # 絵ありは文字を上に寄せ、下半分を絵に使う
    if k == "hook":  # 1フレーム目から全部見せる：絵を大きく、つかみの一言は最初から全文表示
        a, up = 1 - prog(lt, d - 0.2, d), 0
        if il:
            put(img, visuals.render(il, 1.0 + lt), W / 2, 1250, a, 1.12 - 0.12 * eo(prog(lt, 0, 0.5)))
        else:
            q = label("?", "segoeuib.ttf", 700, (255, 255, 255, 18))
            put(img, q.rotate(8 * math.sin(lt * 1.5), Image.BICUBIC, expand=True), W / 2, 1100, a)
        put(img, chip("追及深堀り豆知識", NAVY, GOLD, 34), W / 2, 260, a)
        BLOCKS.setdefault(("hookfull", id(seg)), Block(seg["text"], JPB(hook_size(seg["text"])), 960, GOLD, GOLD)).draw(img, W / 2, Y(900, 560), 999, a)
    elif il:
        put(img, visuals.render(il, max(0, lt - 0.2)), W / 2, {"question": 1100}.get(k, 1330) + up, a)
    if k == "hook":
        pass
    elif k == "intro":
        put(img, chip("よくある思い込み", CREAM, (255, 255, 255, 40), 36), W / 2, Y(700, 420) + up, a)
        block(seg, JPB(72), 900).draw(img, W / 2, Y(960, 680) + up, ch, a)
    elif k == "question":
        put(img, label("Q", "segoeuib.ttf", Y(200, 160), CORAL), W / 2, Y(560, 380) + up, a, eback(prog(lt, 0, 0.4)) or 0.01)
        block(seg, JPB(76), 880).draw(img, W / 2, Y(860, 620) + up, ch, a)
        think0 = seg["vstart"] - seg["start"] + seg["vdur"]
        p = prog(lt, think0, think0 + 1.8)
        if lt > think0 - 0.2:
            lay = Image.new("RGBA", (W, H)); dd = ImageDraw.Draw(lay)
            r = Y(110, 90); cx, cy = W / 2, Y(1260, 1570)
            dd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 50), width=12)
            dd.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * p, fill=GOLD + (255,), width=12)
            n = max(1, 3 - int(p * 3))
            img.alpha_composite(with_alpha(lay, a))
            put(img, label(str(n), "segoeuib.ttf", 120, CREAM), cx, cy, a)
            put(img, label("考えてみて！", "YuGothB.ttc", 50, GOLD), W / 2, Y(1450, 1740), a)
    elif k == "conclusion":
        pop = eback(prog(lt, 0, 0.45))
        put(img, label("A", "segoeuib.ttf", Y(200, 150), GOLD), W / 2, Y(470, 320) + up, a, pop or 0.01)
        b = block(seg, JPB(Y(62, 56)), 760); cy = Y(980, 680)
        lay = Image.new("RGBA", (W, H)); ImageDraw.Draw(lay).rounded_rectangle(
            (50, cy - b.h / 2 - 50 + up, W - 50, cy + b.h / 2 + 50 + up), 40, fill=(255, 255, 255, 22), outline=GOLD + (160,), width=3)
        img.alpha_composite(with_alpha(lay, a))
        b.draw(img, W / 2, cy + up, ch, a)
    elif k == "point":
        i = seg["idx"]
        put(img, chip(f"深掘りポイント {i + 1} / {n_points}", NAVY, MINT, 36), W / 2, Y(440, 290) + up, a)
        put(img, label(str(i + 1), "segoeuib.ttf", Y(230, 140), GOLD), W / 2, Y(640, 420) + up, a, eback(prog(lt, 0, 0.45)) or 0.01)
        hb = BLOCKS.setdefault(("head", id(seg)), Block(seg["head"], JPB(Y(74, 64)), 900, CORAL, CORAL))
        hb.draw(img, W / 2, Y(860, 600) + up, 999, a)
        block(seg, JPM(Y(58, 52)), 900).draw(img, W / 2, Y(1180, 860) + up, ch, a)
        dy = Y(1600, 1720)
        for j in range(n_points):
            r = 12 if j == i else 9
            ImageDraw.Draw(img).ellipse((W / 2 - 40 + j * 40 - r, dy - r, W / 2 - 40 + j * 40 + r, dy + r),
                                        fill=(GOLD if j <= i else (90, 96, 120)) + (int(255 * a),))
    elif k == "share":
        put(img, chip("人に話したくなる一言", NAVY, CORAL, 40), W / 2, Y(600, 360) + up, a)
        b = block(seg, JPB(66), 820); cy = Y(960, 650)
        lay = Image.new("RGBA", (W, H)); dd = ImageDraw.Draw(lay)
        top, bot = cy - b.h / 2 - 60 + up, cy + b.h / 2 + 60 + up
        dd.rounded_rectangle((80, top, W - 80, bot), 50, fill=(255, 255, 255, 235))
        dd.polygon([(W / 2 - 40, bot - 2), (W / 2 + 40, bot - 2), (W / 2 - 10, bot + 60)], fill=(255, 255, 255, 235))
        img.alpha_composite(with_alpha(lay, a))
        BLOCKS.setdefault(("share", id(seg)), Block(seg["text"], JPB(66), 820, NAVY, (170, 170, 185))).draw(img, W / 2, cy + up, ch, a)
    elif k == "outro":
        b = block(seg, JPB(70), 880, GOLD)
        b.draw(img, W / 2, 860 + up, ch, a)
        put(img, label(script.get("handle", ""), "segoeuib.ttf", 64, CREAM), W / 2, 1110 + up, a * eo(prog(lt, 0.5, 0.9)))
        put(img, chip("フォロー", NAVY, GOLD, 48), W / 2, 1260 + up, a * eo(prog(lt, 0.8, 1.2)),
            1 + 0.05 * math.sin(lt * 8))
    # タイトルの常時表示（hook以外）
    if k != "hook":
        t_im = label(script["title"] if len(script["title"]) <= 26 else script["title"][:25] + "…", "YuGothB.ttc", 34, (220, 222, 235))
        put(img, t_im, W / 2, 150, 0.85)

def frame(f, tl, total, script):
    t = f / FPS
    img = background(t, total)
    npts = len(script["points"])
    for seg in tl:
        if seg["start"] <= t < seg["start"] + seg["dur"]:
            scene(img, seg, t - seg["start"], script, npts)
    flash = max([math.exp(-(t - s["start"]) * 12) for s in tl if t >= s["start"]] + [0]) * 0.1
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    if flash > 0.02: arr += (255 - arr) * flash
    arr *= min(1, (total - t) / 0.4)  # 冒頭はフェードインしない
    return np.clip(arr, 0, 255).astype(np.uint8)

# ---------------- audio ----------------
def audio(tl, total, path):
    n = int(total * SR); tt = np.arange(n) / SR
    rng2 = np.random.default_rng(1)
    bgm = np.zeros((n, 2))
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    beat = 60 / 88
    CH = [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]]  # Fmaj7 Em7 Dm7 Cmaj7
    bar = beat * 4
    for b in range(int(total / bar) + 1):
        s0 = b * bar; notes = CH[b % 4]
        L = int(bar * SR); x = np.arange(L) / SR
        env = np.minimum(1, x / 0.08) * np.exp(-x * 0.6)
        sig = sum(np.sin(2 * np.pi * hz(m) * x) + 0.25 * np.sin(4 * np.pi * hz(m) * x) for m in notes) * env * 0.05
        bass = np.sin(2 * np.pi * hz(notes[0] - 12) * x) * np.exp(-x * 1.2) * 0.18
        i = int(s0 * SR); j = min(n, i + L)
        if j > i:
            bgm[i:j, 0] += (sig * 1.0 + bass)[: j - i]; bgm[i:j, 1] += (sig * 0.8 + bass)[: j - i]
        for k in range(4):
            st = int((s0 + k * beat) * SR)
            if k % 2 == 0 and st < n:  # soft kick
                y = np.arange(int(0.3 * SR)) / SR; kick = np.sin(2 * np.pi * (50 + 60 * np.exp(-y * 25)) * y) * np.exp(-y * 9) * 0.35
                e = min(n, st + len(kick)); bgm[st:e] += kick[: e - st, None]
            for h in (0, 0.5):
                sh = int((s0 + (k + h) * beat) * SR)
                if sh < n:
                    y = np.arange(int(0.04 * SR)) / SR; hat = np.diff(rng2.standard_normal(len(y) + 1)) * np.exp(-y * 90) * 0.025
                    e = min(n, sh + len(hat)); bgm[sh:e] += hat[: e - sh, None]
    bgm += rng2.standard_normal((n, 1)) * 0.002  # vinyl noise
    voice = np.zeros(n); sfx = np.zeros(n)
    def blip(t0, f0, f1, dur, amp):
        i = int(t0 * SR); y = np.arange(int(dur * SR)) / SR
        s = np.sin(2 * np.pi * np.cumsum(np.linspace(f0, f1, len(y))) / SR) * np.exp(-y * 14) * amp
        e = min(n, i + len(s)); sfx[i:e] += s[: e - i]
    for seg in tl:
        i = int(seg["vstart"] * SR); v = seg["pcm"]; e = min(n, i + len(v)); voice[i:e] += v[: e - i]
        blip(seg["start"], 700, 1100, 0.18, 0.18)
        if seg["kind"] == "conclusion":
            for f0 in (1318.5, 1760):
                blip(seg["start"] + (0.08 if f0 > 1500 else 0), f0, f0, 0.9, 0.2)
        if seg["kind"] == "question":
            th = seg["vstart"] + seg["vdur"]
            for k in range(3): blip(th + k * 0.6, 1500, 1500, 0.05, 0.15)
    voice *= 0.9 / max(1e-6, np.abs(voice).max())
    k = int(0.3 * SR); cs = np.concatenate([[0.0], np.cumsum((np.abs(voice) > 0.01).astype(np.float64))])
    idx = np.arange(n); env = (cs[np.minimum(n, idx + k // 2)] - cs[np.maximum(0, idx - k // 2)]) / k  # 移動平均（累積和でO(n)）
    bgm *= (0.55 - 0.3 * np.clip(env * 3, 0, 1))[:, None]
    mix = bgm + (voice + sfx)[:, None]
    fo = int(0.6 * SR); mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    mix *= 0.89 / np.abs(mix).max()
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((mix * 32767).astype(np.int16).tobytes())

# ---------------- main ----------------
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    script = json.load(open(args[0], encoding="utf-8"))
    print("theme:", setup_theme(script))
    tl, total = build(script)
    N = int(total * FPS)
    print(f"total {total:.1f}s / {N} frames")
    for s in tl: print(f"  {s['kind']:10s} {s['start']:5.1f}s +{s['dur']:.1f}s")
    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1].split(",")]
        for s in times: Image.fromarray(frame(int(s * FPS), tl, total, script)).save(os.path.join(HERE, f"prev_{s:05.1f}.png"))
        sys.exit()
    out = args[1] if len(args) > 1 else os.path.join(os.path.expanduser("~"), "Videos", "豆知識",
                                                         os.path.splitext(os.path.basename(args[0]))[0] + ".mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wav = os.path.join(HERE, "_audio.wav"); audio(tl, total, wav)
    p = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium",
                          "-crf", "23", "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p",
                          "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", "-c:a", "aac", "-b:a", "192k",
                          "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for f in range(N):
        p.stdin.write(frame(f, tl, total, script).tobytes())
        if f % 150 == 0: print(f"frame {f}/{N}", flush=True)
    p.stdin.close(); p.wait()
    print("done", out)
    outs = [out]
    if script.get("post"):  # X投稿の本文（導入文）を動画と同じ名前の .txt で保存
        txt = os.path.splitext(out)[0] + "_X投稿文.txt"
        open(txt, "w", encoding="utf-8").write(script["post"].strip() + "\n"); outs.append(txt); print("post", txt)
    if script.get("sources"):  # 事実確認の結果と出典
        src = os.path.splitext(out)[0] + "_出典.txt"
        open(src, "w", encoding="utf-8").write(script["sources"].strip() + "\n"); outs.append(src); print("sources", src)
    if os.environ.get("TRIVIA_NO_DRIVE"): sys.exit()  # 試作はドライブに入れない
    # Googleドライブ（パソコン版）が接続されていれば「マイドライブ\豆知識動画」へコピー（既存ファイルは上書きしない）
    import shutil, string
    roots = [f"{dl}:\\{m}" for dl in string.ascii_uppercase for m in ("マイドライブ", "My Drive") if os.path.isdir(f"{dl}:\\{m}")]
    if not roots: sys.exit(print("drive: Googleドライブ未接続のためコピーせず"))
    dst_dir = os.path.join(roots[0], "豆知識動画"); os.makedirs(dst_dir, exist_ok=True)
    for src in outs:
        dst = os.path.join(dst_dir, os.path.basename(src))
        if os.path.exists(dst):
            stem, ext = os.path.splitext(dst); k = 2
            while os.path.exists(f"{stem}_{k}{ext}"): k += 1
            dst = f"{stem}_{k}{ext}"
        shutil.copy2(src, dst); print("drive", dst)
