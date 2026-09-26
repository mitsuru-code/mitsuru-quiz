"""日本列島のなりたち（約3000万年前→現在）を1分動画にするスクリプト（高精細版）。

使い方:
    pip install matplotlib numpy shapely scipy pillow imageio-ffmpeg pyopenjtalk
    python3 make_video.py            # japan_formation.mp4 を出力（1920x1080 / 30fps / 60秒 / BGM・ナレーション付き）
    python3 make_video.py --audio-only  # 映像は .cache/video.mp4 を再利用し、音だけ作り直す
    python3 make_video.py --preview  # 各シーンの静止画だけ出力

素材（初回に自動取得し .cache/ に保存）:
    - 海岸線・水深: Natural Earth 10m land / bathymetry（パブリックドメイン）
    - 陰影起伏図: Natural Earth Shaded Relief（basemap-data 同梱版、パブリックドメイン）
    - ナレーション音声: Open JTalk + HTS voice tohoku-f01（東北大学, CC BY 4.0）

復元は教育用の簡略モデル:
    - 観音開き説: 西南日本 時計回り約45°、東北日本 反時計回り約30°（約2000万〜1500万年前）
    - 東北海道は千島弧側から衝突、伊豆は南から北上して本州に衝突（約100万年前）
    - 約1500万年前の水没・フォッサマグナ、その後の隆起は「海岸からの距離」で近似
    - 最終氷期の陸化域は水深200m等深線より浅い範囲で近似
"""
import glob
import json
import math
import multiprocessing as mp
import os
import subprocess
import sys
import urllib.request
import wave
import zipfile

import imageio_ffmpeg
import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon as MplPolygon, Rectangle  # noqa: E402
from matplotlib.transforms import Affine2D  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from scipy import ndimage  # noqa: E402
from shapely.affinity import affine_transform  # noqa: E402
from shapely.geometry import LineString, Polygon, box, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT = os.path.join(HERE, "japan_formation.mp4")
NE_RAW = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"

W, H, FPS, DURATION = 1920, 1080, 30, 60
SCALE = W / 1280  # 文字サイズ基準
# ラスタ座標系（全レイヤ共通）
R_LON0, R_LON1, R_LAT0, R_LAT1, RES = 95.0, 170.0, 15.0, 58.0, 0.02
RW, RH = int(round((R_LON1 - R_LON0) / RES)), int(round((R_LAT1 - R_LAT0) / RES))
KX = math.cos(math.radians(36))  # 経度方向の縮尺補正

for f in font_manager.findSystemFonts():
    if "ipag" in os.path.basename(f).lower():
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = ["IPAPGothic", "IPAGothic", "sans-serif"]

# ---------- 配色 ----------
C_BG = "#07182c"
C_PANEL = "#0a1d33"
C_GOLD = "#ffd27a"
C_SW = "#ff9d3c"
C_NE = "#4fd17a"
C_EH = "#b58cff"
C_IZU = "#ff5f7a"
C_SHALLOW = np.array([0.55, 0.80, 0.86])
C_SHELF = np.array([0.80, 0.76, 0.56])
DEPTH_COLORS = [  # (水深ファイル, 色)
    (None, "#8fc3dc"), ("K_200", "#5f9fc7"), ("J_1000", "#4a88b8"), ("I_2000", "#3b76a9"),
    ("H_3000", "#2f6497"), ("G_4000", "#255484"), ("F_5000", "#1c4470"), ("E_6000", "#15355b"),
    ("D_7000", "#0f2848"), ("C_8000", "#0a1d37"),
]


# ======================================================================
# 素材の取得
# ======================================================================
def fetch(name, url):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        print("download:", url, flush=True)
        urllib.request.urlretrieve(url, path)
    return path


def relief_image():
    path = os.path.join(CACHE, "shadedrelief.jpg")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps",
                               "basemap-data==2.0.0", "-d", CACHE])
        whl = glob.glob(os.path.join(CACHE, "basemap_data-*.whl"))[0]
        with zipfile.ZipFile(whl) as z, open(path, "wb") as fp:
            fp.write(z.read("mpl_toolkits/basemap_data/shadedrelief.jpg"))
        os.remove(whl)
    return path


