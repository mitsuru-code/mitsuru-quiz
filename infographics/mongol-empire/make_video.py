"""モンゴル帝国の図解をカメラワーク＋ナレーションで動画にするスクリプト。

使い方:
    pip install matplotlib numpy shapely pillow scipy imageio-ffmpeg
    export GOOGLE_TTS_API_KEY=...       # Google Cloud Text-to-Speech の API キー
    python3 make_video.py               # mongol_empire.mp4 を出力（1920x1080 / 30fps）
    python3 make_video.py --dry-run     # 音声なし。話す長さを文字数から推定してカメラだけ確認
    python3 make_video.py --preview     # 各場面の静止画だけ出力

ナレーションは Cloud TTS の Chirp 3: HD 音声（既定 ja-JP-Chirp3-HD-Aoede、TTS_VOICE で変更可）。
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
import urllib.request
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image

import make_infographic as info

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT = os.path.join(HERE, "mongol_empire.mp4")
W, H, FPS = 1920, 1080, 30
SCALE = 2  # 図解を2倍解像度で描き、拡大しても文字をくっきりさせる
SR = 24000
VOICE = os.environ.get("TTS_VOICE", "ja-JP-Chirp3-HD-Aoede")
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

# (読み上げ文, カメラの動き[(区間内の割合, 注目点, 横幅px@等倍)]) 注目点は ("map", lon, lat) か ("fig", x, y)
SCRIPT = [
    ("わずか七十年あまりで、ユーラシアの大半を支配した国があります。モンゴル帝国です。",
     [(0.0, ("fig", 0.5, 0.5), 2000), (1.0, ("fig", 0.5, 0.5), 1900)]),
    ("1206年、チンギス・カンが草原の部族をまとめて即位。騎馬軍団は、東の金、西のホラズムへと攻め込みます。",
     [(0.0, ("map", 102, 46), 800), (0.55, ("map", 105, 45), 950), (1.0, ("map", 86, 44), 1050)]),
    ("孫の代には、ヨーロッパの入り口ワールシュタット、そして中東のバグダードまで到達しました。",
     [(0.0, ("map", 42, 50), 1000), (0.5, ("map", 32, 50), 950), (1.0, ("map", 45, 36), 950)]),
    ("1279年、フビライが南宋を滅ぼし、領土は最大に。その広さは約二千四百万平方キロ。地球の陸地の、およそ六分の一です。",
     [(0.0, ("map", 115, 34), 1000), (0.45, ("map", 115, 34), 1000), (0.62, ("fig", 0.855, 0.93), 620),
      (1.0, ("fig", 0.855, 0.93), 600)]),
    ("しかし、拡大はここまで。エジプト、日本、ベトナムへの遠征は、相次いで失敗します。",
     [(0.0, ("map", 38, 33), 900), (0.45, ("map", 128, 30), 1000), (1.0, ("map", 115, 26), 1050)]),
    ("さらに後継者争いで、帝国は四つのウルスに分裂。",
     [(0.0, ("map", 78, 40), 1500), (1.0, ("map", 78, 40), 1400)]),
    ("疫病や天災、紙幣の乱発によるインフレが、追い打ちをかけます。",
     [(0.0, ("fig", 0.845, 0.62), 1000), (1.0, ("fig", 0.845, 0.52), 950)]),
    ("そして1368年、元は明に追われて北へ。巨大帝国は、わずか百六十年あまりで崩れていきました。",
     [(0.0, ("fig", 0.62, 0.16), 1500), (0.6, ("fig", 0.66, 0.16), 1300), (1.0, ("fig", 0.5, 0.5), 2000)]),
]
LEAD, GAP, TAIL = 0.6, 0.45, 1.6  # 冒頭・文間・末尾の間（秒）


# ---------------------------------------------------------------- 音声
def tts(text, dry=False):
    """Chirp 3: HD で1文を合成して float32 配列（SR Hz）を返す。dry=True なら長さだけ推定した無音"""
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
    clips = [tts(text, dry) for text, _ in SCRIPT]
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
    for (text, moves), s, d in zip(SCRIPT, starts, durs):
        span = d + GAP
        for frac, target, width in moves:
            cx, cy = to_px(target)
            keys.append((s - 0.35 + frac * span, cx, cy, width * SCALE))
    keys.sort()
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
            frame(canvas, *cam_at(s + d * 0.5, keys)).save(os.path.join(HERE, f"preview_{i}.png"))
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
    cmd += ["-c:v", "copy", "-shortest" if not dry else "-an", "-movflags", "+faststart",
            OUT if not dry else os.path.join(CACHE, "dry_run.mp4")]
    subprocess.check_call(cmd)
    print("done:", cmd[-1])


if __name__ == "__main__":
    main()
