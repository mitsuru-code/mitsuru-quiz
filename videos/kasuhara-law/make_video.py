"""カスハラ防止法（改正労働施策総合推進法）を約2分で解説する動画を作るスクリプト。

使い方:
    pip install numpy scipy pillow imageio-ffmpeg pyopenjtalk
    python3 make_video.py            # kasuhara_law.mp4 を出力（1920x1080 / 30fps / 約2分 / BGM・ナレーション・字幕付き）
    python3 make_video.py --preview  # 各場面の静止画だけ出力（preview_*.png）

場面の長さはナレーションの長さから自動で決まる（読み上げ → 映像の順に作る）。

内容の出典（2026年10月時点）:
    - 労働施策総合推進法の改正（令和7年法律第63号、2025年6月11日公布、2026年10月1日施行）
    - 事業主が職場における顧客等の言動に起因する問題に関して雇用管理上講ずべき措置等についての指針
      （令和8年厚生労働省告示第51号）
素材:
    - ナレーション音声: Open JTalk + HTS Voice Mei（名古屋工業大学, CC BY 3.0）
    - フォント: IPAゴシック（IPAフォントライセンス）
"""
import os
import subprocess
import sys
import urllib.request
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT = os.environ.get("VIDEO_OUT", os.path.join(HERE, "kasuhara_law.mp4"))
W, H, FPS, SR = 1920, 1080, 30, 44100

FONT_PATHS = ["/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
              "C:/Windows/Fonts/BIZ-UDGothicB.ttc", "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/msgothic.ttc"]
FONT_PATH = next(p for p in FONT_PATHS if os.path.exists(p))

# 配色
C_BG = (16, 27, 48)
C_BG2 = (26, 44, 76)
C_CARD = (34, 56, 94)
C_TEXT = (240, 244, 250)
C_SUB = (168, 186, 214)
C_ACCENT = (255, 159, 67)   # オレンジ
C_OK = (72, 199, 142)       # 緑
C_NG = (240, 92, 92)        # 赤
C_BLUE = (90, 170, 255)

