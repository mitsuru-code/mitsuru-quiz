# 豆知識動画の挿絵（PILで描くアニメーション図解）。draw(name, lt) → 1000x600 RGBA
import math
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import fonts

IW, IH = 1000, 600
GOLD, CORAL, MINT, CREAM = (255, 200, 90), (255, 122, 92), (110, 225, 190), (248, 244, 232)
BLUE, GRAY, DARK = (120, 150, 255), (110, 118, 140), (30, 38, 62)

@lru_cache(None)
def F(size, bold=True): return fonts.font("YuGothB.ttc" if bold else "YuGothM.ttc", size)
@lru_cache(None)
def MONO(size): return fonts.font("consola.ttf", size)

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def prog(t, a, b): return clamp((t - a) / (b - a))
def eo(x): return 1 - (1 - x) ** 3
def eback(x):
    c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2
def A(col, a): return col + (int(255 * clamp(a)),)

def text(d, xy, s, size, col, a=1.0, bold=True, anchor="mm"):
    if a > 0.01: d.text(xy, s, font=F(size, bold), fill=A(col, a), anchor=anchor)

def person(d, x, y, s, col, a=1.0):
    d.ellipse((x - .42 * s, y - 1.55 * s, x + .42 * s, y - .71 * s), fill=A(col, a))
    d.rounded_rectangle((x - .62 * s, y - .6 * s, x + .62 * s, y + .9 * s), int(.35 * s), fill=A(col, a))

def arrow(d, x1, y1, x2, y2, col, a=1.0, w=7, dash=False):
    L = math.hypot(x2 - x1, y2 - y1); ux, uy = (x2 - x1) / L, (y2 - y1) / L
    if dash:
        t = 0
        while t < L - 24:
            e = min(t + 18, L - 24)
            d.line((x1 + ux * t, y1 + uy * t, x1 + ux * e, y1 + uy * e), fill=A(col, a), width=w); t += 32
    else:
        d.line((x1, y1, x2 - ux * 20, y2 - uy * 20), fill=A(col, a), width=w)
    px, py = -uy, ux
    d.polygon([(x2, y2), (x2 - ux * 30 + px * 16, y2 - uy * 30 + py * 16), (x2 - ux * 30 - px * 16, y2 - uy * 30 - py * 16)], fill=A(col, a))

def helix(d, lt, x0, x1, cy, amp, tags=0.0, reveal=1.0, width=9):
    """DNA二重らせん。tags>0 でメチル基（オレンジの目印）を出す"""
    ph = lt * 2.2; xe = x0 + (x1 - x0) * reveal
    s1, s2 = [], []
    for x in range(int(x0), int(xe) + 1, 5):
        s1.append((x, cy + amp * math.sin(x / 62 + ph))); s2.append((x, cy + amp * math.sin(x / 62 + ph + math.pi)))
    cols = [GOLD, MINT, CORAL, BLUE]
    for i, x in enumerate(range(int(x0) + 10, int(xe), 30)):
        y1, y2 = cy + amp * math.sin(x / 62 + ph), cy + amp * math.sin(x / 62 + ph + math.pi)
        depth = 0.45 + 0.55 * abs(math.cos(x / 62 + ph))
        d.line((x, y1, x, y2), fill=A(cols[i % 4], 0.85 * depth), width=6)
    if len(s1) > 1:
        d.line(s1, fill=A(CREAM, 1), width=width, joint="curve"); d.line(s2, fill=A((170, 180, 215), 1), width=width, joint="curve")
    tagpos = []
    if tags > 0:
        for k, x in enumerate(range(int(x0) + 40, int(xe), 90)):
            p = eback(prog(tags, k * 0.12, k * 0.12 + 0.35))
            if p <= 0.01: continue
            y = cy + amp * math.sin(x / 62 + ph)
            r = 15 * p
            d.ellipse((x - r, y - r - 18, x + r, y + r - 18), fill=A(CORAL, 1), outline=A(CREAM, 1), width=3)
            d.line((x, y - 3, x, y - 18 + r), fill=A(CORAL, 1), width=4)
            tagpos.append((x, y - 18))
    return tagpos

def i_dna(d, lt):
    helix(d, lt, 90, 910, 300, 120, reveal=eo(prog(lt, 0, 0.9)))
    text(d, (500, 520), "DNA（二重らせん）", 40, CREAM, prog(lt, 0.6, 1.0))

def i_dna_tags(d, lt):
    tp = helix(d, lt, 90, 910, 290, 115, tags=prog(lt, 0.4, 2.4), reveal=eo(prog(lt, 0, 0.7)))
    a = prog(lt, 1.2, 1.6)
    if tp and a > 0:
        x, y = tp[0]
        d.line((x, y - 20, 250, 90), fill=A(CORAL, a), width=3)
        text(d, (330, 70), "メチル基＝目印", 40, CORAL, a)
    text(d, (500, 540), "目印がつくと、その遺伝子は働きにくくなる", 36, CREAM, prog(lt, 1.8, 2.2), bold=False)

