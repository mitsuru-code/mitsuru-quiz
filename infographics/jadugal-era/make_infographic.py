"""『天幕のジャドゥーガル』の時代背景（13世紀前半のモンゴル帝国）を1枚の図解（PNG）にするスクリプト。

使い方:
    pip install -r ../mongol-empire/requirements.txt
    python make_infographic.py   # jadugal_era.png を出力（2000x1400）

作品の画像・キャラクターは使わず、史実だけで構成する。
ネタバレを避けるため、年表は 1241年（オゴデイの死）までにとどめる。
地図の描画部品は ../mongol-empire/make_infographic.py を再利用する。
"""
import os

import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
# 同名の make_infographic.py なので、別名でモジュールとして読み込む
_spec = importlib.util.spec_from_file_location(
    "mongol_infographic", os.path.join(HERE, "..", "mongol-empire", "make_infographic.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

OUT = os.path.join(HERE, "jadugal_era.png")
SURFACE, INK, INK2, MUTED = base.SURFACE, base.INK, base.INK2, base.MUTED
EMPIRE = "#2a78d6"   # 帝国の範囲（参照パレット slot 1）
STAGE = "#eb6834"    # 作品の舞台となる地点（slot 2）
LON0, LON1, LAT0, LAT1 = 40, 126, 22, 57
KX = base.KX

# 1241年ごろ（オゴデイ死去時）のおおよその支配範囲
EMPIRE_1241 = [(40, 45), (43, 51), (50, 55), (62, 56), (78, 55), (92, 54), (106, 54), (120, 54), (126, 50),
               (124, 42), (120, 36), (114, 33), (106, 32.5), (99, 35), (90, 37), (80, 35.5), (73, 34),
               (67, 33), (61, 32), (55, 33.5), (50, 36), (46, 38), (42, 40.5)]

PLACES = [  # 名前, lon, lat, ラベルのずらし, 作品の舞台か
    ("カラコルム\n（1235年に都を建設）", 102.8, 47.2, (0.0, 1.9), False),
    ("中都（北京）\n1215年陥落", 116.4, 39.9, (3.8, 0.4), False),
    ("開封\n（金の都）1233年陥落", 114.3, 34.8, (4.6, -0.9), False),
    ("ブハラ", 64.4, 39.8, (-2.2, 0.9), False),
    ("サマルカンド", 67.0, 39.6, (3.3, 1.0), False),
    ("オトラル", 68.3, 42.8, (0.0, 1.1), False),
    ("トゥース", 59.6, 36.4, (-2.6, 1.0), True),
    ("ニーシャープール", 58.8, 36.2, (-0.5, -1.3), True),
    ("バグダード\n（まだ独立）", 44.4, 33.3, (0.0, -1.9), False),
]
CAMPAIGNS = [
    ([(98, 47.5), (84, 46), (70, 43.3)], "1219  ホラズム遠征へ", (86, 44.1)),
    ([(68, 42.5), (65.5, 40.5), (62, 38.2), (60.2, 36.9)], "1220〜21\nホラーサーン攻略", (53.5, 40.3)),
    ([(104, 46.5), (110, 42), (114, 35.8)], "1231〜34  金を滅ぼす", (116.8, 44.3)),
    ([(55, 50), (47, 51), (41, 51.5)], "1236〜  西征\n（ヨーロッパへ）", (47.5, 53.6)),
]

PEOPLE = [  # (x, y, 名前, 説明, 強調)
    (0.50, 0.90, "チンギス・カン", "初代（在位1206〜27）", False),
    (0.11, 0.62, "ジョチ", "長男", False),
    (0.37, 0.62, "チャガタイ", "次男", False),
    (0.63, 0.62, "オゴデイ", "三男・2代皇帝\n（在位1229〜41）", True),
    (0.89, 0.62, "トルイ", "末子", False),
    (0.63, 0.30, "トレゲネ", "オゴデイの妃", True),
    (0.89, 0.30, "ソルコクタニ・ベキ", "トルイの妃\nモンケ・フビライらの母", False),
    (0.37, 0.30, "グユク", "オゴデイと\nトレゲネの長子", False),
]
BOX_W, BOX_TOP, BOX_BOTTOM = 0.21, 0.08, 0.13
GLOSSARY = [
    ("ジャドゥーガル", "ペルシア語で「魔術師」"),
    ("天幕（ゲル）", "遊牧民の移動式住居"),
    ("オルド", "皇帝や妃の宮廷となる天幕群"),
    ("クリルタイ", "皇帝を選ぶ有力者の会議"),
]

EVENTS_UP = [(1206, "チンギス・カン即位"), (1219, "ホラズム遠征"), (1227, "チンギス・カン死去"),
             (1234, "金を滅ぼす"), (1241, "オゴデイ死去")]
EVENTS_DN = [(1215, "中都（北京）陥落"), (1220.6, "ホラーサーン\n諸都市が陥落"), (1229, "オゴデイ即位"),
             (1235, "カラコルム建設"), (1236, "西征開始")]


def draw_map(ax, land):
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.set_aspect(1 / KX)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((LON0, LAT0), LON1 - LON0, LAT1 - LAT0, color=base.OCEAN, zorder=0))
    base.fill(ax, land, facecolor=base.LAND, edgecolor=base.LAND_EDGE, lw=0.6, zorder=1)
    g = Polygon(base.smooth(EMPIRE_1241)).buffer(0).intersection(land)
    base.fill(ax, g, facecolor=EMPIRE, alpha=0.30, edgecolor=EMPIRE, lw=1.6, zorder=2)
    ax.text(92, 52.3, "モンゴル帝国\n（1241年ごろのおおよその範囲）", fontsize=15, fontweight="bold", color=INK,
            ha="center", va="center", zorder=9, path_effects=base.halo(4.5))
    ax.text(114, 27.5, "南宋\n（まだ独立）", fontsize=12, color=INK2, ha="center", va="center", zorder=9,
            path_effects=base.halo())
    ax.text(46.5, 44.3, "カスピ海", fontsize=10, color=MUTED, ha="center", va="center", zorder=9)

    # 作品の舞台（ホラーサーン地方）を丸で囲む
    th = np.linspace(0, 2 * np.pi, 80)
    ax.plot(59.2 + 3.2 * np.cos(th) / KX, 36.3 + 2.4 * np.sin(th), color=STAGE, lw=2.4, zorder=6)
    ax.text(59.2, 31.4, "ホラーサーン地方\n作品の物語はここから", fontsize=12.5, color=INK, fontweight="bold",
            ha="center", va="center", zorder=9, path_effects=base.halo(4))

    for pts, label, lpos in CAMPAIGNS:
        xs, ys = zip(*pts)
        ax.plot(xs[:-1], ys[:-1], color=INK, lw=2.2, zorder=5, solid_capstyle="round",
                path_effects=[pe.withStroke(linewidth=5, foreground=SURFACE)])
        ax.annotate("", xy=pts[-1], xytext=pts[-2], zorder=5,
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=2.2, mutation_scale=18, shrinkA=0, shrinkB=0))
        ax.text(*lpos, label, fontsize=11.5, color=INK, ha="center", va="center", fontweight="bold", zorder=8,
                path_effects=base.halo(3.6))

    for name, x, y, (dx, dy), stage in PLACES:
        ax.plot(x, y, "o", ms=8 if stage else 6, color=STAGE if stage else INK, mec=SURFACE, mew=1.3, zorder=8)
        ax.text(x + dx, y + dy, name, fontsize=11 if stage else 10, color=INK if stage else INK2,
                fontweight="bold" if stage else "normal", ha="center", va="center", zorder=8,
                path_effects=base.halo())
    ax.text(LON0 + 0.6, LAT0 + 0.6, "塗り＝1241年ごろのおおよその範囲（模式図）　オレンジの点と丸＝作品の舞台となる地域",
            fontsize=10.5, color=INK2, ha="left", va="bottom", zorder=9, path_effects=base.halo())


