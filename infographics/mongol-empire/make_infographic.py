"""モンゴル帝国の拡大と衰退を1枚の図解（PNG）にするスクリプト。

使い方:
    pip install matplotlib numpy shapely
    python3 make_infographic.py   # mongol_empire.png を出力（2000x1400）

海岸線は Natural Earth ne_50m_land（パブリックドメイン）。
各ウルスの範囲は1300年ごろのおおよその領域を手で描いた多角形を陸地で切り抜いたもの。
"""
import json
import os
import urllib.request

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon as MplPolygon  # noqa: E402
from shapely.geometry import Polygon, box, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
LAND_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"
OUT = os.path.join(HERE, "mongol_empire.png")

for f in font_manager.findSystemFonts():
    if "ipag" in os.path.basename(f).lower():
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = ["IPAPGothic", "IPAGothic", "sans-serif"]

# ---------- 配色（dataviz の参照パレット。4色は all-pairs で検証済み） ----------
SURFACE = "#fcfcfb"
OCEAN = "#e4edf3"
LAND = "#ebe7de"
LAND_EDGE = "#c9c3b5"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8983"
KHANATES = {  # 名前, 色, ラベル位置, 補足
    "yuan": ("元（大元ウルス）", "#2a78d6", (108, 36.5), "フビライの系統・中国を支配"),
    "chagatai": ("チャガタイ・ウルス", "#1baf7a", (80, 39.2), "中央アジア"),
    "ilkhan": ("イルハン朝", "#eb6834", (54, 29.8), "西アジア"),
    "jochi": ("ジョチ・ウルス\n（キプチャク・ハン国）", "#4a3aa7", (61, 47.8), "ロシア草原"),
}
LON0, LON1, LAT0, LAT1 = 12, 146, 10, 64
KX = np.cos(np.radians(40))

# 1300年ごろのおおよその範囲（陸地で切り抜くので海岸線は粗くてよい）
REGIONS = {
    "yuan": [(80, 36), (86, 45), (89, 49), (92, 53), (105, 54), (122, 56), (142, 56), (142, 44),
             (131, 43), (129, 42), (124.5, 40), (122, 39), (128, 33), (122, 20), (108, 18), (100, 21),
             (97, 24), (92, 27), (80, 30), (78, 34)],
    "chagatai": [(60, 38), (61, 42), (64, 45), (72, 48), (82, 48), (89, 49), (86, 45), (80, 36), (78, 34),
                 (74, 34), (70, 34), (66, 36)],
    "ilkhan": [(29, 36), (28, 41), (36, 42), (42, 42), (47, 42.5), (50, 41), (54, 38), (60, 38), (66, 36),
               (70, 34), (67, 26), (58, 24), (56, 27), (50, 29), (48, 30), (45, 31), (40, 33), (37, 35.5),
               (35, 36)],
    "jochi": [(27, 46), (30, 50), (36, 53), (48, 57), (56, 60), (66, 57), (72, 52), (72, 48), (64, 45),
              (61, 42), (60, 38), (54, 38), (50, 41), (47, 42.5), (42, 42), (38, 45), (33, 45.5)],
}
VASSALS = {  # 属国（服属した国）
    "高麗（属国）": ("yuan", [(124.5, 40), (129, 42), (130.5, 42.5), (130, 34), (126, 33.5), (124.5, 37.5)],
                   (127.6, 37.2)),
    "ルーシ諸公国（属国）": ("jochi", [(23, 50), (27, 57), (36, 60), (46, 61), (48, 57), (36, 53), (30, 50)],
                         (35.5, 57.2)),
}
EARLY = [(52, 38), (54, 46), (60, 50), (72, 52), (90, 53), (108, 52), (122, 50), (124, 45), (118, 39),
         (108, 36), (98, 37), (86, 41), (76, 37), (68, 35), (60, 34)]  # 1227年ごろ（チンギス死去時）

CITIES = [("カラコルム", 102.8, 47.2, (0.6, 0.9)), ("大都（北京）", 116.4, 39.9, (0.6, -1.1)),
          ("サマルカンド", 67.0, 39.6, (-0.6, -1.2)), ("バグダード", 44.4, 33.3, (-0.5, -1.2)),
          ("キエフ", 30.5, 50.4, (-0.3, -1.1)), ("サライ", 47.6, 46.9, (0.8, -1.0))]