def load_polys(geojson_path, clip):
    with open(geojson_path, encoding="utf-8") as fp:
        gj = json.load(fp)
    out = []
    for feat in gj["features"]:
        g = shape(feat["geometry"])
        if not g.intersects(clip):
            continue
        g = g.intersection(clip)
        out.extend(p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon")
    return out


# ======================================================================
# 陸塊の分類
# ======================================================================
ISTL_WEST = Polygon([(137.2, 50), (137.86, 37.04), (138.1, 36.05), (138.38, 34.97), (138.6, 29.0),
                     (120, 29.0), (120, 50)])  # 糸魚川－静岡構造線より西
HIDAKA_EAST = Polygon([(142.0, 47), (142.4, 43.3), (143.25, 41.9), (143.4, 40.0), (160, 40), (160, 47)])
IZU_BOX = Polygon([(138.68, 35.12), (139.2, 35.12), (139.2, 34.55), (141.5, 34.55), (141.5, 29.0),
                   (138.68, 29.0)])


def classify(polys):
    cont, jp, static = [], [], []
    for p in polys:
        c = p.representative_point()
        lon, lat = c.x, c.y
        in_jp = ((lon >= 128.0 and 29.8 <= lat < 34.0) or (129.15 <= lon and 34.0 <= lat < 41.5)
                 or (139.3 <= lon <= 149.8 and 41.5 <= lat <= 45.8)) and not (lon > 141.2 and lat > 45.6)
        ryukyu = lon > 122 and lat < 30.2
        ogasawara = lon > 141.0 and lat < 29.0
        if in_jp:
            jp.append(p)
        elif ryukyu or ogasawara:
            static.append(p)
        else:
            cont.append(p)
    japan = unary_union(jp)
    izu = japan.intersection(IZU_BOX)
    rest = japan.difference(IZU_BOX)
    sw = rest.intersection(ISTL_WEST)
    rest = rest.difference(ISTL_WEST)
    eh = rest.intersection(HIDAKA_EAST)
    ne = rest.difference(HIDAKA_EAST)
    return dict(cont=unary_union(cont), static=unary_union(static), sw=sw, ne=ne, eh=eh, izu=izu)


# ======================================================================
# ラスタ化
# ======================================================================
def to_px(coords):
    return [((x - R_LON0) / RES, (R_LAT1 - y) / RES) for x, y in coords]


def rasterize(geoms, size=(RW, RH), offset=(0, 0)):
    img = Image.new("L", size, 0)
    d = ImageDraw.Draw(img)
    ox, oy = offset
    for g in geoms:
        for p in getattr(g, "geoms", [g]):
            if p.is_empty or p.geom_type != "Polygon":
                continue
            d.polygon([(x - ox, y - oy) for x, y in to_px(p.exterior.coords)], fill=255)
            for hole in p.interiors:
                d.polygon([(x - ox, y - oy) for x, y in to_px(hole.coords)], fill=0)
    return np.asarray(img) > 127


def build_layers():
    view = box(R_LON0, R_LAT0, R_LON1, R_LAT1)
    land = load_polys(fetch("land10.geojson", NE_RAW + "ne_10m_land.geojson"), view)
    blocks = classify(land)

    # 陰影起伏図をラスタ座標へ
    Image.MAX_IMAGE_PIXELS = None
    rel = Image.open(relief_image()).convert("RGB")
    sw_, sh_ = rel.size
    crop = rel.crop((int((R_LON0 + 180) / 360 * sw_), int((90 - R_LAT1) / 180 * sh_),
                     int((R_LON1 + 180) / 360 * sw_), int((90 - R_LAT0) / 180 * sh_)))
    relief = np.asarray(crop.resize((RW, RH), Image.BICUBIC)).astype(np.float32) / 255
    # 少しコントラストと彩度を上げる
    g = relief.mean(axis=2, keepdims=True)
    relief = np.clip((relief - g) * 1.25 + (g - 0.5) * 1.15 + 0.5, 0, 1)

    # 海（水深段彩）
    ocean = Image.new("RGB", (RW, RH), DEPTH_COLORS[0][1])
    deep200 = None
    for name, col in DEPTH_COLORS[1:]:
        polys = load_polys(fetch(f"bathy_{name}.geojson", NE_RAW + f"ne_10m_bathymetry_{name}.geojson"), view)
        m = rasterize(polys)
        if name == "K_200":
            deep200 = m
        ocean.paste(Image.new("RGB", (RW, RH), col), mask=Image.fromarray((m * 255).astype(np.uint8)))
    # 現在の日本列島の足跡は「元からあった海」に見えるよう中深度で塗る
    jp_now = unary_union([blocks["sw"], blocks["ne"], blocks["eh"], blocks["izu"]])
    foot = rasterize([jp_now.buffer(0.25)])
    ocean.paste(Image.new("RGB", (RW, RH), "#3b76a9"),
                mask=Image.fromarray((foot * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)))
    ocean = np.asarray(ocean.filter(ImageFilter.GaussianBlur(3))).astype(np.float32) / 255
    rng = np.random.default_rng(1)
    noise = ndimage.gaussian_filter(rng.standard_normal((RH, RW)), 6)
    ocean = np.clip(ocean * (1 + 0.35 * noise[..., None] / noise.std() * 0.08), 0, 1)

    cont_mask = rasterize([blocks["cont"], blocks["static"]])
    base = ocean.copy()
    soft = ndimage.gaussian_filter(cont_mask.astype(np.float32), 0.7)[..., None]
    base = base * (1 - soft) + relief * soft
    # 海岸のにじみ（浅瀬の明るい縁）
    glow = ndimage.gaussian_filter(cont_mask.astype(np.float32), 5)[..., None] * (1 - soft)
    base = np.clip(base + glow * 0.18, 0, 1)

    shelf = (~deep200) & (~cont_mask)
    shelf = ndimage.gaussian_filter(shelf.astype(np.float32), 1.2)

    # 各陸塊のテクスチャ・海岸からの距離（隆起/水没の近似）
    fossa = Polygon([(137.86, 37.9), (137.86, 37.04), (138.1, 36.05), (138.38, 34.97), (138.3, 34.3),
                     (139.9, 34.8), (140.3, 35.7), (139.5, 37.1), (139.4, 38.3)])
    tiles = {}
    for key in ("sw", "ne", "eh", "izu"):
        geom = blocks[key]
        x0, y0, x1, y1 = geom.bounds
        c0 = max(int((x0 - R_LON0) / RES) - 4, 0)
        c1 = min(int((x1 - R_LON0) / RES) + 5, RW)
        r0 = max(int((R_LAT1 - y1) / RES) - 4, 0)
        r1 = min(int((R_LAT1 - y0) / RES) + 5, RH)
        mask = rasterize([geom], size=(c1 - c0, r1 - r0), offset=(c0, r0))
        dist = ndimage.distance_transform_edt(mask)
        fmask = rasterize([fossa], size=(c1 - c0, r1 - r0), offset=(c0, r0)) & mask
        fmask = ndimage.gaussian_filter(fmask.astype(np.float32), 3)
        alpha = ndimage.gaussian_filter(mask.astype(np.float32), 0.6)
        tiles[key] = dict(
            rgb=relief[r0:r1, c0:c1].copy(), alpha=alpha, dist=dist, fossa=fmask,
            extent=(R_LON0 + c0 * RES, R_LON0 + c1 * RES, R_LAT1 - r1 * RES, R_LAT1 - r0 * RES),
        )
    outlines = {k: blocks[k].simplify(0.01) for k in ("sw", "ne", "eh", "izu")}
    simple = {k: blocks[k].simplify(0.05).buffer(0.05) for k in ("sw", "ne", "eh", "izu")}
    return dict(base=base, shelf=shelf, tiles=tiles, outlines=outlines, simple=simple,
                cont=blocks["cont"].simplify(0.02))


# ======================================================================
# 運動モデル
# ======================================================================
def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def seg(t, a, b):
    return ease((t - a) / (b - a))


# 陸塊ごとの「過去の姿勢」: 回転中心(lon,lat)、角度(°, 反時計回り正)、平行移動(lon,lat)
PAST = {
    "sw": dict(pivot=(129.6, 34.0), angle=45.0, shift=(-2.4, 1.0)),
    "ne": dict(pivot=(142.5, 44.5), angle=-30.0, shift=(-2.8, 2.0)),
    "eh": dict(pivot=(144.0, 43.5), angle=-10.0, shift=(1.8, 0.5)),
    "izu": dict(pivot=(139.2, 33.5), angle=0.0, shift=(0.6, -4.2)),
}


def progress(key, t):
    """1=過去の姿勢, 0=現在の姿勢"""
    if key in ("sw", "ne"):
        return 1.0 - 0.1 * seg(t, 10, 16) - 0.9 * seg(t, 16, 29)
    if key == "eh":
        return 1.0 - seg(t, 17, 34)
    if key == "izu":
        return 1.0 - seg(t, 30, 42)
    return 0.0


def affine(key, k):
    """lon/lat 平面での 2x3 アフィン変換（k=1で過去、k=0で現在）"""
    p = PAST[key]
    px, py = p["pivot"]
    a = math.radians(p["angle"] * k)
    ca, sa = math.cos(a), math.sin(a)
    dx, dy = p["shift"][0] * k, p["shift"][1] * k
    # 縮尺補正した平面で回転: x' = (ca*(x*KX - px*KX) - sa*(y-py))/KX + px + dx
    m00, m01 = ca, -sa / KX
    m10, m11 = sa * KX, ca
    c0 = px - (m00 * px + m01 * py) + dx
    c1 = py - (m10 * px + m11 * py) + dy
    return m00, m01, m10, m11, c0, c1


def mpl_affine(key, k):
    m00, m01, m10, m11, c0, c1 = affine(key, k)
    return Affine2D(np.array([[m00, m01, c0], [m10, m11, c1], [0, 0, 1]]))


def place(geom, key, k):
    m00, m01, m10, m11, c0, c1 = affine(key, k)
    return affine_transform(geom, [m00, m01, m10, m11, c0, c1])


_SWEPT = {}


def new_seafloor(L, t):
    """大陸から離れた陸塊が通過した範囲＝日本海の新しい海底"""
    ks = progress("sw", t)
    if ks > 0.97 or t < 12:
        return None
    key = round(ks, 3)
    if key not in _SWEPT:
        parts = []
        for b in ("sw", "ne"):
            for kk in np.linspace(ks, 1.0, 14):
                parts.append(place(L["simple"][b], b, kk))
        region = unary_union(parts)
        now = unary_union([place(L["simple"][b], b, ks) for b in ("sw", "ne")])
        region = region.difference(now.buffer(0.02)).difference(L["cont"]).buffer(-0.08).buffer(0.08)
        _SWEPT.clear()
        _SWEPT[key] = region
    return _SWEPT[key]


def submerge_level(t):
    """海岸からの距離(px, 1px≈2km)でこの値未満の土地を浅い海として描く"""
    return 13.0 * seg(t, 27, 32) * (1 - seg(t, 36, 44))


def fossa_level(t):
    return seg(t, 24, 30) * (1 - seg(t, 37, 44))


def sea_level(t):
    """氷期の海面（m）"""
    keys = [(44, 0), (45.5, -70), (46.5, -35), (48, -95), (48.8, -60), (50, -120), (51.5, -120), (53.2, 0)]
    if t <= keys[0][0] or t >= keys[-1][0]:
        return 0.0
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * ease((t - t0) / (t1 - t0))
    return 0.0


AGE_KEYS = [(0, 3.0e7), (10, 2.8e7), (16, 2.3e7), (29, 1.5e7), (36, 1.0e7), (44, 1.0e6), (49, 2.5e4),
            (51.5, 2.0e4), (53.5, 1.0e4)]


def age(t):
    if t >= 55:
        return 0
    if t >= AGE_KEYS[-1][0]:
        return 1.0e4
    for (t0, a0), (t1, a1) in zip(AGE_KEYS, AGE_KEYS[1:]):
        if t0 <= t <= t1:
            u = (t - t0) / (t1 - t0)
            return 10 ** (math.log10(a0) + (math.log10(a1) - math.log10(a0)) * u)
    return AGE_KEYS[0][1]


def age_text(a):
    if a <= 0:
        return "現在"
    man = a / 1e4
    if man >= 100:
        return f"約{int(round(man / 10) * 10):,}万年前"
    return f"約{max(1, int(round(man)))}万年前"


# カメラ: (時刻, 中心lon, 中心lat, 横幅°)
CAM_KEYS = [(0, 133.0, 38.0, 64.0), (4, 134.0, 38.0, 46.0), (16, 135.0, 38.2, 42.0), (29, 136.0, 37.0, 38.0),
            (36, 137.2, 36.6, 30.0), (44, 132.5, 37.5, 44.0), (53, 132.5, 37.5, 44.0), (58, 137.0, 37.4, 40.0),
            (60, 137.0, 37.4, 40.0)]


def camera(t):
    for (t0, *a), (t1, *b) in zip(CAM_KEYS, CAM_KEYS[1:]):
        if t0 <= t <= t1:
            u = ease((t - t0) / (t1 - t0))
            lon, lat, w = (x + (y - x) * u for x, y in zip(a, b))
            h = w * KX * H / W
            return lon - w / 2, lon + w / 2, lat - h / 2, lat + h / 2
    lon, lat, w = CAM_KEYS[-1][1:]
    h = w * KX * H / W
    return lon - w / 2, lon + w / 2, lat - h / 2, lat + h / 2


# ======================================================================
# 描画要素
# ======================================================================
SCENES = [
    (0, "日本列島のなりたち", "大陸の一部から、いまの形になるまで"),
    (4, "大陸の一部だった", "日本列島のもとは、ユーラシア大陸の東の縁。太平洋側からプレートが沈み込んでいました"),
    (10, "大陸が裂けはじめる", "沈み込みの影響で地下からマグマが上昇。大陸の縁に割れ目（リフト）ができます"),
    (16, "観音開きで日本海が誕生", "西南日本は時計回り、東北日本は反時計回りに回転。すき間に新しい海底ができ日本海に"),
    (29, "列島の大部分は海の下", "列島は多くの島に分かれ、中央部には深い海「フォッサマグナ」が広がっていました"),
    (36, "押されて隆起、伊豆が衝突", "東西から押されて山脈が隆起。南から来た伊豆の島が本州にぶつかり半島になりました"),
    (44, "氷期のたびに陸続き", "海面が最大約120m下がり、北海道は大陸と、九州・四国・本州は互いに陸でつながりました"),
    (53.5, "いまの日本列島", "約1万年前に海面が上がり、いまの形に。列島はいまもプレートに押され動き続けています"),
]

TRENCHES = {
    "千島海溝": [(158, 50.5), (154, 46.3), (150, 43.6), (147, 41.9), (144.8, 41.0)],
    "日本海溝": [(144.8, 41.0), (144.2, 39.5), (143.9, 38.0), (142.9, 36.5), (142.2, 35.0), (141.95, 34.1)],
    "伊豆・小笠原海溝": [(141.95, 34.1), (142.3, 31.0), (142.7, 28.0), (143.2, 25.0), (144.5, 22.0)],
    "相模トラフ": [(141.95, 34.1), (140.6, 34.75), (139.35, 35.1)],
    "南海トラフ": [(138.55, 35.0), (138.45, 34.2), (137.0, 33.6), (135.0, 32.9), (133.0, 32.2),
                   (131.9, 31.3), (131.4, 30.4)],
    "琉球海溝": [(131.4, 30.4), (130.0, 28.5), (128.3, 26.3), (126.5, 24.8), (124.0, 23.8), (122.5, 23.6)],
}
VOLCANOES = [(138.73, 35.36), (138.52, 36.40), (130.66, 31.58), (131.10, 32.88), (130.30, 32.76),
             (140.84, 42.54), (142.68, 43.42), (140.07, 37.60), (141.00, 39.85), (137.48, 35.89),
             (130.87, 31.93), (139.39, 34.73), (140.28, 38.14), (144.0, 43.6), (139.52, 34.08), (136.77, 36.15)]


def txt(ax, x, y, s, size, color="#ffffff", alpha=1.0, ha="center", weight="bold", z=20):
    if alpha <= 0.01:
        return
    ax.text(x, y, s, fontsize=size * SCALE, color=color, alpha=alpha, ha=ha, va="center", zorder=z,
            fontweight=weight, path_effects=[pe.withStroke(linewidth=3.2 * SCALE, foreground="#06121f",
                                                           alpha=alpha * 0.9)])


def arrow(ax, p0, p1, color, alpha, lw=4, ms=26):
    if alpha <= 0.01:
        return
    ax.annotate("", xy=p1, xytext=p0, zorder=15,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw * SCALE, mutation_scale=ms * SCALE,
                                alpha=alpha, shrinkA=0, shrinkB=0))


