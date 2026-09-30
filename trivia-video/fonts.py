# フォントの場所を解決する（Windowsは従来のフォント、Linux/クラウドは Noto で代用）
import os
from functools import lru_cache
from PIL import ImageFont

WIN = "C:/Windows/Fonts/"
_NOTO = "/usr/share/fonts/opentype/noto/"
FALLBACK = {
    "YuGothB.ttc": (_NOTO + "NotoSansCJK-Bold.ttc", 0),      # index 0 = Noto Sans CJK JP
    "YuGothM.ttc": (_NOTO + "NotoSansCJK-Regular.ttc", 0),
    "segoeuib.ttf": (_NOTO + "NotoSansCJK-Bold.ttc", 0),
    "segoeuil.ttf": (_NOTO + "NotoSansCJK-Regular.ttc", 0),
    "consola.ttf": ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
}

@lru_cache(None)
def font(name, size):
    if os.path.exists(WIN + name):
        return ImageFont.truetype(WIN + name, size)
    path, idx = FALLBACK[name]
    return ImageFont.truetype(path, size, index=idx)