CAMPAIGNS = [  # (経路, ラベル, ラベル位置)
    ([(104, 47), (112, 44), (116, 40.5)], "1211〜34\n金を攻略", (113.5, 45.5)),
    ([(98, 46), (82, 44), (68, 40)], "1219〜21\nホラズム遠征", (84, 46.3)),
    ([(62, 50), (45, 52), (31, 51)], "1236〜42 バトゥの西征", (47, 54.2)),
    ([(31, 51), (22, 51), (16.5, 51)], "", None),
    ([(64, 37), (54, 35), (45, 33.6)], "1258 バグダード陥落", (57.5, 34.4)),
    ([(116, 39), (119, 34), (120, 30.6)], "1276〜79\n南宋を滅ぼす", (125.8, 29.2)),
]
DEFEATS = [("1241 ワールシュタット\n（勝利後に撤退）", 16.2, 51.2, (1.5, 3.3), False),
           ("1260 アイン・ジャールート\nマムルーク朝に敗北", 35.4, 32.5, (-6.5, -3.0), True),
           ("1274・1281\n元寇（失敗）", 130.4, 33.6, (7.2, -1.2), True),
           ("1288 白藤江\n（ベトナム・失敗）", 106.8, 20.9, (-8.5, -2.4), True),
           ("↓ 1293 ジャワ遠征（失敗）", 112.5, 12.0, (0, 0.6), None)]


def smooth(pts, n=3):
    """Chaikin 法で多角形の角を丸める（手描きの境界を自然に見せる）"""
    p = np.asarray(pts, dtype=float)
    for _ in range(n):
        q = np.roll(p, -1, axis=0)
        p = np.vstack([np.column_stack([0.75 * p + 0.25 * q]), np.column_stack([0.25 * p + 0.75 * q])])
        p = p.reshape(2, -1, 2).transpose(1, 0, 2).reshape(-1, 2)
    return p


def load_land():
    path = os.path.join(CACHE, "land50.geojson")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        urllib.request.urlretrieve(LAND_URL, path)
    with open(path, encoding="utf-8") as fp:
        gj = json.load(fp)
    view = box(LON0 - 5, LAT0 - 5, LON1 + 5, LAT1 + 5)
    geoms = [shape(f["geometry"]) for f in gj["features"]]
    return unary_union([g.intersection(view) for g in geoms if g.intersects(view)])


def polys(g):
    for p in getattr(g, "geoms", [g]):
        if p.geom_type == "Polygon" and not p.is_empty:
            yield p


def fill(ax, g, **kw):
    for p in polys(g):
        ax.add_patch(MplPolygon(np.asarray(p.exterior.coords), closed=True, **kw))


def halo(w=3.2, c=SURFACE):
    return [pe.withStroke(linewidth=w, foreground=c)]