def arc(ax, center, r, a0, a1, color, alpha):
    if alpha <= 0.01:
        return
    th = np.radians(np.linspace(a0, a1, 50))
    xs = center[0] + r * np.cos(th) / KX
    ys = center[1] + r * np.sin(th)
    ax.plot(xs[:-4], ys[:-4], color=color, lw=4 * SCALE, alpha=alpha, zorder=15, solid_capstyle="round",
            path_effects=[pe.withStroke(linewidth=7 * SCALE, foreground="#06121f", alpha=alpha * 0.6)])
    arrow(ax, (xs[-5], ys[-5]), (xs[-1], ys[-1]), color, alpha)


def trench_line(ax, pts, alpha, color="#ffffff"):
    if alpha <= 0.01:
        return
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=1.6 * SCALE, alpha=0.8 * alpha, zorder=9)
    line = LineString([(x * KX, y) for x, y in pts])
    n = max(int(line.length / 0.55), 2)
    tri = []
    for i in range(n):
        d = (i + 0.5) * line.length / n
        p = line.interpolate(d)
        q = line.interpolate(min(d + 0.05, line.length))
        vx, vy = q.x - p.x, q.y - p.y
        L = math.hypot(vx, vy) or 1
        vx, vy = vx / L, vy / L
        nx, ny = vy, -vx  # 進行方向の右側（上盤側＝陸側）に三角
        s = 0.18
        a = ((p.x - vx * s) / KX, p.y - vy * s)
        b = ((p.x + vx * s) / KX, p.y + vy * s)
        c = ((p.x + nx * s * 1.4) / KX, p.y + ny * s * 1.4)
        tri.append(MplPolygon([a, b, c], closed=True))
    for tpoly in tri:
        tpoly.set(facecolor=color, edgecolor="none", alpha=0.8 * alpha, zorder=9)
        ax.add_patch(tpoly)


