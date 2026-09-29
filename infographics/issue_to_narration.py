"""「🎬 図解動画を作る」Issue の本文から、動画フォルダ名と narration.txt を作る（video-make.yml から呼ぶ）。

使い方:
    ISSUE_BODY="..." python3 infographics/issue_to_narration.py   # 標準出力にフォルダ名を1行出す

ナレーション欄は 1行＝1場面。番号なしの行は上から順に番号を振り、「3: 本文」の形はその番号を使う。
「-」だけの行はその場面を無音にする（番号だけ進める）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDERS = ["hormuz-sts", "mongol-empire"]


def section(body, label):
    m = re.search(rf"^###\s*{re.escape(label)}\s*$\n(.*?)(?=^###\s|\Z)", body, re.M | re.S)
    text = m.group(1).strip() if m else ""
    return "" if text == "_No response_" else text


def main():
    body = os.environ.get("ISSUE_BODY", "").replace("\r\n", "\n")
    choice = section(body, "動画")
    folder = next((f for f in FOLDERS if choice.startswith(f)), None)
    if not folder:
        sys.exit(f"動画の選択が読み取れません: {choice!r}")
    lines, n = [], 0
    for raw in section(body, "ナレーション").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s*[:：]\s*(.*)$", line)
        if m:
            n, text = int(m.group(1)), m.group(2).strip()
        else:
            n, text = n + 1, line
        lines.append(f"{n}: {'' if text in ('-', 'ー', '－') else text}")
    if not any(re.match(r"^\d+: .+", x) for x in lines):
        sys.exit("ナレーションが空です")
    with open(os.path.join(HERE, folder, "narration.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    print(folder)


if __name__ == "__main__":
    main()
