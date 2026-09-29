"""ホルムズ海峡の瀬取り（STS）図解を、カメラワーク＋ナレーションで動画にするスクリプト（PCで実行）。

運用は豆知識と同じ「素材は機械、文章と投稿は人」:
    1. 素材メモ.md の事実をもとに、narration.txt に自分の言葉でナレーションを書く
    2. このスクリプトで動画にする（声は Cloud TTS Chirp 3: HD）
    3. できた mp4 を X公式アプリから手動で投稿する（投稿文も自分で書く）

使い方（詳しくは PC手順.md）:
    pip install -r requirements.txt
    python make_video.py               # out/hormuz_sts_YYYYMMDD.mp4 を出力
    python make_video.py --dry-run     # 音声なし。話す長さを文字数から推定してカメラだけ確認
    python make_video.py --preview     # 各場面の静止画だけ出力

APIキーは環境変数 GOOGLE_TTS_API_KEY か、このフォルダの .env（Git管理外）に書く。
声は TTS_VOICE（既定 ja-JP-Chirp3-HD-Aoede）で変更できる。
合成結果は .cache/ に保存し、同じ文面なら API を再度呼ばない。
"""
import base64
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image

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
W, H, FPS = 1920, 1080, 30
IMAGE = os.path.join(HERE, "hormuz_sts.jpg")  # 1312x1199 の図解
SR = 24000
VOICE = os.environ.get("TTS_VOICE", "ja-JP-Chirp3-HD-Aoede")
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

# 場面ごとのカメラの動き [(区間内の割合, 注目点(x, y), 横幅px)]。座標は図解画像のピクセル（左上が原点）
# narration.txt の「1:」〜「9:」がそれぞれの場面に対応する
FULL = ((656, 600), 2250)
SCENES = [
    ("全体（導入）", [(0.0, *FULL), (1.0, (656, 600), 2150)]),
    ("① 湾内で積み込み", [(0.0, (220, 320), 620), (0.6, (260, 330), 680), (1.0, (430, 380), 760)]),
    ("② ホルムズ海峡を通過", [(0.0, (700, 330), 640), (1.0, (720, 320), 560)]),
    ("③ オマーン沖で積み替え → 写真", [(0.0, (1030, 400), 700), (0.55, (1030, 420), 640),
                               (0.7, (817, 830), 480), (1.0, (817, 830), 450)]),
    ("④ 外洋船が出発", [(0.0, (1060, 560), 700), (0.6, (1060, 540), 760), (1.0, (1145, 830), 480)]),
    ("⑤ シャトル船が戻る", [(0.0, (640, 490), 760), (1.0, (620, 510), 700)]),
    ("メリット", [(0.0, (265, 1090), 600), (1.0, (265, 1090), 560)]),
    ("課題・対象の貨物", [(0.0, (740, 1090), 600), (0.6, (740, 1090), 560), (1.0, (1135, 1090), 520)]),
    ("最後に全体", [(0.0, (656, 330), 1400), (1.0, *FULL)]),
]
NARRATION_FILE = os.path.join(HERE, "narration.txt")
SILENT_SCENE_SEC = 4.0  # ナレーションを書かなかった場面の長さ
LEAD, GAP, TAIL = 0.6, 0.45, 1.6  # 冒頭・文間・末尾の間（秒）


# ---------------------------------------------------------------- 音声
def read_narration():
    """narration.txt を読み、場面番号→本文 の辞書を返す。無ければ雛形を作って終了"""
    if not os.path.exists(NARRATION_FILE):
        with open(NARRATION_FILE, "w", encoding="utf-8") as fp:
            fp.write("# 素材メモ.md を見ながら、各場面のナレーションを自分の言葉で書いてください。\n"
                     "# 1行＝1場面。「番号: 本文」の形。空欄の場面は無音で約4秒映します。\n"
                     "# 目安は1場面25〜50字（全体で約50〜60秒）。# で始まる行は無視されます。\n\n")
            for i, (desc, _) in enumerate(SCENES, 1):
                fp.write(f"# {i}. {desc}\n{i}: \n\n")
        sys.exit(f"narration.txt の雛形を作りました。ナレーションを書いてから再実行してください: {NARRATION_FILE}")
    texts = {}
    with open(NARRATION_FILE, encoding="utf-8-sig") as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line.replace("：", ":"):
                continue
            num, text = line.replace("：", ":").split(":", 1)
            if num.strip().isdigit():
                texts[int(num)] = text.strip()
    return [texts.get(i, "") for i in range(1, len(SCENES) + 1)]


