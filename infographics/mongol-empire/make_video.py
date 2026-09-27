"""モンゴル帝国の図解を、カメラワーク＋ナレーションで動画にするスクリプト（PCで実行）。

運用は豆知識と同じ「素材は機械、文章と投稿は人」:
    1. 素材メモ.md の事実をもとに、narration.txt に自分の言葉でナレーションを書く
    2. このスクリプトで動画にする（声は Cloud TTS Chirp 3: HD）
    3. できた mp4 を X公式アプリから手動で投稿する（投稿文も自分で書く）

使い方（詳しくは PC手順.md）:
    pip install -r requirements.txt
    python make_video.py               # out/mongol_empire_YYYYMMDD.mp4 を出力
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

import make_infographic as info

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(folder=HERE):
    """フォルダの .env（KEY=VALUE 形式）を環境変数に取り込む。既存の環境変数が優先"""
    path = os.path.join(folder, ".env")
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
SCALE = 2  # 図解を2倍解像度で描き、拡大しても文字をくっきりさせる
SR = 24000
VOICE = os.environ.get("TTS_VOICE", "ja-JP-Chirp3-HD-Aoede")
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

# 場面ごとのカメラの動き [(区間内の割合, 注目点, 横幅px@等倍)]。注目点は ("map", lon, lat) か ("fig", x, y)
# narration.txt の「1:」〜「8:」がそれぞれの場面に対応する
SCENES = [
    ("全体", [(0.0, ("fig", 0.5, 0.5), 2000), (1.0, ("fig", 0.5, 0.5), 1900)]),
    ("モンゴル高原・金とホラズムへの遠征", [(0.0, ("map", 102, 46), 800), (0.55, ("map", 105, 45), 950),
                                 (1.0, ("map", 86, 44), 1050)]),
    ("西へ：ワールシュタット・バグダード", [(0.0, ("map", 42, 50), 1000), (0.5, ("map", 32, 50), 950),
                                (1.0, ("map", 45, 36), 950)]),
    ("南宋を滅ぼす → 最大版図の数字", [(0.0, ("map", 115, 34), 1000), (0.45, ("map", 115, 34), 1000),
                              (0.62, ("fig", 0.855, 0.93), 620), (1.0, ("fig", 0.855, 0.93), 600)]),
    ("遠征の失敗（エジプト→日本→ベトナム）", [(0.0, ("map", 38, 33), 900), (0.45, ("map", 128, 30), 1000),
                                   (1.0, ("map", 115, 26), 1050)]),
    ("4つのウルスへの分裂", [(0.0, ("map", 78, 40), 1500), (1.0, ("map", 78, 40), 1400)]),
    ("衰退の理由パネル", [(0.0, ("fig", 0.845, 0.62), 1000), (1.0, ("fig", 0.845, 0.52), 950)]),
    ("年表 → 最後に全体", [(0.0, ("fig", 0.62, 0.16), 1500), (0.6, ("fig", 0.66, 0.16), 1300),
                      (1.0, ("fig", 0.5, 0.5), 2000)]),
]
NARRATION_FILE = os.path.join(HERE, "narration.txt")
WORK_DIR = HERE           # プレビュー画像の出力先（他の図解から流用する時に差し替える）
PREFIX = "mongol_empire"  # 出力ファイル名の頭
SILENT_SCENE_SEC = 4.0  # ナレーションを書かなかった場面の長さ
LEAD, GAP, TAIL = 0.6, 0.45, 1.6  # 冒頭・文間・末尾の間（秒）


# ---------------------------------------------------------------- 音声
def read_narration():
    """narration.txt を読み、場面番号→本文 の辞書を返す。無ければ雛形を作って終了"""
    if not os.path.exists(NARRATION_FILE):
        with open(NARRATION_FILE, "w", encoding="utf-8") as fp:
            fp.write("# 素材メモ.md を見ながら、各場面のナレーションを自分の言葉で書いてください。\n"
                     "# 1行＝1場面。「番号: 本文」の形。空欄の場面は無音で約4秒映します。\n"
                     "# 目安は1場面30〜60字（全体で約50〜60秒）。# で始まる行は無視されます。\n\n")
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


MEI_URL = "https://raw.githubusercontent.com/mmdagent-ex/example/main/voice/mei/mei_normal.htsvoice"


def tts_openjtalk(text):
    """APIキーが無い時の代替: Open JTalk + HTS Voice Mei（名古屋工業大学, CC BY 3.0）でオフライン合成"""
    import pyopenjtalk
    from pyopenjtalk.htsengine import HTSEngine
    from scipy.signal import butter, resample_poly, sosfiltfilt

    path = os.path.join(CACHE, "mei_normal.htsvoice")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        urllib.request.urlretrieve(MEI_URL, path)
    eng = HTSEngine(path.encode())
    eng.set_speed(1.0)
    x = np.asarray(eng.synthesize(pyopenjtalk.extract_fullcontext(text)), dtype=np.float64) / 32768
    x = resample_poly(x, SR, eng.get_sampling_frequency())
    x = sosfiltfilt(butter(4, 7000, "low", fs=SR, output="sos"), x)  # 機械的なざらつきを抑える
    x = x / (np.abs(x).max() + 1e-9) * 0.8
    idx = np.where(np.abs(x) > 0.01)[0]
    return x[max(idx[0] - 240, 0): idx[-1] + 2400].astype(np.float32) if len(idx) else x.astype(np.float32)


def tts(text, dry=False):
    """Chirp 3: HD で1文を合成して float32 配列（SR Hz）を返す。dry=True なら長さだけ推定した無音"""
    if not text:
        return np.zeros(int(SILENT_SCENE_SEC * SR), dtype=np.float32)
    if dry:
        return np.zeros(int(len(text) / 7.2 * SR), dtype=np.float32)
    if os.environ.get("TTS_ENGINE", "chirp").lower() == "openjtalk":
        return tts_openjtalk(text)
    key = os.environ.get("GOOGLE_TTS_API_KEY")
    if not key:
        sys.exit("GOOGLE_TTS_API_KEY が未設定です（--dry-run なら音声なし、TTS_ENGINE=openjtalk ならオフライン音声で作れます）")
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
    """図解を高解像度で描き、周囲に余白を足したキャンバスと座標変換関数を返す"""
    fig, ax = info.build()
    fig.set_dpi(100 * SCALE)
    fig.canvas.draw()
    img = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB")
    fw, fh = img.size
    margin = 400 * SCALE
    canvas = Image.new("RGB", (fw + 2 * margin, fh + 2 * margin), info.SURFACE)
    canvas.paste(img, (margin, margin))

    def to_px(target):
        kind, a, b = target
        if kind == "map":
            x, y = ax.transData.transform((a, b))
        else:
            x, y = fig.transFigure.transform((a, b))
        return margin + x, margin + (fh - y)

    return canvas, to_px


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def camera_keys(starts, durs, total, to_px):
    """(時刻, cx, cy, 幅px) のキーフレーム列"""
    keys = []
    for (_, moves), s, d in zip(SCENES, starts, durs):
        span = (d + GAP) * 0.97  # 場面の終わりのキーが次の場面の始まりと同時刻にならないよう少し手前に
        for frac, target, width in moves:
            cx, cy = to_px(target)
            t = s - 0.35 + frac * span
            if keys and t <= keys[-1][0]:  # 時刻は必ず単調増加（並べ替えると同時刻のキーの順序が崩れて画面が跳ぶ）
                t = keys[-1][0] + 0.01
            keys.append((t, cx, cy, width * SCALE))
    keys = [(0.0,) + keys[0][1:]] + keys + [(max(total, keys[-1][0] + 0.01),) + keys[-1][1:]]
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


def draw_credit(img, text):
    """右下にクレジットを重ねる（CC BY の表示義務のため）"""
    from matplotlib import font_manager
    from PIL import ImageDraw, ImageFont

    path = font_manager.findfont(font_manager.FontProperties(family=info.plt.rcParams["font.family"]))
    font = ImageFont.truetype(path, 26)
    d = ImageDraw.Draw(img, "RGBA")
    w = d.textlength(text, font=font)
    d.rounded_rectangle((W - w - 44, H - 64, W - 16, H - 16), radius=10, fill=(10, 29, 51, 170))
    d.text((W - w - 30, H - 56), text, font=font, fill=(235, 240, 245, 255))


def main():
    dry = "--dry-run" in sys.argv or "--preview" in sys.argv
    mix, starts, durs, total = build_audio(dry)
    canvas, to_px = render_canvas()
    keys = camera_keys(starts, durs, total, to_px)
    print(f"total {total:.1f}s", ", ".join(f"{s:.1f}+{d:.1f}" for s, d in zip(starts, durs)), flush=True)

    if "--preview" in sys.argv:
        for i, (s, d) in enumerate(zip(starts, durs)):
            frame(canvas, *cam_at(s + d * 0.5, keys)).save(os.path.join(WORK_DIR, f"preview_{i + 1}.png"))
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
    credit = ("音声: HTS Voice Mei © 名古屋工業大学 (CC BY 3.0)"
              if os.environ.get("TTS_ENGINE", "chirp").lower() == "openjtalk" and not dry else "")
    for i in range(n):
        img = frame(canvas, *cam_at(i / FPS, keys))
        if credit and i / FPS > total - 4.5:
            draw_credit(img, credit)
        writer.send(np.asarray(img).tobytes())
        if i % 300 == 0:
            print(f"{i}/{n}", flush=True)
    writer.close()
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-i", silent]
    if not dry:
        cmd += ["-i", wav, "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100"]
    os.makedirs(OUT_DIR, exist_ok=True)
    name = time.strftime(f"{PREFIX}_%Y%m%d_%H%M") + ("_dryrun" if dry else "") + ".mp4"
    cmd += ["-c:v", "copy", "-shortest" if not dry else "-an", "-movflags", "+faststart",
            os.path.join(OUT_DIR, name)]
    subprocess.check_call(cmd)
    print("done:", cmd[-1])


if __name__ == "__main__":
    main()