# ======================================================================
# 台本: 各場面 = 見出し + 要素（順に表示）+ ナレーション
#   segs: (字幕, 読み上げ文, その文が始まる時に表示済みにする要素数)
#   読み上げ文は読み誤り対策で一部かな書き
# ======================================================================
SCENES = [
    dict(kind="title", head="", items=[
        dict(big="カスハラ防止法", sub="2分でわかる　企業に何が求められる？"),
        dict(badge="2026年10月1日 施行"),
    ], segs=[
        ("2分でわかる、カスハラ防止法。", "にふんでわかる、カスハラ防止法。", 1),
        ("2026年10月から、すべての会社にカスハラ対策が義務づけられました。",
         "2026年10月から、すべての会社に、カスハラ対策が、義務づけられました。", 2),
    ]),
    dict(kind="facts", head="どんな法律？", items=[
        dict(label="正式には", value="改正 労働施策総合推進法"),
        dict(label="公布", value="2025年6月11日"),
        dict(label="施行", value="2026年10月1日"),
        dict(label="対象", value="労働者を1人でも雇うすべての事業主", note="中小企業・個人事業主も。業種や規模による除外なし"),
    ], segs=[
        ("正式には、改正された労働施策総合推進法。", "正式には、改正された、労働施策総合推進法。", 1),
        ("2025年6月に公布され、2026年10月1日に施行されました。", "2025年6月に公布され、2026年10月1日に施行されました。", 3),
        ("従業員を1人でも雇っていれば、規模や業種を問わず対象です。", "従業員を一人でも雇っていれば、規模や業種を問わず、対象です。", 4),
    ]),
    dict(kind="cards3", head="カスハラとは？　3つの要素をすべて満たすもの", items=[
        dict(no="1", title="顧客等の言動", body="顧客・取引先・施設の利用者など、事業に関係する人の言動"),
        dict(no="2", title="社会通念上の\n許容範囲を超える", body="要求の内容が妥当でない、または手段・態様が相当でない"),
        dict(no="3", title="就業環境が\n害される", body="働く人が身体的・精神的に苦痛を受け、働く環境が害される"),
    ], segs=[
        ("カスハラとは、次の3つをすべて満たす行為です。", "カスハラとは、次の三つを、すべて満たす行為です。", 0),
        ("1つ目、顧客や取引先など、事業に関係する人の言動であること。",
         "一つ目。顧客や取引先など、事業に関係する人の言動であること。", 1),
        ("2つ目、社会通念上、許される範囲を超えていること。", "二つ目。社会通念上、許される範囲を、超えていること。", 2),
        ("3つ目、働く人の就業環境が害されること。", "三つ目。働く人の、就業環境が、害されること。", 3),
    ]),
    dict(kind="versus", head="カスハラになる例・ならない例", items=[
        dict(side="ng", title="カスハラの例", lines=["暴言・大声・脅迫", "長時間の拘束・何度も電話", "土下座の要求", "SNSでのさらし・誹謗中傷"]),
        dict(side="ok", title="カスハラではない", lines=["商品の不具合を伝える", "ミスへの謝罪・交換の要求", "社会通念の範囲内の苦情", "→ 正当なクレームは大切な声"]),
    ], segs=[
        ("たとえば、暴言や脅し、長時間の拘束、土下座の要求、SNSでのさらしなど。",
         "たとえば、暴言や脅し、長時間の拘束、土下座の要求、SNSでのさらしなどです。", 1),
        ("一方、商品の不具合を伝えるような正当なクレームは、カスハラではありません。",
         "いっぽう、商品の不具合を伝えるような、正当なクレームは、カスハラではありません。", 2),
    ]),
    dict(kind="cards4", head="会社が講じなければならない措置", items=[
        dict(no="1", title="方針を決めて周知", body="カスハラには毅然と対応する方針を明確にし、従業員に周知・啓発"),
        dict(no="2", title="相談体制をつくる", body="相談窓口を決めて周知し、担当者が適切に対応できるようにする"),
        dict(no="3", title="起きたら迅速に対応", body="事実を確認し、被害を受けた従業員に配慮、再発を防止"),
        dict(no="4", title="悪質ケースに備える", body="特に悪質な場合の対処方針（警察への相談等）を事前に決めておく"),
    ], segs=[
        ("会社に求められる対策は、大きく4つ。", "会社に求められる対策は、大きく四つ。", 0),
        ("方針を決めて、社内に周知すること。", "方針を決めて、社内に周知すること。", 1),
        ("相談窓口をつくること。", "相談窓口を、つくること。", 2),
        ("起きたときは事実を確認し、従業員を守って、再発を防ぐこと。",
         "起きたときは、事実を確認し、従業員を守って、再発を防ぐこと。", 3),
        ("そして、悪質なケースへの対応方針を、あらかじめ決めておくことです。",
         "そして、悪質なケースへの対応方針を、あらかじめ決めておくことです。", 4),
    ]),
    dict(kind="list", head="あわせて守ること", items=[
        dict(icon="🔒", color=C_BLUE, title="相談者のプライバシーを守る", body="相談内容や個人情報が広がらないよう措置し、従業員に周知"),
        dict(icon="⚖", color=C_ACCENT, title="相談したことで不利益に扱わない", body="相談・事実確認への協力を理由とする解雇などは禁止"),
        dict(icon="♿", color=C_OK, title="お客様の正当な権利に配慮", body="消費者の権利や、障害のある方への合理的配慮に留意"),
    ], segs=[
        ("あわせて、相談した人のプライバシーを守り、", "あわせて、相談した人の、プライバシーを守り、", 1),
        ("相談したことを理由に、不利益に扱うことは禁止です。", "相談したことを理由に、不利益に扱うことは、禁止です。", 2),
        ("障害のある方への合理的配慮など、お客様の正当な権利にも気をつけましょう。",
         "障害のある方への合理的配慮など、お客様の正当な権利にも、気をつけましょう。", 3),
    ]),
    dict(kind="end", head="", items=[
        dict(big="お客様も、働く人も、同じ人。", sub="まずは自社の方針と相談窓口を確認しよう"),
        dict(src="出典: 厚生労働省「カスタマーハラスメント防止指針」（令和8年厚生労働省告示第51号）／改正労働施策総合推進法"),
    ], segs=[
        ("お客様も、働く人も、同じ人。", "お客様も、働く人も、同じ人。", 1),
        ("まずは自社の方針と相談窓口を、確認するところから始めましょう。",
         "まずは、自社の方針と、相談窓口を、確認するところから、始めましょう。", 2),
    ]),
]

