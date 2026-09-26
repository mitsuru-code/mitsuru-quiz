"""日本列島のなりたち（約3000万年前→現在）を1分動画にするスクリプト。

使い方:
    pip install matplotlib numpy shapely imageio-ffmpeg
    python3 make_video.py            # japan_formation.mp4 を出力
    python3 make_video.py --preview  # 各シーンの静止画だけ出力

海岸線は Natural Earth (ne_50m_land, パブリックドメイン) を使用。
復元は教育用の簡略モデル（観音開き説：西南日本 時計回り約45°、東北日本 反時計回り約30°）。
"""
import json
import math
import os
import sys
import urllib.request

import imageio_ffmpeg
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon as MplPolygon  # noqa: E402
from shapely.affinity import rotate, translate  # noqa: E402
from shapely.geometry import Polygon, box, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LAND_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"
LAND_CACHE = os.path.join(HERE, ".ne_50m_land.geojson")
OUT = os.path.join(HERE, "japan_formation.mp4")

W, H, FPS, DURATION = 1280, 720, 30, 60
LON0, LON1, LAT0, LAT1 = 108.5, 156.0, 25.0, 46.5
KX = math.cos(math.radians(36))  # 経度→平面の縮尺（正距円筒の横伸びを補正）

for f in font_manager.findSystemFonts():
    if "ipag" in f.lower() or "noto" in f.lower() and "cjk" in f.lower():
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = ["IPAGothic", "IPAPGothic", "Noto Sans CJK JP", "sans-serif"]

# ---------- 色 ----------
C_SEA_DEEP = "#0b2a4a"
C_SEA = "#15406b"
C_CONT = "#8a7b5c"
C_CONT_EDGE = "#5c5038"
C_SW = "#e8a33d"
C_NE = "#58b368"
C_JP = "#9ccf6a"
C_LGM = "#b7a77f"
C_TEXT = "#ffffff"


# ---------- 地形データ ----------
def load_land():
    if not os.path.exists(LAND_CACHE):
        urllib.request.urlretrieve(LAND_URL, LAND_CACHE)
    with open(LAND_CACHE, encoding="utf-8") as fp:
        gj = json.load(fp)
    view = box(LON0 - 8, LAT0 - 6, LON1 + 8, LAT1 + 8)
    polys = []
    for feat in gj["features"]:
        g = shape(feat["geometry"]).intersection(view)
        if g.is_empty:
            continue
        polys.extend(getattr(g, "geoms", [g]))
    return [p for p in polys if p.geom_type == "Polygon"]


def to_xy(g):
    """lon/lat → 回転計算用の平面座標（x=経度*KX）"""
    from shapely.affinity import scale
    return scale(g, xfact=KX, yfact=1.0, origin=(0, 0))


def to_ll(g):
    from shapely.affinity import scale
    return scale(g, xfact=1 / KX, yfact=1.0, origin=(0, 0))


def classify(polys):
    """大陸側 / 西南日本 / 東北日本 / 固定（琉球・伊豆諸島など）に分ける"""
    cont, jp, static = [], [], []
    for p in polys:
        c = p.centroid
        lon, lat = c.x, c.y
        in_jp = 128.9 <= lon <= 149.5 and 30.9 <= lat <= 45.8
        sakhalin = lon > 141 and lat > 45.8
        izu = 139.0 < lon < 141.0 and lat < 34.65
        if in_jp and not sakhalin and not izu:
            jp.append(p)
        elif (lon > 122 and lat < 31) or izu:
            static.append(p)  # 琉球・伊豆諸島・台湾周辺の島は固定表示
        else:
            cont.append(p)
    japan = unary_union(jp)
    # 糸魚川－静岡構造線を延長した線で東西に分割
    istl_west = Polygon([(137.2, 50), (137.86, 37.04), (138.1, 36.05), (138.38, 34.97), (138.6, 30),
                         (120, 30), (120, 50)])
    sw = japan.intersection(istl_west)
    ne = japan.difference(istl_west)
    return unary_union(cont), sw, ne, unary_union(static)


