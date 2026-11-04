#!/usr/bin/env python3
"""quiz-maker の出力形式チェック。使い方: python3 check_quiz.py quiz.md"""
import re
import sys

LABELS = ["問題", "選択肢", "ヒント", "解説"]


def field(block, name):
    m = re.search(rf"\*\*{name}\*\*[：:]\s*(.+?)(?=\n\*\*|\Z)", block, re.S)
    return m.group(1).strip() if m else None


def check(block):
    errs = []
    vals = {k: field(block, k) for k in LABELS}
    for k, v in vals.items():
        if not v:
            errs.append(f"{k}がない")
    if errs:
        return errs
    pos = [block.index(f"**{k}**") for k in LABELS]
    if pos != sorted(pos):
        errs.append("順番が 問題→選択肢→ヒント→解説 になっていない")
    if len(vals["問題"]) > 80:
        errs.append(f"問題が{len(vals['問題'])}字（80字以内）")
    choices = re.findall(r"[A-D]\)", vals["選択肢"])
    if choices != ["A)", "B)", "C)", "D)"]:
        errs.append(f"選択肢がA〜Dの4つになっていない: {choices}")
    if len(vals["ヒント"]) > 40:
        errs.append(f"ヒントが{len(vals['ヒント'])}字（40字以内）")
    n = len(re.sub(r"\s", "", vals["解説"]))
    if not 270 <= n <= 330:
        errs.append(f"解説が{n}字（270〜330字）")
    if not re.match(r"正解は[A-D]", vals["解説"]):
        errs.append("解説が「正解は〇」で始まっていない")
    return errs


def main():
    text = open(sys.argv[1], encoding="utf-8").read()
    blocks = re.split(r"(?=\*\*Q\d+\*\*)", text)
    blocks = [b for b in blocks if re.match(r"\*\*Q\d+\*\*", b)]
    if not blocks:
        print("NG: **Q1** 形式の問題が見つからない")
        sys.exit(1)
    ng = 0
    for b in blocks:
        q = re.match(r"\*\*(Q\d+)\*\*", b).group(1)
        errs = check(b)
        print(f"{q}: " + ("OK" if not errs else "NG - " + " / ".join(errs)))
        ng += bool(errs)
    print(f"{len(blocks)}問中 OK {len(blocks) - ng} / NG {ng}")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