LEAD, GAP, TAIL = 0.7, 0.35, 0.9  # 場面の頭の間・文と文の間・場面の終わりの間（秒）
SPEED = 1.08                        # 話速

# ======================================================================
# ナレーション
# ======================================================================
VOICE_URL = "https://raw.githubusercontent.com/mmdagent-ex/example/main/voice/mei/mei_normal.htsvoice"
# HTS Voice "Mei" (c) Nagoya Institute of Technology, CC BY 3.0


def fetch(name, url):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        print("download:", url, flush=True)
        urllib.request.urlretrieve(url, path)
    return path


def _smooth_voice(x):
    """機械的なざらつきを抑える後処理（japan-formation と同じ）"""
    from scipy.signal import butter, fftconvolve, sosfiltfilt

    x = sosfiltfilt(butter(4, 7000, "low", fs=SR, output="sos"), x)
    x = sosfiltfilt(butter(2, 90, "high", fs=SR, output="sos"), x)
    rng = np.random.default_rng(7)
    ir_t = np.arange(int(0.35 * SR)) / SR
    ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t / 0.07)
    ir = sosfiltfilt(butter(2, 3500, "low", fs=SR, output="sos"), ir)
    wet = fftconvolve(x, ir)[: len(x) + len(ir_t) // 2]
    x = np.concatenate([x, np.zeros(len(wet) - len(x))])
    x = x + wet / (np.abs(wet).max() + 1e-9) * np.abs(x).max() * 0.12
    rms = np.sqrt(np.mean(x[np.abs(x) > np.abs(x).max() * 0.05] ** 2)) + 1e-9
    x = x / rms * 0.16
    x = np.tanh(x * 1.6) / 1.6
    fade = int(0.03 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade * 4:] *= np.linspace(1, 0, fade * 4)
    return x


def synth_all():
    """全文を読み上げ、タイムライン（場面・文の開始秒）を決める"""
    import pyopenjtalk
    from pyopenjtalk.htsengine import HTSEngine
    from scipy.signal import resample_poly

    eng = HTSEngine(fetch("mei_normal.htsvoice", VOICE_URL).encode())
    eng.set_speed(SPEED)
    vsr = eng.get_sampling_frequency()
    clips, timeline, t = [], [], 0.0
    for si, sc in enumerate(SCENES):
        s_start = t
        t += LEAD
        segs = []
        for disp, read, step in sc["segs"]:
            x = np.asarray(eng.synthesize(pyopenjtalk.extract_fullcontext(read)), dtype=np.float64)
            eng.refresh()
            x = _smooth_voice(resample_poly(x, SR, vsr) / 32768.0)
            dur = len(x) / SR
            clips.append((t, x))
            segs.append(dict(t0=t, t1=t + dur, text=disp, step=step))
            t += dur + GAP
        t += TAIL - GAP
        timeline.append(dict(t0=s_start, t1=t, segs=segs))
        for sg in segs:
            assert font(44).getlength(sg["text"]) <= 1760, f"字幕が1行に収まりません: {sg['text']}"
        print(f"scene {si}: {s_start:6.1f}s 〜 {t:6.1f}s", flush=True)
    return clips, timeline, t


def make_audio(path, clips, total):
    n = int(total * SR) + SR
    tt = np.arange(n) / SR
    out = np.zeros((n, 2))
    # 落ち着いたパッド（C - Am - F - G を繰り返す）
    chords = [[261.6, 329.6, 392.0], [220.0, 261.6, 329.6], [174.6, 220.0, 261.6], [196.0, 246.9, 293.7]]
    seg_len = 6.0
    for i in range(int(np.ceil(total / seg_len))):
        ch = chords[i % 4]
        s0, s1 = int(i * seg_len * SR), min(int(((i + 1) * seg_len + 1.2) * SR), n)
        tl = tt[s0:s1] - tt[s0]
        ln = tl[-1] + 1e-3
        env = np.minimum(1, tl / 1.5) * np.minimum(1, (ln - tl) / 1.5)
        for j, f in enumerate(ch + [ch[0] / 2]):
            for det, pan in ((-0.5, 0.3), (0.5, 0.7)):
                w = np.sin(2 * np.pi * (f + det) * tl + j) + 0.2 * np.sin(4 * np.pi * (f + det) * tl)
                out[s0:s1, 0] += w * env * (1 - pan) * 0.05
                out[s0:s1, 1] += w * env * pan * 0.05
    master = np.clip(np.minimum(tt / 1.5, (total - tt) / 2.5), 0, 1)
    out *= master[:, None]
    out /= np.abs(out).max() + 1e-9
    voice = np.zeros(n)
    for st, x in clips:
        s0 = int(st * SR)
        x = x[: n - s0]
        voice[s0:s0 + len(x)] += x
    active = ndimage.maximum_filter1d((np.abs(voice) > 0.01).astype(float), int(SR * 0.6))
    duck = 1 - 0.65 * ndimage.gaussian_filter1d(active, SR * 0.25)
    out = out * 0.35 * duck[:, None] + voice[:, None]
    out /= max(np.abs(out).max(), 1.0)
    out *= 0.95
    out = out[: int(total * SR)]
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((out * 32767).astype(np.int16).tobytes())


# ======================================================================
# 描画ヘルパー
# ======================================================================
_FONTS = {}


def font(size):
    if size not in _FONTS:
        _FONTS[size] = ImageFont.truetype(FONT_PATH, size)
    return _FONTS[size]


def text(d, xy, s, size, fill=C_TEXT, anchor="la", bold=True, spacing=12):
    # IPAゴシックには太字がないので、同色の縁取りで太く見せる
    d.multiline_text(xy, s, font=font(size), fill=fill, anchor=anchor, spacing=spacing, align="center" if anchor[0] == "m" else "left",
                     stroke_width=1 if bold and size >= 30 else 0, stroke_fill=fill)


def wrap(s, size, width):
    out = []
    for para in s.split("\n"):
        line = ""
        for ch in para:
            if font(size).getlength(line + ch) > width and line:
                # 句読点・閉じ括弧は行頭に来ないようにする
                if ch in "、。）」・":
                    out.append(line[:-1])
                    line = line[-1]
                else:
                    out.append(line)
                    line = ""
            line += ch
        out.append(line)
    return "\n".join(out)


def layer(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def shadowed(img, radius=18, alpha=110, pad=30):
    """要素に柔らかい影をつける"""
    out = layer(img.width + pad * 2, img.height + pad * 2)
    a = img.split()[3].point(lambda v: alpha if v > 0 else 0)
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 255), (pad, pad + 8), a)
    sh = sh.filter(ImageFilter.GaussianBlur(radius))
    out.alpha_composite(sh)
    out.alpha_composite(img, (pad, pad))
    return out, pad