def draw_people(fig):
    ax = fig.add_axes([0.655, 0.43, 0.33, 0.39])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    line = dict(color=MUTED, lw=1.3)
    # 親子（チンギス → 4人の息子）
    px, py = PEOPLE[0][:2]
    bus = (py - BOX_BOTTOM + PEOPLE[1][1] + BOX_TOP) / 2
    ax.plot([px, px], [py - BOX_BOTTOM, bus], **line)
    ax.plot([PEOPLE[1][0], PEOPLE[4][0]], [bus, bus], **line)
    for i in (1, 2, 3, 4):
        ax.plot([PEOPLE[i][0]] * 2, [bus, PEOPLE[i][1] + BOX_TOP], **line)
    # 夫婦（点線）
    for a, b in ((3, 5), (4, 6)):
        ax.plot([PEOPLE[a][0]] * 2, [PEOPLE[a][1] - BOX_BOTTOM, PEOPLE[b][1] + BOX_TOP], color=MUTED, lw=1.3,
                ls=(0, (3, 2)))
    # オゴデイとトレゲネの子 グユク
    mid = (PEOPLE[3][1] - BOX_BOTTOM + PEOPLE[5][1] + BOX_TOP) / 2
    ax.plot([PEOPLE[3][0], PEOPLE[7][0], PEOPLE[7][0]], [mid, mid, PEOPLE[7][1] + BOX_TOP], **line)
    for x, y, name, desc, hl in PEOPLE:
        ax.add_patch(FancyBboxPatch((x - BOX_W / 2, y - BOX_BOTTOM), BOX_W, BOX_TOP + BOX_BOTTOM,
                                    boxstyle="round,pad=0.004,rounding_size=0.02",
                                    facecolor="#e7f0fb" if hl else "#f3f2ee", edgecolor=EMPIRE if hl else "none",
                                    lw=1.4, zorder=3))
        ax.text(x, y + 0.02, name, fontsize=13 if len(name) < 8 else 11, fontweight="bold", color=INK,
                ha="center", va="center", zorder=4)
        ax.text(x, y - 0.065, desc, fontsize=9.5, color=INK2, ha="center", va="center", linespacing=1.3, zorder=4)
    ax.text(0.0, 0.05, "実線＝親子　点線＝夫婦", fontsize=9.5, color=MUTED, va="center")