def outline(ax, geom, color, alpha, lw=1.1, z=8):
    if alpha <= 0.01:
        return
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty or p.geom_type != "Polygon" or p.area < 0.004:
            continue
        xs, ys = p.exterior.xy
        ax.plot(xs, ys, color=color, lw=lw * SCALE, alpha=alpha, zorder=z)


def fill(ax, geom, color, alpha, z=3, **kw):
    if geom is None or alpha <= 0.01:
        return
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        ax.add_patch(MplPolygon(np.asarray(p.exterior.coords), closed=True, facecolor=color, alpha=alpha,
                                zorder=z, edgecolor="none", **kw))


def rgba(c):
    return np.array(matplotlib.colors.to_rgb(c))


BLOCK_COLOR = {"sw": C_SW, "ne": C_NE, "eh": C_EH, "izu": C_IZU}
BLOCK_NAME = {"sw": "西南日本", "ne": "東北日本", "eh": "東北海道（千島弧）", "izu": "伊豆（伊豆・小笠原弧）"}


def block_image(tile, key, t):
    rgb, alpha, dist = tile["rgb"], tile["alpha"], tile["dist"]
    tint = 0.28 * (1 - seg(t, 42, 46))
    out = rgb * (1 - tint) + rgba(BLOCK_COLOR[key]) * tint
    lvl = submerge_level(t)
    wet = np.zeros_like(alpha)
    if lvl > 0.05:
        wet = np.clip((lvl - dist) / 3.0 + 0.5, 0, 1)
    fl = fossa_level(t)
    if fl > 0:
        wet = np.maximum(wet, tile["fossa"] * fl)
    if wet.any():
        w = wet[..., None]
        out = out * (1 - w) + C_SHALLOW * w
        a = alpha * (1 - 0.55 * wet)
    else:
        a = alpha
    return np.dstack([np.clip(out, 0, 1), a])


# ======================================================================
# フレーム描画
# ======================================================================
def scene_at(t):
    idx = 0
    for i, s in enumerate(SCENES):
        if t >= s[0]:
            idx = i
    start = SCENES[idx][0]
    return idx, t - start


