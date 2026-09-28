"""『天幕のジャドゥーガル』の時代背景の図解を、カメラワーク＋ナレーションで動画にする（PCで実行）。

仕組みは ../mongol-empire/make_video.py と同じで、図解と場面の定義だけを差し替えている。
運用も同じ（素材メモ.md を見て narration.txt を自分で書く → 動画化 → 手動で投稿）。

使い方:
    python make_video.py               # out/jadugal_era_YYYYMMDD_HHMM.mp4 を出力（声は Chirp 3: HD）
    python make_video.py --preview     # 各場面の静止画だけ出力
    TTS_ENGINE=openjtalk python make_video.py   # APIキーが無い時のオフライン音声
"""
import os
import sys

import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
MONGOL = os.path.join(HERE, "..", "mongol-empire")


def _load(name, path):
    """同名ファイルが2つのフォルダにあるので、別名のモジュールとして読み込む"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


jadugal = _load("jadugal_infographic", os.path.join(HERE, "make_infographic.py"))
sys.path.insert(0, MONGOL)  # mongol 側の make_video が make_infographic を import できるように
mv = _load("mongol_make_video", os.path.join(MONGOL, "make_video.py"))

mv._load_dotenv(HERE)
mv.info = jadugal
mv.PREFIX = "jadugal_era"
mv.WORK_DIR = HERE
mv.NARRATION_FILE = os.path.join(HERE, "narration.txt")
mv.OUT_DIR = os.environ.get("VIDEO_OUT_DIR") or os.path.join(HERE, "out")
mv.VOICE = os.environ.get("TTS_VOICE", mv.VOICE)

# 場面ごとのカメラの動き。narration.txt の「1:」〜「8:」に対応する
mv.SCENES = [
    ("全体（導入）", [(0.0, ("fig", 0.5, 0.5), 2000), (1.0, ("fig", 0.5, 0.5), 1900)]),
    ("モンゴル高原 → ホラズム遠征", [(0.0, ("map", 96, 46), 950), (1.0, ("map", 76, 43), 950)]),
    ("ホラーサーン地方（作品の舞台）", [(0.0, ("map", 64, 39), 850), (1.0, ("map", 60, 36.5), 620)]),
    ("主な人物の系図（オゴデイ・トレゲネ）", [(0.0, ("fig", 0.82, 0.70), 820), (1.0, ("fig", 0.84, 0.60), 760)]),
    ("金の滅亡・カラコルム", [(0.0, ("map", 108, 42), 950), (1.0, ("map", 104, 45), 900)]),
    ("西征（ヨーロッパへ）", [(0.0, ("map", 60, 50), 1000), (1.0, ("map", 48, 50), 950)]),
    ("年表（1241年まで）", [(0.0, ("fig", 0.40, 0.15), 1150), (1.0, ("fig", 0.60, 0.15), 1050)]),
    ("用語 → 最後に全体", [(0.0, ("fig", 0.82, 0.31), 900), (0.55, ("fig", 0.82, 0.31), 900),
                      (1.0, ("fig", 0.5, 0.5), 2000)]),
]

if __name__ == "__main__":
    mv.main()