def tts(text, dry=False):
    """Chirp 3: HD で1文を合成して float32 配列（SR Hz）を返す。dry=True なら長さだけ推定した無音"""
    if not text:
        return np.zeros(int(SILENT_SCENE_SEC * SR), dtype=np.float32)
    if dry:
        return np.zeros(int(len(text) / 7.2 * SR), dtype=np.float32)
    key = os.environ.get("GOOGLE_TTS_API_KEY")
    if not key:
        sys.exit("GOOGLE_TTS_API_KEY が未設定です（--dry-run なら音声なしで確認できます）")
    os.makedirs(CACHE, exist_ok=True)
    h = hashlib.sha1(f"{VOICE}|{text}".encode()).hexdigest()[:16]
    path = os.path.join(CACHE, f"tts_{h}.wav")
    if not os.path.exists(path):
        body = json.dumps({
            "input": {"text": text},
            "voice": {"languageCode": "ja-JP", "name": VOICE},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR},
        }).encode()
        req = urllib.request.Request(f"{TTS_URL}?key={key}", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            audio = base64.b64decode(json.load(r)["audioContent"])
        with open(path, "wb") as fp:
            fp.write(audio)
    with wave.open(path) as wf:
        assert wf.getframerate() == SR, wf.getframerate()
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    # 前後の無音を詰める
    idx = np.where(np.abs(x) > 0.01)[0]
    return x[max(idx[0] - 240, 0): idx[-1] + 2400] if len(idx) else x


def pad_music(n):
    """控えめなアンビエントBGM（Dm - B♭ - F - C）"""
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    chords = [[146.8, 220, 293.7], [116.5, 233.1, 293.7], [174.6, 220, 261.6], [130.8, 196, 329.6]]
    seg = 7.5
    for i in range(int(math.ceil(n / SR / seg))):
        ch = chords[i % 4]
        s0, s1 = int(i * seg * SR), min(int((i + 1) * seg * SR + SR), n)
        tl = t[s0:s1] - t[s0]
        env = np.minimum(1, tl / 2.0) * np.minimum(1, np.maximum(0, (tl[-1] - tl) / 2.0))
        for f in ch:
            out[s0:s1] += (np.sin(2 * np.pi * f * tl) + 0.2 * np.sin(4 * np.pi * f * tl)) * env
    return out / (np.abs(out).max() + 1e-9)


def build_audio(dry):
    clips = [tts(text, dry) for text in read_narration()]
    starts, cur = [], LEAD
    for c in clips:
        starts.append(cur)
        cur += len(c) / SR + GAP
    total = cur - GAP + TAIL
    n = int(total * SR)
    voice = np.zeros(n)
    for s, c in zip(starts, clips):
        i = int(s * SR)
        voice[i:i + len(c)] += c
    from scipy import ndimage
    active = ndimage.maximum_filter1d((np.abs(voice) > 0.01).astype(float), int(SR * 0.6))
    duck = 1 - 0.55 * ndimage.gaussian_filter1d(active, SR * 0.3)
    tt = np.arange(n) / SR
    fade = np.clip(np.minimum(tt / 1.5, (total - tt) / 2.0), 0, 1)
    mix = pad_music(n) * 0.12 * duck * fade + voice * 0.95
    mix /= max(np.abs(mix).max(), 1.0)
    return mix, starts, [len(c) / SR for c in clips], total


# ---------------------------------------------------------------- 映像
def render_canvas():
    """図解画像の周囲に余白を足したキャンバスと座標変換関数を返す"""
    img = Image.open(IMAGE).convert("RGB")
    fw, fh = img.size
    margin = 600
    canvas = Image.new("RGB", (fw + 2 * margin, fh + 2 * margin), img.getpixel((4, 4)))
    canvas.paste(img, (margin, margin))

    def to_px(target):
        return margin + target[0], margin + target[1]

    return canvas, to_px


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def camera_keys(starts, durs, total, to_px):
    """(時刻, cx, cy, 幅px) のキーフレーム列"""
    keys = []
    for (_, moves), s, d in zip(SCENES, starts, durs):
        span = d + GAP
        for frac, target, width in moves:
            cx, cy = to_px(target)
            keys.append((s - 0.35 + frac * span, cx, cy, width))
    keys.sort(key=lambda k: k[0])  # 同時刻のキーは場面順を保つ（座標で並べ替えるとカメラが跳ぶ）
    keys = [(0.0,) + keys[0][1:]] + keys + [(total,) + keys[-1][1:]]
    return keys


def cam_at(t, keys):
    for (t0, *a), (t1, *b) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = ease((t - t0) / max(t1 - t0, 1e-6))
            cx, cy = (p + (q - p) * u for p, q in zip(a[:2], b[:2]))
            w = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * u)  # ズームは対数で補間
            return cx, cy, w
    return keys[-1][1:]


def frame(canvas, cx, cy, w):
    h = w * H / W
    box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return canvas.resize((W, H), Image.BICUBIC, box=box)


def main():
    dry = "--dry-run" in sys.argv or "--preview" in sys.argv
    mix, starts, durs, total = build_audio(dry)
    canvas, to_px = render_canvas()
    keys = camera_keys(starts, durs, total, to_px)
    print(f"total {total:.1f}s", ", ".join(f"{s:.1f}+{d:.1f}" for s, d in zip(starts, durs)), flush=True)

    if "--preview" in sys.argv:
        for i, (s, d) in enumerate(zip(starts, durs)):
            frame(canvas, *cam_at(s + d * 0.5, keys)).save(os.path.join(HERE, f"preview_{i + 1}.png"))
        return

    os.makedirs(CACHE, exist_ok=True)
    wav = os.path.join(CACHE, "mix.wav")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    silent = os.path.join(CACHE, "video.mp4")
    writer = imageio_ffmpeg.write_frames(silent, (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                         macro_block_size=1, output_params=["-crf", "19", "-preset", "slow"])
    writer.send(None)
    n = int(total * FPS)
    for i in range(n):
        writer.send(np.asarray(frame(canvas, *cam_at(i / FPS, keys))).tobytes())
        if i % 300 == 0:
            print(f"{i}/{n}", flush=True)
    writer.close()
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-i", silent]
    if not dry:
        cmd += ["-i", wav, "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100"]
    os.makedirs(OUT_DIR, exist_ok=True)
    name = time.strftime("hormuz_sts_%Y%m%d_%H%M") + ("_dryrun" if dry else "") + ".mp4"
    cmd += ["-c:v", "copy", "-shortest" if not dry else "-an", "-movflags", "+faststart",
            os.path.join(OUT_DIR, name)]
    subprocess.check_call(cmd)
    print("done:", cmd[-1])


if __name__ == "__main__":
    main()