def render_frame(fig, ax, t, L):
    ax.clear()
    ax.axis("off")
    x0, x1, y0, y1 = camera(t)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("auto")

    ax.imshow(L["base"], extent=(R_LON0, R_LON1, R_LAT0, R_LAT1), origin="upper", zorder=0,
              interpolation="bilinear", aspect="auto")

    # 経緯線
    for lon in range(100, 170, 5):
        ax.axvline(lon, color="#ffffff", lw=0.6 * SCALE, alpha=0.10, zorder=1)
        if x0 + 0.8 < lon < x1 - 0.8:
            ax.text(lon, y0 + (y1 - y0) * 0.155, f"{lon}°E", color="#dbe9f7", alpha=0.35, fontsize=9 * SCALE,
                    ha="center", zorder=1)
    for lat in range(20, 60, 5):
        ax.axhline(lat, color="#ffffff", lw=0.6 * SCALE, alpha=0.10, zorder=1)
        if y0 + 1 < lat < y1 - 0.5:
            ax.text(x1 - (x1 - x0) * 0.008, lat, f"{lat}°N", color="#dbe9f7", alpha=0.35, fontsize=9 * SCALE,
                    ha="right", va="bottom", zorder=1)

    # 氷期の陸化した大陸棚
    sl = sea_level(t)
    if sl < -1:
        a = min(1.0, -sl / 120) ** 0.8
        sh = L["shelf"]
        img = np.dstack([np.broadcast_to(C_SHELF, sh.shape + (3,)), sh * 0.92 * a])
        ax.imshow(img, extent=(R_LON0, R_LON1, R_LAT0, R_LAT1), origin="upper", zorder=2,
                  interpolation="bilinear", aspect="auto")

    # 日本海の新しい海底
    sea = new_seafloor(L, t)
    if sea is not None:
        a = 0.5 * seg(t, 12, 15) * (1 - seg(t, 27, 31))
        fill(ax, sea, "#10345a", a, z=3)
        outline(ax, sea, "#7fd0ff", a * 0.9, lw=1.0, z=3)
        if 19 < t < 29 and not sea.is_empty:
            big = max(getattr(sea, "geoms", [sea]), key=lambda g: g.area)
            p = big.representative_point()
            txt(ax, p.x, p.y, "新しい海底", 14, "#9fdcff", seg(t, 19, 21) * (1 - seg(t, 27, 29)))

    # 陸塊（過去→現在へ移動）
    for key in ("izu", "eh", "ne", "sw"):
        k = progress(key, t)
        tile = L["tiles"][key]
        tr = mpl_affine(key, k) + ax.transData
        im = ax.imshow(block_image(tile, key, t), extent=tile["extent"], origin="upper", zorder=6,
                       interpolation="bilinear", aspect="auto")
        im.set_transform(tr)
        ol_a = 0.9 * (1 - seg(t, 43, 47)) * (1 - 0.7 * min(submerge_level(t) / 13, 1))
        outline(ax, place(L["outlines"][key], key, k), BLOCK_COLOR[key], ol_a, lw=1.3, z=7)

    draw_rift(ax, t)
    draw_rotation(ax, t)
    draw_uplift(ax, t)
    draw_plates(ax, t)
    draw_ice_age(ax, t, sl)
    draw_labels(ax, t)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    draw_hud(fig, ax, t)


# 日本海側の海岸のすぐ沖（現在の座標）。陸塊と一緒に動かす
RIFT_SW = [(129.9, 33.9), (131.3, 34.8), (132.8, 35.6), (134.6, 35.9), (135.9, 35.9), (136.6, 37.3)]
RIFT_NE = [(137.9, 37.9), (139.3, 38.6), (139.7, 40.0), (139.7, 41.6), (140.2, 43.2), (141.4, 45.5)]