# 回転中心（lon, lat）と、過去（約2500万年前）の姿勢
SW_PIVOT = (129.6, 34.0)   # 対馬付近を軸に西南日本が時計回り
NE_PIVOT = (142.5, 44.5)   # 北海道付近を軸に東北日本が反時計回り
SW_ANGLE_PAST = 45.0       # 過去は反時計回りに45°戻す
NE_ANGLE_PAST = -30.0      # 過去は時計回りに30°戻す
SW_SHIFT_PAST = (-2.4, 1.0)  # 大陸沿いへ寄せる平行移動（lon, lat）
NE_SHIFT_PAST = (-3.6, 1.0)


def place(block, pivot, angle, shift, k):
    """k=1 で過去の姿勢、k=0 で現在の姿勢"""
    if k <= 0:
        return block
    g = to_xy(block)
    g = rotate(g, angle * k, origin=(pivot[0] * KX, pivot[1]), use_radians=False)
    g = to_ll(g)
    return translate(g, shift[0] * k, shift[1] * k)


# ---------- 氷期（約2万年前）の陸橋：海面-120m で陸化した大陸棚の簡略形 ----------
LGM_POLYS = [
    # 黄海・東シナ海の大陸棚
    [(117, 38.8), (118.5, 40.5), (121, 41), (122.5, 40.2), (125, 39.9), (126.9, 37.6), (126.9, 34.4),
     (127.8, 34.4), (128.2, 33.4), (126.6, 31.4), (124.6, 28.6), (121.8, 25.4), (119.5, 24.0), (117, 24.5)],
    # 瀬戸内海・関門（九州・四国・本州が陸続き）
    [(130.8, 33.7), (131.1, 34.1), (132.2, 34.4), (133.1, 34.6), (134.3, 34.85), (135.3, 34.7),
     (135.1, 34.1), (134.6, 33.85), (133.5, 33.85), (132.4, 33.3), (131.6, 33.15), (130.8, 33.4)],
    # 宗谷海峡（北海道－サハリン）
    [(141.4, 45.1), (142.3, 45.3), (142.4, 46.6), (141.7, 46.6), (141.4, 45.8)],
    # 間宮海峡付近（サハリン－大陸）
    [(140.6, 50.5), (142.2, 50.5), (142.2, 53.5), (140.6, 53.5)],
    # 東京湾
    [(139.6, 35.0), (140.0, 34.95), (140.1, 35.7), (139.75, 35.7)],
]

# フォッサマグナ（中央日本を南北に横切る海域）
FOSSA = Polygon([(137.86, 37.8), (137.86, 37.04), (138.1, 36.05), (138.38, 34.97), (138.3, 34.2),
                 (140.4, 34.6), (140.3, 35.5), (139.4, 37.0), (139.3, 38.2)])


# ---------- 描画 ----------
def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def patches(ax, geom, **kw):
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        ax.add_patch(MplPolygon(np.asarray(p.exterior.coords), closed=True, **kw))


# シーン定義: (開始秒, 年代表示, 見出し, 説明)
SCENES = [
    (0, "", "日本列島のなりたち", "大陸の一部から、いまの形になるまで"),
    (4, "約3000万年前", "大陸の一部だった", "日本列島のもとは、ユーラシア大陸の東のはしにありました"),
    (11, "約2500万年前", "大陸が裂けはじめる", "地下からマグマが上がり、大陸の縁に割れ目ができます"),
    (18, "約2000万〜1500万年前", "観音開きで日本海が誕生", "西南日本は時計回り、東北日本は反時計回りに回転しながら大陸から離れました"),
    (31, "約1500万年前", "列島の中央は海だった", "東西の間は「フォッサマグナ」と呼ばれる深い海。多くの土地はまだ海の下でした"),
    (39, "数百万年前〜", "押されて隆起、ひとつの島に", "プレートに押されて土地が盛り上がり、伊豆も衝突。山脈ができて東西がつながりました"),
    (47, "約2万年前（氷期）", "海面が約120m低かった", "北海道はサハリン経由で大陸と陸続き。九州・四国・本州もつながっていました"),
    (54, "現在", "いまの日本列島", "氷期が終わり海面が上昇。約1万年前に現在の形になりました"),
]