def draw_map(ax, land):
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.set_aspect(1 / KX)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((LON0, LAT0), LON1 - LON0, LAT1 - LAT0, color=OCEAN, zorder=0))
    fill(ax, land, facecolor=LAND, edgecolor=LAND_EDGE, lw=0.6, zorder=1)

    for key, pts in REGIONS.items():
        name, col, _, _ = KHANATES[key]
        g = Polygon(smooth(pts)).buffer(0).intersection(land)
        fill(ax, g, facecolor=col, alpha=0.62, edgecolor=SURFACE, lw=2.0, zorder=2)
    for name, (parent, pts, lab) in VASSALS.items():
        col = KHANATES[parent][1]
        g = Polygon(pts).buffer(0).intersection(land)
        fill(ax, g, facecolor="none", edgecolor=col, hatch="////", lw=0, alpha=0.9, zorder=2)
        fill(ax, g, facecolor="none", edgecolor=col, lw=1.0, alpha=0.9, zorder=2)
        ax.text(*lab, name, fontsize=11, color=INK2, ha="center", va="center", zorder=6,
                path_effects=halo())

    early = Polygon(smooth(EARLY))
    xs, ys = early.exterior.xy
    ax.plot(xs, ys, color=INK, lw=1.8, ls=(0, (5, 3)), zorder=4)
    ax.text(93, 55.6, "1227年ごろの範囲（チンギス・カン死去時）", fontsize=11.5, color=INK, ha="center",
            zorder=6, path_effects=halo())

    for pts, label, lpos in CAMPAIGNS:
        xs, ys = zip(*pts)
        ax.plot(xs[:-1], ys[:-1], color=INK, lw=2.2, zorder=5, solid_capstyle="round",
                path_effects=[pe.withStroke(linewidth=5, foreground=SURFACE)])
        ax.annotate("", xy=pts[-1], xytext=pts[-2], zorder=5,
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=2.2, mutation_scale=18,
                                    shrinkA=0, shrinkB=0))
        if label:
            ax.text(*lpos, label, fontsize=11.5, color=INK, ha="center", va="center", zorder=7,
                    fontweight="bold", path_effects=halo(3.6))

    for label, x, y, (dx, dy), failed in DEFEATS:
        if failed is not None:
            ax.plot(x, y, marker="X", ms=13, color=INK if failed else INK2, mec=SURFACE, mew=1.5, zorder=8)
        ax.text(x + dx, y + dy, label, fontsize=10.5, color=INK, ha="center", va="center", zorder=8,
                path_effects=halo(3.4))

    for name, x, y, (dx, dy) in CITIES:
        ax.plot(x, y, "o", ms=6, color=INK, mec=SURFACE, mew=1.2, zorder=8)
        ax.text(x + dx, y + dy, name, fontsize=10, color=INK2, ha="left" if dx > 0 else "right",
                va="center", zorder=8, path_effects=halo())

    for key, (name, col, (x, y), sub) in KHANATES.items():
        ax.text(x, y, name, fontsize=16, color=INK, ha="center", va="center", fontweight="bold",
                zorder=9, path_effects=halo(4.5))
        ax.text(x, y - (2.6 if "\n" in name else 1.7), sub, fontsize=10.5, color=INK2, ha="center",
                va="center", zorder=9, path_effects=halo(3.5))

    ax.text(LON0 + 0.8, LAT0 + 1.0, "塗り＝1300年ごろのおおよその勢力範囲　✕＝敗北・遠征失敗　斜線＝属国",
            fontsize=10.5, color=INK2, ha="left", va="bottom", zorder=9, path_effects=halo())


REASONS = [
    ("1", "後継争いで分裂", "1260年、フビライとアリクブケが帝位を争う。\n以後、4つのウルスが事実上独立"),
    ("2", "遠征の失敗", "エジプト・日本・ベトナム・ジャワで敗退。\n拡大が止まり、戦費だけが残る"),
    ("3", "疫病と天災", "14世紀、黒死病や飢饉が交易路と\n草原・農村を直撃"),
    ("4", "財政難と反乱", "元は紙幣（交鈔）の乱発でインフレ。\n1351年の紅巾の乱から明が台頭"),
]

EXPAND = [(1206, "チンギス・カン即位"), (1219, "ホラズム遠征"), (1234, "金を滅ぼす"),
          (1241, "ワールシュタットの戦い"), (1258, "バグダード陥落"), (1271, "国号を「元」に"),
          (1279, "南宋を滅ぼす\n＝最大版図")]
DECLINE = [(1260, "継承戦争・\nアイン・ジャールート敗北"), (1281, "元寇（2度目）失敗"),
           (1335, "イルハン朝が崩壊"), (1351, "紅巾の乱"), (1368, "明が大都を占領\n元は北へ（北元）"),
           (1502, "ジョチ・ウルス滅亡")]


def tx(year):
    """年→横位置（1200〜1300 を広く、1300〜1510 を圧縮）"""
    if year <= 1300:
        return 0.06 + (year - 1200) / 100 * 0.52
    return 0.58 + (year - 1300) / 210 * 0.36


