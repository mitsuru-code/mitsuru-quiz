"""図解動画スクリプト（*/make_video.py）の共通部品：APIキー不要の読み上げと、焼き込み字幕。

- openjtalk_tts: Open JTalk（pyopenjtalk）でオフライン合成。Cloud TTS より機械的な声だが無料・キー不要
- Subtitler: 画面下に字幕帯を描く（Xは無音で自動再生されるので、声が無くても内容が伝わるように）
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",  # Linux（fonts-ipafont-gothic）
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    r"C:\Windows\Fonts\BIZ-UDGothicR.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
]


def openjtalk_tts(text, sr, speed=None):
    """Open JTalk で1文を合成して float32 配列（sr Hz）を返す"""
    try:
        import pyopenjtalk
    except ImportError:
        sys.exit("pyopenjtalk が入っていません: pip install pyopenjtalk")
    from scipy.signal import resample_poly

    speed = speed or float(os.environ.get("OPENJTALK_SPEED", "1.1"))
    x, src_sr = pyopenjtalk.tts(text, speed=speed)
    x = resample_poly(x.astype(np.float64), sr, int(src_sr)).astype(np.float32)
    return x / max(np.abs(x).max(), 1.0) * 0.9


def _wrap(draw, text, font, max_w):
    """日本語は単語の区切りが無いので1文字ずつ詰める。はみ出す時は、行の後半にある句読点の直後で折り返す"""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur and ch not in "、。」）！？":
            cut = max(cur.rfind(p) for p in "、。」")
            if cut >= len(cur) * 0.5:
                lines.append(cur[:cut + 1])
                cur = cur[cut + 1:] + ch
            else:
                lines.append(cur)
                cur = ch
        else:
            cur += ch
    return lines + [cur] if cur else lines


class Subtitler:
    def __init__(self, w, h):
        path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
        if not path:
            sys.exit("字幕用の日本語フォントが見つかりません（SUBTITLES=0 で字幕なし）")
        self.w, self.h = w, h
        self.font = ImageFont.truetype(path, int(h * 0.046))
        self.cache = {}

    def _overlay(self, text):
        """字幕帯（RGBA）と貼り付け位置。同じ文は使い回す"""
        if text not in self.cache:
            probe = ImageDraw.Draw(Image.new("L", (1, 1)))
            lines = _wrap(probe, text, self.font, self.w * 0.84)
            size = self.font.size
            pad, gap = int(size * 0.55), int(size * 0.35)
            bw = int(max(probe.textlength(s, font=self.font) for s in lines)) + pad * 2
            bh = len(lines) * size + (len(lines) - 1) * gap + pad * 2
            band = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            d = ImageDraw.Draw(band)
            d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=int(size * 0.4), fill=(12, 14, 18, 215))
            for i, s in enumerate(lines):
                x = (bw - d.textlength(s, font=self.font)) / 2
                d.text((x, pad + i * (size + gap) - int(size * 0.08)), s, font=self.font, fill=(255, 255, 255, 255))
            self.cache[text] = (band, ((self.w - bw) // 2, int(self.h * 0.95) - bh))
        return self.cache[text]

    def draw(self, img, text, alpha=1.0):
        """img（RGB, W×H）に字幕を重ねて返す。alpha で出入りをフェード"""
        if not text or alpha <= 0:
            return img
        band, pos = self._overlay(text)
        if alpha < 1:
            band = band.copy()
            band.putalpha(band.getchannel("A").point(lambda v: int(v * alpha)))
        img = img.copy()
        img.paste(band, pos, band)
        return img
