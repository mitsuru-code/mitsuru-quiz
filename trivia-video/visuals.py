# 場面の絵: ②手作り画像（Googleドライブ「豆知識素材/<フォルダ>」）→ 挿絵(illust) → ①絵文字 の優先順で決める
import glob, math, os
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageOps
import illust

DRIVE_ROOTS = [f"{dl}:\\{m}" for dl in "GHIJKLMNOPQRSTUVWXYZDEF" for m in ("マイドライブ", "My Drive")]
def drive_root():
    return next((r for r in DRIVE_ROOTS if os.path.isdir(r)), None)
# クラウドでは TRIVIA_SOZAI_DIR（ダウンロードした素材の場所）と TRIVIA_EMOJI_FONT で上書きする
SOZAI = lambda: os.environ.get("TRIVIA_SOZAI_DIR") or os.path.join(drive_root() or "", "豆知識素材")
EMOJI_FONT = lambda: os.environ.get("TRIVIA_EMOJI_FONT") or os.path.join(SOZAI(), "_素材フォント", "NotoColorEmoji.ttf")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
BOX_W, BOX_H = 940, 600

def scene_keys(script):
    return ["hook", "intro", "question", "conclusion"] + [f"point{i}" for i in range(len(script["points"]))] + ["share"]

def load_images(script):
    """豆知識素材/<imageFolder> の画像を、アップロード順に imagePrompts の場面へ割り当てる"""
    folder = script.get("imageFolder")
    base = SOZAI()
    if not folder or not os.path.isdir(base): return {}
    d = os.path.join(base, folder)
    if not os.path.isdir(d): d = os.path.join(base, "取り込み済み", folder)  # 作り直し時は移動済みの素材を使う
    files = sorted((f for f in glob.glob(os.path.join(d, "*")) if f.lower().endswith(IMG_EXT)), key=lambda f: (int(os.path.getmtime(f)), os.path.basename(f)))  # 同時刻に同期された分はファイル名順
    scenes = [p.get("scene") for p in script.get("imagePrompts") or [] if p.get("scene")]
    scenes += [k for k in ("hook", "conclusion", "point0", "point1", "point2", "share") if k not in scenes]
    return dict(zip(scenes, [_local_copy(f, folder) for f in files]))

def _local_copy(src, folder):
    """Googleドライブの画像は同期中だと読めないことがあるので、PCへコピーしてから使う（最大約2分再試行）"""
    import shutil, time
    dst_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img_cache", folder)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    for k in range(24):
        try:
            shutil.copyfile(src, dst)
            Image.open(dst).verify()
            return dst
        except OSError:
            time.sleep(5)
    raise OSError(f"画像を読み込めませんでした: {os.path.basename(src)}")

def emoji_of(script, key):
    e = script.get("emoji") or {}
    if key.startswith("point"):
        pts = e.get("points") or []
        i = int(key[5:])
        v = pts[i] if i < len(pts) else script["points"][i].get("emoji")
    else:
        v = e.get(key)
    return str(v or "").strip()[:6]

def choose(script, key, images):
    """(種類, 値) を返す。無ければ None"""
    if key in images: return ("image", images[key])
    il = script["points"][int(key[5:])].get("illust") if key.startswith("point") else (script.get("illust") or {}).get(key)
    if il in illust.LIB: return ("illust", il)
    em = emoji_of(script, key)
    if em and os.path.exists(EMOJI_FONT()): return ("emoji", em)
    return None

@lru_cache(None)
def _photo(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im = ImageOps.fit(im, (int(BOX_W * 1.12), int(BOX_H * 1.12)), Image.LANCZOS)
    return im

@lru_cache(None)
def _mask():
    m = Image.new("L", (BOX_W, BOX_H), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, BOX_W - 1, BOX_H - 1), 36, fill=255)
    return m

def photo_card(path, lt):
    big = _photo(path)
    z = 1.12 - 0.1 * min(1, lt / 6)  # ゆっくりズームアウト
    w, h = int(BOX_W * z), int(BOX_H * z)
    im = big.resize((w, h), Image.BILINEAR).crop(((w - BOX_W) // 2, (h - BOX_H) // 2, (w - BOX_W) // 2 + BOX_W, (h - BOX_H) // 2 + BOX_H))
    card = Image.new("RGBA", (BOX_W + 12, BOX_H + 12), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, BOX_W + 11, BOX_H + 11), 42, fill=(255, 255, 255, 60))
    im = im.convert("RGBA"); im.putalpha(_mask())
    card.alpha_composite(im, (6, 6))
    return card

@lru_cache(None)
def _emoji(ch):
    f = ImageFont.truetype(EMOJI_FONT(), 109)  # CBDTカラー絵文字は109pxのみ
    im = Image.new("RGBA", (220, 160)); ImageDraw.Draw(im).text((10, 10), ch, font=f, embedded_color=True)
    bb = im.getbbox()
    return im.crop(bb) if bb else im

def split_emoji(s):
    # 異体字セレクタ・ZWJ結合を1つの絵文字として扱う
    out, cur = [], ""
    for c in s:
        if cur and (c in "️‍" or cur.endswith("‍") or 0x1F3FB <= ord(c) <= 0x1F3FF):
            cur += c
        else:
            if cur: out.append(cur)
            cur = c
    if cur: out.append(cur)
    return [e for e in out if e.strip()][:3]

def emoji_row(s, lt):
    items = split_emoji(s)
    lay = Image.new("RGBA", (illust.IW, illust.IH))
    n = len(items)
    for i, ch in enumerate(items):
        p = illust.eback(illust.prog(lt, i * 0.18, i * 0.18 + 0.45))
        if p <= 0.01: continue
        size = (300 if n == 1 else 240 if n == 2 else 210) * p
        e = _emoji(ch).resize((max(1, int(size)), max(1, int(size * _emoji(ch).height / _emoji(ch).width))), Image.LANCZOS)
        cx = illust.IW / 2 + (i - (n - 1) / 2) * (310 if n > 1 else 0)
        cy = illust.IH / 2 + 12 * math.sin(lt * 2.4 + i)
        lay.alpha_composite(e, (int(cx - e.width / 2), int(cy - e.height / 2)))
    return lay

def render(vis, lt):
    kind, val = vis
    if kind == "image": return photo_card(val, lt)
    if kind == "illust": return illust.draw(val, lt)
    return emoji_row(val, lt)