def scene_at(t):
    idx = 0
    for i, s in enumerate(SCENES):
        if t >= s[0]:
            idx = i
    start = SCENES[idx][0]
    end = SCENES[idx + 1][0] if idx + 1 < len(SCENES) else DURATION
    return idx, (t - start) / (end - start)


def drift_k(t):
    """1=過去の姿勢（大陸に接する）, 0=現在"""
    if t < 11:
        return 1.0
    if t < 18:
        return 1.0 - 0.12 * ease((t - 11) / 7)      # 裂けはじめ
    if t < 31:
        return 0.88 * (1 - ease((t - 18) / 12))      # 観音開き
    return 0.0


def render_frame(fig, ax, t, geo):
    cont, sw, ne, static = geo
    ax.clear()
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.set_aspect(1 / KX)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((LON0, LAT0), LON1 - LON0, LAT1 - LAT0, color=C_SEA, zorder=0))

    idx, u = scene_at(t)
    k = drift_k(t)

    # 氷期の陸橋
    lgm_a = 0.0
    if 47 <= t < 54:
        lgm_a = ease((t - 47) / 1.5)
    elif 54 <= t < 56:
        lgm_a = 1 - ease((t - 54) / 2)
    if lgm_a > 0:
        for pts in LGM_POLYS:
            ax.add_patch(MplPolygon(pts, closed=True, color=C_LGM, alpha=lgm_a, zorder=1, lw=0))

    patches(ax, cont, facecolor=C_CONT, edgecolor=C_CONT_EDGE, lw=0.6, zorder=2)
    patches(ax, static, facecolor=C_JP, edgecolor="none", zorder=2)

    # 裂け目（割れ目の赤い光）
    if 11 <= t < 22:
        a = ease((t - 11) / 2) * (1 - ease((t - 19) / 3))
        rift = [(129.0, 34.9), (129.6, 37.3), (130.6, 39.8), (133.3, 42.3), (136.8, 44.3), (139.8, 46.5)]
        xs, ys = zip(*rift)
        ax.plot(xs, ys, color="#ff5a36", lw=6, alpha=0.35 * a, zorder=5, solid_capstyle="round")
        ax.plot(xs, ys, color="#ffd27a", lw=1.8, alpha=0.9 * a, zorder=5, ls=(0, (4, 3)))

    # 陸塊の色：動いている間は東西を色分け、つながった後は1色に
    mix = ease((t - 41) / 5)
    sw_c = blend(C_SW, C_JP, mix)
    ne_c = blend(C_NE, C_JP, mix)
    sw_now = place(sw, SW_PIVOT, SW_ANGLE_PAST, SW_SHIFT_PAST, k)
    ne_now = place(ne, NE_PIVOT, NE_ANGLE_PAST, NE_SHIFT_PAST, k)
    if t >= 46:
        patches(ax, geo_jp_union(sw, ne), facecolor=C_JP, edgecolor="#f0ffe6", lw=0.8, zorder=4)
    else:
        patches(ax, sw_now, facecolor=sw_c, edgecolor="#fff3d6", lw=0.8, zorder=4)
        patches(ax, ne_now, facecolor=ne_c, edgecolor="#e6ffe9", lw=0.8, zorder=4)

    # フォッサマグナの海（1500万年前ごろ→数百万年前に隆起して消える）
    fossa_a = 0.0
    if 26 <= t < 39:
        fossa_a = ease((t - 26) / 4)
    elif 39 <= t < 46:
        fossa_a = 1 - ease((t - 39) / 7)
    if fossa_a > 0:
        patches(ax, FOSSA.intersection(unary_union([sw, ne])).buffer(0.02), facecolor=C_SEA,
                edgecolor="none", alpha=fossa_a, zorder=5)
        if 31 <= t < 44:
            txt(ax, 141.3, 33.4, "フォッサマグナ（海）", 13, alpha=fossa_a, color="#bfe3ff")

    # 回転の矢印
    if 18 <= t < 30:
        a = min(ease((t - 18) / 1.5), 1 - ease((t - 28) / 2))
        arc(ax, SW_PIVOT, 6.8, 55, 20, "#ffcf80", a)    # 時計回り
        arc(ax, NE_PIVOT, 6.5, 225, 262, "#9ef0aa", a)  # 反時計回り
        txt(ax, 137.2, 40.0, "時計回り", 13, alpha=a, color="#ffcf80")
        txt(ax, 146.8, 39.4, "反時計回り", 13, alpha=a, color="#9ef0aa")

    # プレートの押す矢印
    if 39 <= t < 47:
        a = min(ease((t - 39) / 1.5), 1 - ease((t - 45.5) / 1.5))
        ax.annotate("", xy=(144.3, 38.5), xytext=(152.5, 38.5),
                    arrowprops=dict(arrowstyle="-|>", color="#ff8a6a", lw=4, mutation_scale=28), alpha=a, zorder=6)
        txt(ax, 150.5, 39.7, "太平洋プレート", 13, alpha=a, color="#ffb39e")
        ax.annotate("", xy=(139.0, 34.3), xytext=(140.2, 29.0),
                    arrowprops=dict(arrowstyle="-|>", color="#ff8a6a", lw=4, mutation_scale=28), alpha=a, zorder=6)
        txt(ax, 142.8, 30.2, "フィリピン海プレート\n（伊豆の衝突）", 12, alpha=a, color="#ffb39e")

    # 氷期ラベル
    if lgm_a > 0.3:
        txt(ax, 146.0, 45.6, "サハリン経由で\n大陸と陸続き", 12, alpha=lgm_a, color="#fff1c9")
        txt(ax, 124.0, 31.0, "陸化した大陸棚", 12, alpha=lgm_a, color="#fff1c9")

    # 地名
    txt(ax, 116, 40.5, "ユーラシア大陸", 18, color="#f3ead2", alpha=0.9)
    txt(ax, 148, 31, "太平洋", 18, color="#9cc4ea", alpha=0.9)
    sea_a = ease((t - 24) / 3)
    if sea_a > 0:
        txt(ax, 132.3, 40.8, "日本海", 18, color="#9cc4ea", alpha=sea_a)
    if t >= 54:
        a = ease((t - 54.5) / 1.5)
        for name, x, y in [("北海道", 143.0, 43.4), ("本州", 139.6, 38.3), ("四国", 133.4, 32.8), ("九州", 130.1, 31.9)]:
            txt(ax, x, y, name, 14, alpha=a, color="#ffffff", stroke=True)

    draw_hud(fig, t, idx, u)