def background():
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    k = np.clip(0.55 * y + 0.25 * (1 - x) + 0.1, 0, 1)[..., None]
    arr = np.array(C_BG)[None, None] * k + np.array(C_BG2)[None, None] * (1 - k)
    img = Image.fromarray(arr.astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img, "RGBA")  # RGB画像に RGBA で描くと半透明で重なる
    # うっすらとした斜線模様
    for i in range(-H, W, 70):
        d.line([(i, H), (i + H, 0)], fill=(255, 255, 255, 7), width=2)
    return img.convert("RGBA")


def header(img, s):
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, 150], fill=(10, 18, 34, 200))
    d.rectangle([90, 48, 104, 112], fill=C_ACCENT)
    text(d, (130, 80), s, 56, anchor="lm")
    text(d, (W - 90, 80), "カスハラ防止法", 30, fill=C_SUB, anchor="rm", bold=False)


# ======================================================================
# 場面ごとの要素（RGBA画像＋配置位置）を作る
# ======================================================================
def build_title(sc, end=False):
    els = []
    it = sc["items"][0]
    im = layer(W, 420)
    d = ImageDraw.Draw(im)
    size = 130 if not end else 96
    text(d, (W // 2, 170), it["big"], size, anchor="mm")
    d.rectangle([W // 2 - 140, 270, W // 2 + 140, 278], fill=C_ACCENT)
    text(d, (W // 2, 350), it["sub"], 52 if not end else 50, fill=C_SUB, anchor="mm")
    els.append((im, (0, 230 if not end else 260)))
    it2 = sc["items"][1]
    if "badge" in it2:
        f = font(54)
        tw = int(f.getlength(it2["badge"]))
        im = layer(tw + 120, 110)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, im.width - 1, 109], 55, fill=C_ACCENT)
        text(d, (im.width // 2, 55), it2["badge"], 54, fill=(25, 25, 35), anchor="mm")
        im, pad = shadowed(im)
        els.append((im, (W // 2 - im.width // 2, 700 - pad)))
    else:
        im = layer(W, 60)
        d = ImageDraw.Draw(im)
        text(d, (W // 2, 30), it2["src"], 26, fill=C_SUB, anchor="mm", bold=False)
        els.append((im, (0, 760)))
    return els


def build_facts(sc):
    els = []
    y = 230
    for it in sc["items"]:
        h = 150 if "note" in it else 130
        im = layer(1600, h)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, 1599, h - 1], 24, fill=C_CARD)
        d.rounded_rectangle([0, 0, 300, h - 1], 24, fill=C_ACCENT)
        d.rectangle([270, 0, 300, h - 1], fill=C_ACCENT)
        text(d, (150, h // 2), it["label"], 46, fill=(25, 25, 35), anchor="mm")
        if "note" in it:
            text(d, (350, 52), it["value"], 54, anchor="lm")
            text(d, (352, 112), it["note"], 32, fill=C_SUB, anchor="lm", bold=False)
        else:
            text(d, (350, h // 2), it["value"], 58, anchor="lm")
        im, pad = shadowed(im)
        els.append((im, (160 - pad, y - pad)))
        y += h + 36
    return els


def build_cards(sc, cols):
    els = []
    n = len(sc["items"])
    if cols == 3:
        cw, ch, gap, x0, y0 = 540, 640, 60, (W - (540 * 3 + 60 * 2)) // 2, 230
    else:
        cw, ch, gap, x0, y0 = 800, 320, 50, (W - (800 * 2 + 50)) // 2, 200
    for i, it in enumerate(sc["items"]):
        im = layer(cw, ch)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, cw - 1, ch - 1], 30, fill=C_CARD)
        if cols == 3:
            d.ellipse([cw // 2 - 70, 50, cw // 2 + 70, 190], fill=C_ACCENT)
            text(d, (cw // 2, 120), it["no"], 90, fill=(25, 25, 35), anchor="mm")
            text(d, (cw // 2, 300), it["title"], 52, anchor="mm", spacing=16)
            d.rectangle([60, 390, cw - 60, 394], fill=(255, 255, 255, 40))
            text(d, (50, 425), wrap(it["body"], 36, cw - 100), 36, fill=C_SUB, bold=False, spacing=16)
        else:
            d.ellipse([40, 40, 150, 150], fill=C_ACCENT)
            text(d, (95, 95), it["no"], 70, fill=(25, 25, 35), anchor="mm")
            text(d, (180, 95), it["title"], 56, anchor="lm")
            text(d, (50, 185), wrap(it["body"], 38, cw - 100), 38, fill=C_SUB, bold=False, spacing=16)
        im, pad = shadowed(im)
        r, c = divmod(i, cols)
        els.append((im, (x0 + c * (cw + gap) - pad, y0 + r * (ch + 36) - pad)))
    return els


def build_versus(sc):
    els = []
    cw, ch = 800, 660
    for i, it in enumerate(sc["items"]):
        col = C_NG if it["side"] == "ng" else C_OK
        im = layer(cw, ch)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, cw - 1, ch - 1], 30, fill=C_CARD)
        d.rounded_rectangle([0, 0, cw - 1, 140], 30, fill=col)
        d.rectangle([0, 110, cw - 1, 140], fill=col)
        mark = "×" if it["side"] == "ng" else "○"
        text(d, (cw // 2, 72), f"{mark}  {it['title']}", 60, fill=(255, 255, 255), anchor="mm")
        y = 210
        for ln in it["lines"]:
            if ln.startswith("→"):
                text(d, (60, y), ln, 42, fill=C_OK, anchor="lm")
            else:
                d.ellipse([60, y - 10, 80, y + 10], fill=col)
                text(d, (110, y), ln, 46, anchor="lm")
            y += 118
        im, pad = shadowed(im)
        els.append((im, (W // 2 - cw - 40 + i * (cw + 80) - pad, 220 - pad)))
    return els


def draw_icon(d, kind, cx, cy, col):
    """簡単な図形アイコン（絵文字フォントに頼らない）"""
    d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=col)
    k = (25, 25, 35)
    if kind == "🔒":  # 鍵
        d.arc([cx - 26, cy - 52, cx + 26, cy + 4], 180, 360, fill=k, width=10)
        d.rectangle([cx - 26, cy - 26, cx - 17, cy - 4], fill=k)
        d.rectangle([cx + 17, cy - 26, cx + 26, cy - 4], fill=k)
        d.rounded_rectangle([cx - 38, cy - 6, cx + 38, cy + 46], 8, fill=k)
        d.ellipse([cx - 7, cy + 8, cx + 7, cy + 22], fill=col)
    elif kind == "⚖":  # 盾（守る）
        d.polygon([(cx, cy - 48), (cx + 40, cy - 30), (cx + 34, cy + 18), (cx, cy + 50), (cx - 34, cy + 18), (cx - 40, cy - 30)], fill=k)
        d.line([(cx - 16, cy + 2), (cx - 2, cy + 18), (cx + 20, cy - 14)], fill=col, width=9)
    else:  # ハート（配慮）
        d.ellipse([cx - 40, cy - 34, cx + 2, cy + 8], fill=k)
        d.ellipse([cx - 2, cy - 34, cx + 40, cy + 8], fill=k)
        d.polygon([(cx - 38, cy - 4), (cx + 38, cy - 4), (cx, cy + 42)], fill=k)


def build_list(sc):
    els = []
    y = 200
    for it in sc["items"]:
        im = layer(1640, 210)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, 1639, 219], 30, fill=C_CARD)
        draw_icon(d, it["icon"], 130, 105, it["color"])
        text(d, (250, 74), it["title"], 56, anchor="lm")
        text(d, (252, 150), it["body"], 38, fill=C_SUB, anchor="lm", bold=False)
        im, pad = shadowed(im)
        els.append((im, (140 - pad, y - pad)))
        y += 235
    return els


def build_scene(sc):
    base = BG.copy()
    if sc["head"]:
        header(base, sc["head"])
    k = sc["kind"]
    els = {"title": lambda: build_title(sc), "end": lambda: build_title(sc, end=True), "facts": lambda: build_facts(sc),
           "cards3": lambda: build_cards(sc, 3), "cards4": lambda: build_cards(sc, 2),
           "versus": lambda: build_versus(sc), "list": lambda: build_list(sc)}[k]()
    return base, els


# ======================================================================
# フレーム合成
# ======================================================================
def ease(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def subtitle_img(s):
    fs = 44
    s = wrap(s, fs, 1760)
    lines = s.count("\n") + 1
    h = 34 + lines * (fs + 14)
    im = layer(W, h)
    d = ImageDraw.Draw(im)
    tw = max(font(fs).getlength(ln) for ln in s.split("\n"))
    d.rounded_rectangle([W // 2 - tw / 2 - 36, 0, W // 2 + tw / 2 + 36, h], 18, fill=(0, 0, 0, 170))
    d.multiline_text((W // 2, h // 2), s, font=font(fs), fill=(255, 255, 255), anchor="mm", align="center", spacing=14,
                     stroke_width=1, stroke_fill=(255, 255, 255))
    return im


class Renderer:
    def __init__(self, timeline, total):
        self.timeline, self.total = timeline, total
        self.scenes = [build_scene(sc) for sc in SCENES]
        self.subs = [[subtitle_img(sg["text"]) for sg in tl["segs"]] for tl in timeline]
        # 各要素を表示し始める時刻（その要素数に達した文の開始秒）
        self.reveal = []
        for sc, tl in zip(SCENES, timeline):
            rv = [None] * len(sc["items"])
            for sg in tl["segs"]:
                for k in range(sg["step"]):
                    if rv[k] is None:
                        rv[k] = sg["t0"] - 0.15
            self.reveal.append([r if r is not None else tl["t0"] + 0.3 for r in rv])
        cred = layer(W, 40)
        ImageDraw.Draw(cred).text((W - 30, 20), "音声: HTS Voice Mei © 名古屋工業大学 (CC BY 3.0)", font=font(20),
                                  fill=(200, 210, 230, 150), anchor="rm")
        self.credit = cred

    def scene_frame(self, si, t):
        base, els = self.scenes[si]
        img = base.copy()
        for (im, (x, y)), r in zip(els, self.reveal[si]):
            a = ease((t - r) / 0.5)
            if a <= 0:
                continue
            dy = int((1 - a) * 40)
            if a < 1:
                im = im.copy()
                im.putalpha(im.getchannel("A").point(lambda v, a=a: int(v * a)))
            img.alpha_composite(im, (x, y + dy))
        return img

    def frame(self, t):
        si = next((i for i, tl in enumerate(self.timeline) if t < tl["t1"]), len(self.timeline) - 1)
        tl = self.timeline[si]
        img = self.scene_frame(si, t)
        # 場面の切り替え: 前の場面からクロスフェード
        if si > 0 and t - tl["t0"] < 0.45:
            prev = self.scene_frame(si - 1, t).convert("RGB")
            img = Image.blend(prev, img.convert("RGB"), ease((t - tl["t0"]) / 0.45)).convert("RGBA")
        # 字幕
        for sg, sub in zip(tl["segs"], self.subs[si]):
            if sg["t0"] - 0.1 <= t <= sg["t1"] + 0.25:
                a = min(1.0, (t - sg["t0"] + 0.1) / 0.15, (sg["t1"] + 0.25 - t) / 0.15)
                s = sub
                if a < 1:
                    s = sub.copy()
                    s.putalpha(s.getchannel("A").point(lambda v, a=a: int(v * max(a, 0))))
                img.alpha_composite(s, (0, H - 70 - sub.height))
        # 進行バー
        d = ImageDraw.Draw(img)
        d.rectangle([0, H - 10, W, H], fill=(255, 255, 255, 30))
        d.rectangle([0, H - 10, int(W * t / self.total), H], fill=C_ACCENT)
        img.alpha_composite(self.credit, (0, H - 52))
        return img.convert("RGB")


BG = None


def main():
    global BG
    os.makedirs(CACHE, exist_ok=True)
    BG = background()
    clips, timeline, total = synth_all()
    print(f"total: {total:.1f}s", flush=True)
    r = Renderer(timeline, total)
    if "--preview" in sys.argv:
        for i, tl in enumerate(timeline):
            r.frame(tl["t1"] - 0.5).save(os.path.join(HERE, f"preview_{i}.png"))
            sg = tl["segs"][-1]
            r.frame((sg["t0"] + sg["t1"]) / 2).save(os.path.join(HERE, f"preview_{i}s.png"))
        return
    wav = os.path.join(CACHE, "audio.wav")
    make_audio(wav, clips, total)
    silent = os.path.join(CACHE, "video.mp4")
    writer = imageio_ffmpeg.write_frames(silent, (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                         quality=None, bitrate=None, macro_block_size=1,
                                         output_params=["-crf", "20", "-preset", "medium", "-tune", "stillimage"])
    writer.send(None)
    n = int(total * FPS)
    for i in range(n):
        writer.send(r.frame(i / FPS).tobytes())
        if i % 300 == 0:
            print(f"{i}/{n}", flush=True)
    writer.close()
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.check_call([ff, "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", OUT])
    print("done:", OUT)


if __name__ == "__main__":
    main()