def draw_rift(ax, t):
    a = seg(t, 10, 11.5) * (1 - seg(t, 16, 18))
    if a <= 0:
        return
    rift = []
    for key, pts in (("sw", RIFT_SW), ("ne", RIFT_NE)):
        m00, m01, m10, m11, c0, c1 = affine(key, progress(key, t))
        rift += [(m00 * x + m01 * y + c0, m10 * x + m11 * y + c1) for x, y in pts]
    xs, ys = zip(*rift)
    grow = seg(t, 10, 13)
    n = max(2, int(len(xs) * grow + 0.999))
    ax.plot(xs[:n], ys[:n], color="#ff4d1f", lw=14 * SCALE, alpha=0.3 * a, zorder=10, solid_capstyle="round")
    ax.plot(xs[:n], ys[:n], color="#ff9a3c", lw=5 * SCALE, alpha=0.55 * a, zorder=10, solid_capstyle="round")
    ax.plot(xs[:n], ys[:n], color="#fff0b0", lw=1.6 * SCALE, alpha=0.95 * a, zorder=10)
    rng = np.random.default_rng(int(t * 10))
    line = LineString(rift[:n])
    for _ in range(16):
        p = line.interpolate(rng.uniform(0, line.length))
        r = rng.uniform(0.08, 0.25)
        ax.add_patch(plt.Circle((p.x + rng.normal(0, 0.25), p.y + rng.normal(0, 0.2)), r,
                                color="#ffb347", alpha=0.6 * a * rng.uniform(0.3, 1), zorder=10, lw=0))
    mx, my = rift[len(rift) // 2]
    txt(ax, mx - 2.2, my + 0.6, "割れ目（リフト）", 15, "#ffc98a", a)


def draw_rotation(ax, t):
    a = seg(t, 16, 17.5) * (1 - seg(t, 27, 29))
    if a <= 0:
        return
    arc(ax, PAST["sw"]["pivot"], 5.2, 78, 38, "#ffc07a", a)
    arc(ax, PAST["ne"]["pivot"], 6.8, 222, 262, "#95f2b0", a)
    txt(ax, 130.6, 39.9, "時計回り 約45°", 15, "#ffc07a", a)
    txt(ax, 147.2, 39.0, "反時計回り 約30°", 15, "#95f2b0", a)
    c = seg(t, 18, 20) * (1 - seg(t, 31, 33))
    arrow(ax, (148.8, 45.2), (146.4, 44.0), C_EH, c)
    txt(ax, 150.3, 43.7, "東北海道が衝突", 13, "#d6c2ff", c)


def draw_uplift(ax, t):
    a = seg(t, 30, 32) * (1 - seg(t, 36, 38))
    txt(ax, 141.0, 34.1, "フォッサマグナ（海）", 15, "#bfe9ff", a)
    txt(ax, 133.6, 36.4, "多島海", 16, "#bfe9ff", a)
    # 伊豆の北上
    b = seg(t, 35.5, 37) * (1 - seg(t, 42, 44))
    k = progress("izu", t)
    dx, dy = PAST["izu"]["shift"][0] * k, PAST["izu"]["shift"][1] * k
    arrow(ax, (139.4 + dx, 32.3 + dy), (139.1 + dx, 34.2 + dy), C_IZU, b)
    txt(ax, 141.1 + dx, 33.0 + dy, "伊豆が北上", 14, "#ffb0bf", b)
    # 東西圧縮・隆起
    c = seg(t, 37, 38.5) * (1 - seg(t, 43, 44.5))
    arrow(ax, (135.4, 39.0), (137.0, 37.6), "#ff8a6a", c, lw=4, ms=26)
    txt(ax, 134.6, 39.6, "東西から圧縮", 14, "#ffc2b0", c)
    txt(ax, 137.6, 36.3, "日本アルプス隆起", 13, "#ffe2b8", c)
    v = seg(t, 38, 40) * (1 - seg(t, 43.5, 45)) + seg(t, 55, 56.5)
    for i, (x, y) in enumerate(VOLCANOES):
        flick = 0.75 + 0.25 * math.sin(t * 6 + i * 1.7)
        ax.plot(x, y, marker="^", ms=7 * SCALE, color="#ff5a36", mec="#fff0d0", mew=0.8 * SCALE,
                alpha=min(v, 1) * flick, zorder=12)


def draw_plates(ax, t):
    a = seg(t, 4, 6) * (1 - seg(t, 9, 11)) + seg(t, 36.5, 38.5) * (1 - seg(t, 43.5, 45)) + seg(t, 55.5, 57)
    a = min(a, 1)
    if a <= 0:
        return
    k_sw, k_ne = progress("sw", t), progress("ne", t)
    for name, pts in TRENCHES.items():
        if name in ("南海トラフ", "琉球海溝"):
            key, k = "sw", k_sw
        elif name in ("日本海溝", "千島海溝"):
            key, k = "ne", k_ne
        else:
            key, k = None, 0
        if key and k > 0:
            m00, m01, m10, m11, c0, c1 = affine(key, k)
            pts = [(m00 * x + m01 * y + c0, m10 * x + m11 * y + c1) for x, y in pts]
        trench_line(ax, pts, a)
    late = min(seg(t, 36.5, 38.5) * (1 - seg(t, 43.5, 45)) + seg(t, 55.5, 57), 1)
    txt(ax, 147.6, 36.2, "日本海溝", 11, "#e8f2ff", late * 0.9)
    txt(ax, 132.4, 31.4, "南海トラフ", 11, "#e8f2ff", late * 0.9)
    arrow(ax, (151.2, 38.9), (146.6, 37.7), "#ff8a6a", a, lw=4, ms=26)
    txt(ax, 149.3, 40.0, "太平洋プレート", 14, "#ffc2b0", a)
    txt(ax, 149.6, 38.0, "年 約8cm", 11, "#ffc2b0", a)
    arrow(ax, (136.9, 32.3), (136.0, 33.3), "#ff8a6a", a * 0.9, lw=3.5, ms=24)
    txt(ax, 136.4, 31.8, "フィリピン海プレート", 12, "#ffc2b0", a)


def draw_ice_age(ax, t, sl):
    a = seg(t, 44.3, 45.5) * (1 - seg(t, 52.5, 53.5))
    if a <= 0:
        return
    deep = min(1.0, -sl / 100)
    txt(ax, 145.4, 45.9, "宗谷・間宮海峡が陸に\n→ 大陸と陸続き", 13, "#fff1c9", a * deep)
    txt(ax, 125.2, 33.0, "黄海・東シナ海の\n大陸棚が陸に", 13, "#fff1c9", a * deep)
    txt(ax, 128.2, 35.9, "対馬海峡は\n細い水道", 12, "#cfe9ff", a * deep)
    txt(ax, 144.5, 41.6, "津軽海峡は残る", 12, "#cfe9ff", a * deep)
    txt(ax, 133.4, 33.35, "瀬戸内海は陸", 12, "#fff1c9", a * deep)


def draw_labels(ax, t):
    x0 = ax.get_xlim()[0]
    txt(ax, max(117.0, x0 + 5.5), 42.5, "ユーラシア大陸", 20, "#f6eed6", 0.9)
    txt(ax, 147.5, 33.2, "太平洋", 22, "#bcd8f2", 0.85)
    txt(ax, 136.0, 41.0, "日本海", 20, "#bcd8f2", seg(t, 25, 28) * (1 - seg(t, 44, 45)) + seg(t, 53, 54.5))
    a = seg(t, 54.5, 56)
    for name, x, y in [("北海道", 142.9, 43.35), ("本州", 139.5, 38.6), ("四国", 133.5, 33.7),
                       ("九州", 130.8, 32.4), ("伊豆半島", 139.0, 34.3)]:
        txt(ax, x, y, name, 15 if name != "伊豆半島" else 11, "#ffffff", a)


def draw_hud(fig, ax, t):
    fig.texts.clear()
    fig.patches.clear()
    idx, dt = scene_at(t)
    _, head, desc = SCENES[idx]
    fade = ease(dt / 0.6)

    if idx == 0:
        a = ease(t / 0.8) * (1 - seg(t, 3.2, 4.0))
        fig.patches.append(FancyBboxPatch((0.18, 0.34), 0.64, 0.32, boxstyle="round,pad=0.01,rounding_size=0.02",
                                          transform=fig.transFigure, facecolor=C_PANEL, alpha=0.82 * a,
                                          edgecolor="#9cc4ea", lw=1.4, figure=fig))
        fig.text(0.5, 0.555, head, ha="center", va="center", fontsize=58 * SCALE, color="#ffffff", alpha=a,
                 fontweight="bold")
        fig.text(0.5, 0.435, desc, ha="center", va="center", fontsize=22 * SCALE, color="#cfe6ff", alpha=a)
        fig.text(0.5, 0.385, "約3000万年の旅を60秒で", ha="center", va="center", fontsize=15 * SCALE,
                 color=C_GOLD, alpha=a)
    else:
        fig.patches.append(FancyBboxPatch((0.012, 0.805), 0.40, 0.175, boxstyle="round,pad=0.006,rounding_size=0.012",
                                          transform=fig.transFigure, facecolor=C_PANEL, alpha=0.8,
                                          edgecolor="#5f8fbf", lw=1, figure=fig))
        fig.text(0.026, 0.925, age_text(age(t)), ha="left", va="center", fontsize=32 * SCALE, color=C_GOLD,
                 fontweight="bold")
        fig.text(0.026, 0.848, head, ha="left", va="center", fontsize=21 * SCALE, color="#ffffff", alpha=fade,
                 fontweight="bold")
        fig.patches.append(FancyBboxPatch((0.07, 0.085), 0.86, 0.068, boxstyle="round,pad=0.006,rounding_size=0.012",
                                          transform=fig.transFigure, facecolor=C_PANEL, alpha=0.8,
                                          edgecolor="none", figure=fig))
        fig.text(0.5, 0.119, desc, ha="center", va="center", fontsize=17 * SCALE, color="#ffffff", alpha=fade)
        draw_legend(fig, t)
        draw_sea_gauge(fig, t)
        draw_scale(fig, ax)

    draw_timeline(fig, t)
    ca = seg(t, 57, 58)
    fig.patches.append(FancyBboxPatch((0.84, 0.945 - 0.062 * ca), 0.155, 0.04 + 0.062 * ca,
                                      boxstyle="round,pad=0.004,rounding_size=0.008", transform=fig.transFigure,
                                      facecolor=C_PANEL, alpha=0.6, edgecolor="none", figure=fig))
    fig.text(0.988, 0.972, "※簡略化した復元図", ha="right", va="top", fontsize=10 * SCALE, color="#9fb6cc")
    fig.text(0.988, 0.935, "地形・海岸線・水深: Natural Earth", ha="right", va="top", fontsize=9 * SCALE,
             color="#9fb6cc", alpha=ca)
    fig.text(0.988, 0.912, "音声: HTS voice tohoku-f01 (CC BY 4.0)", ha="right", va="top", fontsize=9 * SCALE,
             color="#9fb6cc", alpha=ca)


def draw_legend(fig, t):
    a = seg(t, 4.5, 6) * (1 - seg(t, 42, 45))
    if a <= 0:
        return
    fig.patches.append(FancyBboxPatch((0.795, 0.185), 0.19, 0.16, boxstyle="round,pad=0.006,rounding_size=0.01",
                                      transform=fig.transFigure, facecolor=C_PANEL, alpha=0.75 * a,
                                      edgecolor="none", figure=fig))
    y = 0.325
    for key in ("sw", "ne", "eh", "izu"):
        fig.patches.append(Rectangle((0.805, y - 0.011), 0.014, 0.022, transform=fig.transFigure,
                                     facecolor=BLOCK_COLOR[key], alpha=a, figure=fig))
        fig.text(0.825, y, BLOCK_NAME[key], ha="left", va="center", fontsize=12 * SCALE, color="#ffffff", alpha=a)
        y -= 0.036


def draw_sea_gauge(fig, t):
    a = seg(t, 44, 45) * (1 - seg(t, 53, 54))
    if a <= 0:
        return
    sl = sea_level(t)
    x, y0, h = 0.945, 0.3, 0.38
    fig.patches.append(FancyBboxPatch((x - 0.035, y0 - 0.06), 0.075, h + 0.13,
                                      boxstyle="round,pad=0.004,rounding_size=0.01", transform=fig.transFigure,
                                      facecolor=C_PANEL, alpha=0.8 * a, edgecolor="none", figure=fig))
    fig.patches.append(Rectangle((x - 0.006, y0), 0.012, h, transform=fig.transFigure, facecolor="#1c3d5e",
                                 alpha=a, figure=fig))
    lvl = y0 + h * (1 + sl / 150)
    fig.patches.append(Rectangle((x - 0.006, y0), 0.012, lvl - y0, transform=fig.transFigure,
                                 facecolor="#5fb4ff", alpha=a, figure=fig))
    for v in (0, -50, -100, -150):
        yy = y0 + h * (1 + v / 150)
        fig.text(x - 0.012, yy, f"{v}m", ha="right", va="center", fontsize=9 * SCALE, color="#cfe6ff", alpha=a)
    fig.text(x, y0 + h + 0.035, "海面", ha="center", va="center", fontsize=12 * SCALE, color="#ffffff", alpha=a,
             fontweight="bold")
    fig.text(x, y0 - 0.03, f"{sl:+.0f}m", ha="center", va="center", fontsize=13 * SCALE, color=C_GOLD, alpha=a,
             fontweight="bold")


def draw_scale(fig, ax):
    x0, x1, y0, y1 = ax.get_xlim() + ax.get_ylim()
    lat = (y0 + y1) / 2
    km_per_deg = 111.32 * math.cos(math.radians(lat))
    frac = (500 / km_per_deg) / (x1 - x0)
    fx, fy = 0.03, 0.185
    fig.patches.append(Rectangle((fx, fy), frac, 0.006, transform=fig.transFigure, facecolor="#ffffff",
                                 alpha=0.85, figure=fig))
    fig.patches.append(Rectangle((fx, fy), frac / 2, 0.006, transform=fig.transFigure, facecolor="#1a2c40",
                                 alpha=0.85, figure=fig))
    fig.text(fx + frac + 0.006, fy + 0.003, "500 km", ha="left", va="center", fontsize=11 * SCALE,
             color="#ffffff", alpha=0.85)


TL_TICKS = [(3.0e7, "3000万年前"), (1.0e7, "1000万"), (1.0e6, "100万"),
            (1.0e5, "10万"), (1.0e4, "1万"), (1.0e3, "現在")]


def tl_pos(a):
    a = max(a, 1.0e3)
    return (math.log10(3.0e7) - math.log10(a)) / (math.log10(3.0e7) - 3)


def draw_timeline(fig, t):
    if t < 3.5:
        return
    a = seg(t, 3.5, 4.5)
    fig.patches.append(Rectangle((0, 0), 1, 0.075, transform=fig.transFigure, facecolor=C_BG, alpha=0.85 * a,
                                 figure=fig))
    x0, x1, y = 0.07, 0.93, 0.045
    fig.patches.append(Rectangle((x0, y - 0.002), x1 - x0, 0.004, transform=fig.transFigure, facecolor="#5f7f9f",
                                 alpha=a, figure=fig))
    ag = age(t)
    p = tl_pos(ag if ag > 0 else 1e3)
    fig.patches.append(Rectangle((x0, y - 0.003), (x1 - x0) * p, 0.006, transform=fig.transFigure,
                                 facecolor=C_GOLD, alpha=a, figure=fig))
    for v, lab in TL_TICKS:
        xx = x0 + (x1 - x0) * tl_pos(v)
        fig.patches.append(Rectangle((xx - 0.0008, y - 0.008), 0.0016, 0.016, transform=fig.transFigure,
                                     facecolor="#9fb6cc", alpha=a, figure=fig))
        fig.text(xx, y - 0.024, lab, ha="center", va="center", fontsize=9.5 * SCALE, color="#cfe0f0", alpha=a)
    xx = x0 + (x1 - x0) * p
    fig.patches.append(plt.Circle((xx, y), 0.0065, transform=fig.transFigure, facecolor=C_GOLD,
                                  edgecolor="#ffffff", lw=1.2, alpha=a, figure=fig))


# ======================================================================
# 音（アンビエントBGM + 地鳴り）
# ======================================================================
def make_audio(path, sr=44100):
    n = sr * DURATION
    tt = np.arange(n) / sr
    out = np.zeros((n, 2))
    # コード進行（Am - F - C - G - Am - Dm - Em - Am）各7.5秒
    chords = [[220, 261.6, 329.6], [174.6, 220, 261.6], [196, 261.6, 329.6], [196, 246.9, 293.7],
              [220, 261.6, 329.6], [146.8, 220, 293.7], [164.8, 246.9, 329.6], [220, 277.2, 329.6]]
    seg_len = DURATION / len(chords)
    for i, ch in enumerate(chords):
        s0, s1 = int(i * seg_len * sr), int(min((i + 1) * seg_len + 1.5, DURATION) * sr)
        tl = tt[s0:s1] - tt[s0]
        env = np.minimum(1, tl / 2.0) * np.minimum(1, (tt[s1 - 1] - tt[s0] - tl) / 2.0 + 1e-3)
        for j, f in enumerate(ch + [ch[0] / 2]):
            for det, pan in ((-0.6, 0.3), (0.6, 0.7)):
                w = np.sin(2 * np.pi * (f + det) * tl + j) + 0.25 * np.sin(4 * np.pi * (f + det) * tl)
                out[s0:s1, 0] += w * env * (1 - pan) * 0.05
                out[s0:s1, 1] += w * env * pan * 0.05
    # きらめき（高音のアルペジオ）
    rng = np.random.default_rng(3)
    for k in range(70):
        st = rng.uniform(4, 58)
        f = rng.choice([880, 987.8, 1046.5, 1318.5, 1568])
        s0 = int(st * sr)
        ln = int(1.6 * sr)
        tl = np.arange(min(ln, n - s0)) / sr
        w = np.sin(2 * np.pi * f * tl) * np.exp(-tl * 2.6) * 0.022
        pan = rng.uniform(0.2, 0.8)
        out[s0:s0 + len(tl), 0] += w * (1 - pan)
        out[s0:s0 + len(tl), 1] += w * pan
    # 地鳴り（リフト・衝突）
    brown = np.cumsum(rng.standard_normal(n))
    brown = brown - ndimage.uniform_filter1d(brown, sr // 5)
    brown /= np.abs(brown).max() + 1e-9
    rumble_env = np.zeros(n)
    for a, b, g in ((10, 17, 0.35), (37, 44, 0.3)):
        rumble_env += g * np.clip(np.minimum((tt - a) / 1.5, (b - tt) / 2.0), 0, 1)
    rumble = ndimage.uniform_filter1d(brown, 40) * rumble_env
    out[:, 0] += rumble
    out[:, 1] += rumble
    # 全体のフェード
    master = np.clip(np.minimum(tt / 1.5, (DURATION - tt) / 3.0), 0, 1)
    out *= master[:, None]
    out /= np.abs(out).max() + 1e-9
    # ナレーション（話している間はBGMを下げる）
    voice = narration(sr, n)
    active = ndimage.uniform_filter1d((np.abs(voice) > 0.01).astype(float), sr // 2)
    duck = 1 - 0.65 * ndimage.uniform_filter1d(np.clip(active * 4, 0, 1), sr // 3)
    out = out * 0.55 * duck[:, None] + voice[:, None] * 0.9
    out /= max(np.abs(out).max(), 1.0)
    out *= 0.95
    pcm = (out * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


# (開始秒, 読み上げ文) — 次の開始秒の0.3秒前までに収まるよう話速を自動調整
NARRATION = [  # 読み誤り対策で一部をかな書き（縁→ふち、氷期→ひょうき、日本→にほん）
    (0.5, "にほん列島のなりたち。"),
    (4.4, "約三千万年前。にほん列島は、大陸の東のふちにありました。"),
    (10.4, "やがて地下からマグマが上がり、大陸のふちが裂けはじめます。"),
    (16.4, "西南にほんは時計回りに、東北にほんは反時計回りに回転しながら大陸を離れ、そのすき間に、日本海が生まれました。"),
    (29.4, "約千五百万年前。列島の多くは海の下で、中央には深い海が広がっていました。"),
    (36.4, "やがて東西から押されて山脈が隆起し、南から来た伊豆の島が、本州にぶつかりました。"),
    (44.4, "ひょうきには海面が約百二十メートル下がり、北海道は大陸と陸続きになりました。"),
    (53.6, "約一万年前、海面が上がり、いまのにほん列島になりました。"),
]
VOICE_URL = ("https://raw.githubusercontent.com/icn-lab/htsvoice-tohoku-f01/master/"
             "tohoku-f01-neutral.htsvoice")  # CC BY 4.0, Tohoku University


def narration(sr, n):
    import pyopenjtalk
    from pyopenjtalk.htsengine import HTSEngine
    from scipy.signal import resample_poly

    eng = HTSEngine(fetch("tohoku-f01-neutral.htsvoice", VOICE_URL).encode())
    vsr = eng.get_sampling_frequency()
    out = np.zeros(n)
    starts = [s for s, _ in NARRATION] + [DURATION - 0.8]
    for (st, text), nxt in zip(NARRATION, starts[1:]):
        labels = pyopenjtalk.extract_fullcontext(text)
        speed = 1.05
        while True:
            eng.set_speed(speed)
            x = np.asarray(eng.synthesize(labels), dtype=np.float64)
            if len(x) / vsr <= nxt - st - 0.3 or speed >= 1.5:
                break
            speed += 0.05
        eng.refresh()
        x = resample_poly(x, sr, vsr) / 32768.0
        x = x / (np.abs(x).max() + 1e-9) * 0.85
        s0 = int(st * sr)
        x = x[: n - s0]
        out[s0:s0 + len(x)] += x
        print(f"narration {st:5.1f}s: {len(x) / sr:4.1f}s / 枠 {nxt - st:4.1f}s (speed {speed:.2f})", flush=True)
    return out


# ======================================================================
# 実行
# ======================================================================
_G = {}


def _init():
    _G["L"] = build_layers()
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(C_BG)
    _G["fig"], _G["ax"] = fig, fig.add_axes([0, 0, 1, 1])


def _render(i):
    t = i / FPS
    fig, ax = _G["fig"], _G["ax"]
    render_frame(fig, ax, t, _G["L"])
    fig.canvas.draw()
    return np.ascontiguousarray(np.asarray(fig.canvas.buffer_rgba())[:, :, :3]).tobytes()


def main():
    if "--preview" in sys.argv:
        _init()
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]] or \
            [2, 7, 13, 20, 26, 33, 40, 50, 58]
        for s in times:
            render_frame(_G["fig"], _G["ax"], s, _G["L"])
            _G["fig"].savefig(os.path.join(HERE, f"preview_{s:04.1f}.png"), dpi=100)
        return

    wav = os.path.join(CACHE, "bgm.wav")
    make_audio(wav)
    silent = os.path.join(CACHE, "video.mp4")
    if "--audio-only" in sys.argv:  # 映像は作り直さず音だけ差し替える
        mux(silent, wav)
        return

    build_layers()  # 素材のダウンロードを先に済ませる
    writer = imageio_ffmpeg.write_frames(silent, (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                         quality=None, bitrate=None, macro_block_size=1,
                                         output_params=["-crf", "19", "-preset", "slow"])
    writer.send(None)
    n = FPS * DURATION
    procs = max(1, (os.cpu_count() or 2))
    with mp.get_context("fork").Pool(procs, initializer=_init) as pool:
        for i, frame in enumerate(pool.imap(_render, range(n), chunksize=4)):
            writer.send(frame)
            if i % 150 == 0:
                print(f"{i}/{n}", flush=True)
    writer.close()
    mux(silent, wav)


def mux(silent, wav):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.check_call([ff, "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", OUT])
    print("done:", OUT)


if __name__ == "__main__":
    main()