_UNION = {}


def geo_jp_union(sw, ne):
    if "u" not in _UNION:
        _UNION["u"] = unary_union([sw.buffer(0.01), ne.buffer(0.01)])
    return _UNION["u"]


def blend(c1, c2, m):
    a = np.array(matplotlib.colors.to_rgb(c1))
    b = np.array(matplotlib.colors.to_rgb(c2))
    return tuple(a * (1 - m) + b * m)


def arc(ax, center, r, a0, a1, color, alpha):
    th = np.radians(np.linspace(a0, a1, 40))
    xs = center[0] + r * np.cos(th) / KX
    ys = center[1] + r * np.sin(th)
    ax.plot(xs[:-3], ys[:-3], color=color, lw=3, alpha=alpha, zorder=6)
    ax.annotate("", xy=(xs[-1], ys[-1]), xytext=(xs[-4], ys[-4]),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=3, mutation_scale=22), alpha=alpha, zorder=6)


def txt(ax, x, y, s, size, alpha=1.0, color=C_TEXT, stroke=True):
    import matplotlib.patheffects as pe
    ax.text(x, y, s, fontsize=size, color=color, alpha=alpha, ha="center", va="center", zorder=8,
            fontweight="bold", path_effects=[pe.withStroke(linewidth=3, foreground="#0b1e33", alpha=alpha)] if stroke else None)