def draw_timeline(fig):
    y = 0.155
    ax = fig.add_axes([0, 0, 1, 1], facecolor="none")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    # 期間の帯
    for (a, b, lab, col, lx) in [(1206, 1279, "拡大期", "#2a78d6", (1206 + 1219) / 2),
                                 (1279, 1368, "分裂・衰退期", MUTED, 1308)]:
        ax.add_patch(plt.Rectangle((tx(a), y - 0.007), tx(b) - tx(a), 0.014, color=col, alpha=0.85, lw=0))
        ax.text(tx(lx), y, lab, fontsize=11.5, color="#ffffff", ha="center", va="center",
                fontweight="bold")
    ax.add_patch(plt.Rectangle((tx(1368), y - 0.003), tx(1510) - tx(1368), 0.006, color=MUTED, alpha=0.4, lw=0))
    ax.plot([tx(1200), tx(1206)], [y, y], color=MUTED, lw=1)
    for yr in (1200, 1250, 1300, 1400, 1500):
        ax.text(tx(yr), y - 0.02, f"{yr}", fontsize=10, color=MUTED, ha="center", va="top")
    ax.text(tx(1300) + 0.004, y + 0.012, "≈ ここから縮尺を圧縮", fontsize=9, color=MUTED, ha="left")

    levels_up = [0.06, 0.105, 0.06, 0.105, 0.06, 0.105, 0.06]
    for (yr, lab), lv in zip(EXPAND, levels_up):
        x = tx(yr)
        ax.plot([x, x], [y + 0.008, y + lv - 0.012], color="#2a78d6", lw=1.2)
        ax.plot(x, y, "o", ms=7, color="#2a78d6", mec=SURFACE, mew=1.5)
        ax.text(x, y + lv, f"{yr}  {lab}", fontsize=11, color=INK, ha="center", va="bottom")
    levels_dn = [0.045, 0.045, 0.045, 0.095, 0.045, 0.045]
    aligns = ["center", "center", "right", "center", "left", "center"]
    for (yr, lab), lv, ha in zip(DECLINE, levels_dn, aligns):
        x = tx(yr)
        ax.plot([x, x], [y - 0.008, y - lv + 0.004], color=INK2, lw=1.2)
        ax.plot(x, y, "o", ms=7, color=INK2, mec=SURFACE, mew=1.5)
        ax.text(x + {"left": -0.004, "right": 0.004, "center": 0}[ha], y - lv, f"{yr}  {lab}", fontsize=11,
                color=INK, ha=ha, va="top")


def build():
    """図解を描いた Figure と地図の Axes を返す（動画スクリプトからも使う）"""
    land = load_land()
    fig = plt.figure(figsize=(20, 14), dpi=100)
    fig.patch.set_facecolor(SURFACE)

    fig.text(0.03, 0.955, "モンゴル帝国の拡大と衰退", fontsize=40, fontweight="bold", color=INK, va="center")
    fig.text(0.03, 0.912, "草原の一部族から、ユーラシアの大半を治める史上最大級の陸の帝国へ。そして約160年で4つに分かれ、崩れていった。",
             fontsize=15, color=INK2, va="center")
    # ヒーロー数値
    fig.patches.append(FancyBboxPatch((0.735, 0.885), 0.24, 0.09, boxstyle="round,pad=0.006,rounding_size=0.012",
                                      transform=fig.transFigure, facecolor="#eef3fa", edgecolor="none",
                                      figure=fig))
    fig.text(0.748, 0.948, "最大版図（1279年ごろ）", fontsize=13, color=INK2, va="center")
    fig.text(0.748, 0.905, "約2,400万km²", fontsize=30, fontweight="bold", color=INK, va="center")
    fig.text(0.965, 0.905, "推定\n陸地の約16%", fontsize=10.5, color=INK2, va="center", ha="right")

    ax = fig.add_axes([0.01, 0.30, 0.68, 0.58])
    draw_map(ax, land)

    # 右パネル：衰退の理由
    x0 = 0.715
    fig.text(x0, 0.845, "なぜ衰退したのか", fontsize=22, fontweight="bold", color=INK, va="center")
    yy = 0.79
    for num, head, body in REASONS:
        fig.patches.append(FancyBboxPatch((x0, yy - 0.083), 0.26, 0.098,
                                          boxstyle="round,pad=0.004,rounding_size=0.01",
                                          transform=fig.transFigure, facecolor="#f3f2ee", edgecolor="none",
                                          figure=fig))
        fig.text(x0 + 0.012, yy - 0.001, num, fontsize=22, fontweight="bold", color=MUTED, va="center")
        fig.text(x0 + 0.04, yy - 0.001, head, fontsize=16, fontweight="bold", color=INK, va="center")
        fig.text(x0 + 0.04, yy - 0.045, body, fontsize=12, color=INK2, va="center", linespacing=1.5)
        yy -= 0.118
    fig.text(x0, 0.31, "強み（騎馬の機動力・駅伝制）が、広がりすぎた\n帝国をまとめる力にはならなかった。",
             fontsize=12.5, color=INK, va="center", linespacing=1.5)

    draw_timeline(fig)
    fig.text(0.03, 0.012, "地図: Natural Earth（パブリックドメイン）／領域は1300年ごろのおおよその範囲を示した模式図。面積は Taagepera などによる推定値。",
             fontsize=9.5, color=MUTED, va="bottom")
    return fig, ax


def main():
    fig, _ = build()
    fig.savefig(OUT, dpi=100, facecolor=SURFACE)
    print("done:", OUT)


if __name__ == "__main__":
    main()