def i_switch(d, lt):
    rows = [("遺伝子A", 170), ("遺伝子B", 390)]
    flip = int(lt / 1.8) % 2
    for i, (name, y) in enumerate(rows):
        a = eo(prog(lt, 0.1 + i * 0.25, 0.5 + i * 0.25))
        on = (i == 0) ^ bool(flip)
        d.rounded_rectangle((90, y - 60, 380, y + 60), 24, fill=A(DARK, a), outline=A(BLUE, a), width=4)
        text(d, (235, y), name, 46, CREAM, a)
        d.rounded_rectangle((450, y - 38, 590, y + 38), 38, fill=A(MINT if on else GRAY, a))
        kx = 552 if on else 488
        d.ellipse((kx - 30, y - 30, kx + 30, y + 30), fill=A(CREAM, a))
        text(d, (520, y + 70), "ON" if on else "OFF", 30, MINT if on else GRAY, a)
        bx = 800
        if on:
            for r, al in ((95, .15), (75, .3)): d.ellipse((bx - r, y - r, bx + r, y + r), fill=A(GOLD, a * al))
        d.ellipse((bx - 55, y - 55, bx + 55, y + 55), fill=A(GOLD if on else (70, 76, 96), a))
        text(d, (bx, y), "働く" if on else "休む", 34, DARK if on else GRAY, a)
    text(d, (500, 560), "配列は同じ。変わるのはスイッチ", 36, CREAM, prog(lt, 1.0, 1.4), bold=False)

def i_book(d, lt):
    a = eo(prog(lt, 0, 0.5))
    d.polygon([(110, 110), (490, 140), (490, 500), (110, 470)], fill=A((236, 232, 220), a))
    d.polygon([(510, 140), (890, 110), (890, 470), (510, 500)], fill=A((236, 232, 220), a))
    d.line((500, 135, 500, 505), fill=A((150, 150, 160), a), width=6)
    seq = "ATGCCGTAGCTTAGGCATCG"
    for r in range(7):
        y = 180 + r * 42
        d.text((140, y), (seq[r:] + seq[:r])[:17], font=MONO(28), fill=A((80, 90, 110), a))
        d.text((540, y + 6), (seq[-r:] + seq[:-r])[:17], font=MONO(28), fill=A((80, 90, 110), a))
    p1 = eback(prog(lt, 0.6, 1.0))
    if p1 > 0:
        d.rounded_rectangle((160, 110 - 70 * p1, 260, 150), 8, fill=A(MINT, 1)); text(d, (210, 110 - 30 * p1), "読む", 30, DARK)
    p2 = prog(lt, 1.1, 1.6)
    if p2 > 0:
        d.polygon([(510, 140), (890, 110), (890, 470), (510, 500)], fill=(20, 26, 44, int(110 * p2)))
        d.rounded_rectangle((760, 60 + 50 * (1 - eo(p2)), 870, 130), 8, fill=A(CORAL, p2)); text(d, (815, 100), "閉じる", 28, DARK, p2)
    text(d, (500, 560), "DNA＝設計図　　目印＝付せん", 40, CREAM, prog(lt, 1.4, 1.8))

def snow(d, x, y, r, a):
    for k in range(3):
        ang = k * math.pi / 3
        d.line((x - r * math.cos(ang), y - r * math.sin(ang), x + r * math.cos(ang), y + r * math.sin(ang)), fill=A(CREAM, a), width=4)

def i_hunger(d, lt):
    a = eo(prog(lt, 0, 0.5))
    d.rounded_rectangle((60, 90, 420, 500), 30, fill=A(DARK, a), outline=A(BLUE, a), width=4)
    text(d, (240, 150), "1944〜45年", 44, GOLD, a); text(d, (240, 205), "オランダ「飢餓の冬」", 32, CREAM, a, bold=False)
    for k, (x, y) in enumerate([(120, 260), (360, 250), (300, 300), (160, 330)]):
        snow(d, x, y + 10 * math.sin(lt * 2 + k), 16, a * .8)
    d.chord((150, 330, 330, 470), 0, 180, fill=A((200, 205, 220), a)); d.ellipse((150, 380, 330, 420), fill=A((120, 125, 145), a))
    text(d, (240, 480), "空っぽの皿", 26, CREAM, a, bold=False)
    p = eo(prog(lt, 0.9, 1.6))
    if p > 0: arrow(d, 440, 295, 440 + 120 * p, 295, GOLD, 1, 9)
    text(d, (500, 250), "約60年", 30, GOLD, prog(lt, 1.2, 1.6))
    b = eo(prog(lt, 1.5, 2.1))
    if b > 0:
        person(d, 720, 260, 110, (150, 170, 230), b)
        d.rounded_rectangle((600, 400, 840, 440), 18, fill=A((170, 180, 215), b))
        for k, x in enumerate((640, 700, 770)):
            if lt > 1.9 + k * 0.2: d.ellipse((x - 15, 405, x + 15, 435), fill=A(CORAL, b))
        text(d, (720, 490), "遺伝子の目印に違い", 32, CREAM, b)
    text(d, (500, 570), "胎内で経験した環境が、長く残った可能性", 32, CREAM, prog(lt, 2.4, 2.8), bold=False)