def tx(year):
    return 0.06 + (year - 1200) / 55 * 0.86


def draw_timeline(fig):
    ax = fig.add_axes([0, 0, 1, 1], facecolor="none")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    y = 0.15
    ax.add_patch(plt.Rectangle((tx(1200), y - 0.006), tx(1241) - tx(1200), 0.012, color=EMPIRE, alpha=0.85, lw=0))
    ax.add_patch(plt.Rectangle((tx(1241), y - 0.006), tx(1255) - tx(1241), 0.012, facecolor="none",
                               edgecolor=MUTED, hatch="////", lw=0.8))
    ax.text((tx(1241) + tx(1255)) / 2, y + 0.03, "1241年〜 トレゲネが国政を担う時代\n（作品の後半。ネタバレ回避のため省略）",
            fontsize=11, color=INK2, ha="center", va="bottom", linespacing=1.4)
    for yr in range(1200, 1256, 10):
        ax.text(tx(yr), y - 0.022, f"{yr}", fontsize=10, color=MUTED, ha="center", va="top")
    for (yr, lab), lv in zip(EVENTS_UP, [0.05, 0.05, 0.05, 0.05, 0.05]):
        x = tx(yr)
        ax.plot([x, x], [y + 0.007, y + lv - 0.008], color=EMPIRE, lw=1.2)
        ax.plot(x, y, "o", ms=7, color=EMPIRE, mec=SURFACE, mew=1.5)
        ax.text(x, y + lv, f"{yr}  {lab}", fontsize=11.5, color=INK, ha="center", va="bottom")
    for (yr, lab), lv, ha in zip(EVENTS_DN, [0.045, 0.045, 0.045, 0.095, 0.045],
                                 ["center", "center", "center", "center", "left"]):
        x = tx(yr)
        ax.plot([x, x], [y - 0.007, y - lv + 0.004], color=INK2, lw=1.2)
        ax.plot(x, y, "o", ms=7, color=INK2, mec=SURFACE, mew=1.5)
        dx = {"left": -0.003, "right": 0.003, "center": 0}[ha]
        ax.text(x + dx, y - lv, f"{int(yr)}  {lab}", fontsize=11.5, color=INK, ha=ha, va="top", linespacing=1.3)


def build():
    land = base.load_land()
    fig = plt.figure(figsize=(20, 14), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.03, 0.955, "『天幕のジャドゥーガル』の時代背景", fontsize=38, fontweight="bold", color=INK, va="center")
    fig.text(0.03, 0.912, "13世紀前半のモンゴル帝国を、史実で整理しました。作品の舞台は、帝国がホラズムを攻め、2代オゴデイのもとで最も勢いのあった時代です。",
             fontsize=14.5, color=INK2, va="center")

    ax = fig.add_axes([0.01, 0.30, 0.63, 0.58])
    draw_map(ax, land)

    fig.text(0.665, 0.855, "登場する時代の主な人物（史実）", fontsize=19, fontweight="bold", color=INK, va="center")
    draw_people(fig)

    fig.text(0.665, 0.405, "用語", fontsize=19, fontweight="bold", color=INK, va="center")
    yy = 0.365
    for term, desc in GLOSSARY:
        fig.text(0.668, yy, term, fontsize=13.5, fontweight="bold", color=INK, va="center")
        fig.text(0.79, yy, desc, fontsize=12.5, color=INK2, va="center")
        yy -= 0.034

    draw_timeline(fig)
    fig.text(0.03, 0.012, "地図: Natural Earth（パブリックドメイン）／範囲は模式図。作品の画像は使用していません。"
             "『天幕のジャドゥーガル』はトマトスープ作（秋田書店）。",
             fontsize=9.5, color=MUTED, va="bottom")
    return fig, ax


def main():
    fig, _ = build()
    fig.savefig(OUT, dpi=100, facecolor=SURFACE)
    print("done:", OUT)


if __name__ == "__main__":
    main()