def draw_hud(fig, t, idx, u):
    fig.texts.clear()
    fig.patches.clear()
    _, era, head, desc = SCENES[idx]
    fade = min(ease(u * 6), 1.0) if idx > 0 else 1.0

    if idx == 0:
        a = ease(t / 0.8) * (1 - ease((t - 3.3) / 0.7))
        fig.patches.append(FancyBboxPatch((0.2, 0.36), 0.6, 0.28, boxstyle="round,pad=0.01,rounding_size=0.02",
                                          transform=fig.transFigure, facecolor="#0b1e33", alpha=0.8 * a,
                                          edgecolor="#ffffff", lw=1.2, figure=fig))
        fig.text(0.5, 0.54, head, ha="center", va="center", fontsize=46, color=C_TEXT, alpha=a, fontweight="bold")
        fig.text(0.5, 0.43, desc, ha="center", va="center", fontsize=20, color="#cfe6ff", alpha=a)
    else:
        fig.patches.append(FancyBboxPatch((0.015, 0.80), 0.50, 0.17, boxstyle="round,pad=0.008,rounding_size=0.015",
                                          transform=fig.transFigure, facecolor="#0b1e33", alpha=0.78,
                                          edgecolor="#6fa8dc", lw=1, figure=fig))
        fig.text(0.03, 0.925, era, ha="left", va="center", fontsize=26, color="#ffd27a", alpha=fade, fontweight="bold")
        fig.text(0.03, 0.855, head, ha="left", va="center", fontsize=20, color=C_TEXT, alpha=fade, fontweight="bold")
        fig.patches.append(FancyBboxPatch((0.08, 0.035), 0.84, 0.075, boxstyle="round,pad=0.008,rounding_size=0.015",
                                          transform=fig.transFigure, facecolor="#0b1e33", alpha=0.78,
                                          edgecolor="none", figure=fig))
        fig.text(0.5, 0.073, desc, ha="center", va="center", fontsize=17, color=C_TEXT, alpha=fade)

    # 進行バー
    fig.patches.append(plt.Rectangle((0, 0), t / DURATION, 0.008, transform=fig.transFigure,
                                     color="#ffd27a", figure=fig))
    fig.text(0.985, 0.975, "※簡略化した復元図", ha="right", va="top", fontsize=10, color="#9fb6cc")


def main():
    preview = "--preview" in sys.argv
    geo = classify(load_land())
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(C_SEA_DEEP)
    ax = fig.add_axes([0, 0, 1, 1])

    if preview:
        for s in [2, 6, 14, 22, 27, 34, 42, 50, 58]:
            render_frame(fig, ax, s, geo)
            fig.savefig(os.path.join(HERE, f"preview_{s:02d}.png"), dpi=100)
        return

    writer = imageio_ffmpeg.write_frames(OUT, (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                         quality=None, bitrate=None,
                                         output_params=["-crf", "20", "-preset", "medium", "-movflags", "+faststart"])
    writer.send(None)
    n = FPS * DURATION
    for i in range(n):
        render_frame(fig, ax, i / FPS, geo)
        fig.canvas.draw()
        buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
        writer.send(np.ascontiguousarray(buf).tobytes())
        if i % 150 == 0:
            print(f"{i}/{n}", flush=True)
    writer.close()
    print("done:", OUT)


if __name__ == "__main__":
    main()