def i_twins(d, lt):
    age = int(60 * prog(lt, 0.8, 3.2))
    for i, x in enumerate((300, 700)):
        a = eo(prog(lt, i * 0.2, 0.5 + i * 0.2))
        person(d, x, 250, 105, (150, 170, 230) if i == 0 else (130, 200, 190), a)
        text(d, (x, 45), "双子A" if i == 0 else "双子B", 34, CREAM, a)
        d.rounded_rectangle((x - 150, 380, x + 150, 420), 18, fill=A((170, 180, 215), a))
        same = [x - 110, x - 40, x + 30]
        for k, dx in enumerate(same): d.ellipse((dx - 13, 387, dx + 13, 413), fill=A(GOLD, a))
        if i == 1:
            extra = [x + 100, x - 80, x + 65, x - 135]
            for k, dx in enumerate(extra):
                if age > 12 + k * 12: d.ellipse((dx - 13, 387, dx + 13, 413), fill=A(CORAL, 1))
    text(d, (500, 250), "同じDNA", 30, GOLD, prog(lt, 0.4, 0.8))
    text(d, (500, 480), f"{age}歳", 52, CREAM, prog(lt, 0.6, 0.9))
    text(d, (500, 560), "年を重ねるほど、目印の違いが広がる", 34, CREAM, prog(lt, 2.2, 2.6), bold=False)

def i_generations(d, lt):
    pos = [(170, "親", 120), (500, "子", 95), (830, "孫", 80)]
    for i, (x, lab, s) in enumerate(pos):
        a = eo(prog(lt, i * 0.6, i * 0.6 + 0.4))
        person(d, x, 260, s, (150, 170, 230), a)
        text(d, (x, 420), lab, 44, CREAM, a)
    p1 = eo(prog(lt, 0.4, 0.9))
    if p1 > 0: arrow(d, 250, 250, 250 + 170 * p1, 250, GOLD, 1, 9)
    text(d, (335, 190), "伝わることも", 30, GOLD, prog(lt, 0.8, 1.1))
    p2 = eo(prog(lt, 1.0, 1.5))
    if p2 > 0: arrow(d, 575, 250, 575 + 180 * p2, 250, GRAY, 1, 8, dash=True)
    q = eback(prog(lt, 1.5, 1.9))
    if q > 0: text(d, (830, 120 - 8 * math.sin(lt * 4)), "？", int(90 * q) + 1, CORAL)
    text(d, (665, 190), "まだ研究中", 30, GRAY, prog(lt, 1.4, 1.7))
    text(d, (500, 540), "孫の代まで続くかは、議論が続いている", 34, CREAM, prog(lt, 2.0, 2.4), bold=False)

def i_family_q(d, lt):
    for i, (x, s) in enumerate(((330, 115), (520, 105), (690, 80))):
        person(d, x, 330, s, [(150, 170, 230), (230, 160, 170), (130, 200, 190)][i], eo(prog(lt, i * 0.2, 0.4 + i * 0.2)))
    q = eback(prog(lt, 0.7, 1.1))
    if q > 0: text(d, (840, 170 - 10 * math.sin(lt * 4)), "？", int(130 * q) + 1, GOLD)
    text(d, (500, 540), "似ているのは、DNAの配列だけ？", 36, CREAM, prog(lt, 1.0, 1.4))

def i_chat(d, lt):
    person(d, 300, 330, 110, (150, 170, 230), eo(prog(lt, 0, 0.4)))
    person(d, 700, 330, 110, (230, 160, 170), eo(prog(lt, 0.2, 0.6)))
    for i, (x, y, s) in enumerate(((330, 110, "へえ！"), (670, 150, "スイッチ？"))):
        p = eback(prog(lt, 0.6 + i * 0.5, 1.0 + i * 0.5))
        if p > 0:
            w = 190 * p
            d.rounded_rectangle((x - w / 2, y - 45 * p, x + w / 2, y + 45 * p), int(30 * p) + 1, fill=A(CREAM, 1))
            text(d, (x, y), s, max(1, int(36 * p)), DARK)

LIB = {"dna": i_dna, "dna_tags": i_dna_tags, "switch": i_switch, "book": i_book, "hunger": i_hunger,
       "twins": i_twins, "generations": i_generations, "family_q": i_family_q, "chat": i_chat}

def draw(name, lt):
    lay = Image.new("RGBA", (IW, IH)); d = ImageDraw.Draw(lay)
    LIB[name](d, lt)
    g = lay.resize((IW // 3, IH // 3), Image.BILINEAR).filter(ImageFilter.GaussianBlur(4)).resize((IW, IH), Image.BILINEAR)
    g.putalpha(g.getchannel("A").point(lambda v: int(v * 0.7)))
    out = Image.new("RGBA", (IW, IH)); out.alpha_composite(g); out.alpha_composite(lay)
    return out
