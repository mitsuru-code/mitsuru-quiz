"""教材動画のプロジェクトフォルダを組み立て、PC に渡す ZIP を作る。

使い方:
    python build_project.py <プロジェクトフォルダ> [--preview] [--zip-dir <ZIPの出力先>]

プロジェクトフォルダには script.json（必須）と、あれば scenes/NN.png・scroll 画像を置いておく。
このスクリプトは次を行う（script.json・scenes・.env は上書きしない）:
    1. make_video.py と PC 用の付属ファイル（run.bat / check.bat / requirements.txt /
       .env.example / .gitignore / PC手順.md）をコピー
    2. script.json の image_prompt から 素材プロンプト.md を生成
    3. --preview 指定時は全場面の静止画を作り、1枚の一覧画像 preview_sheet.png にまとめる
    4. <slug>.zip を作る（.env・.cache・out・preview は含めない）
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL, "assets")
COPY = {  # アセット名 → プロジェクト内の名前
    "run.bat": "run.bat", "check.bat": "check.bat", "requirements.txt": "requirements.txt",
    "env.example": ".env.example", "gitignore": ".gitignore", "PC手順.md": "PC手順.md",
}
SKIP_DIRS = {".cache", "out", "__pycache__"}


def validate(script):
    errs = []
    for k in ("title", "slug", "scenes"):
        if not script.get(k):
            errs.append(f"script.json に {k} がありません")
    if script.get("slug") and not all(c.isalnum() or c in "_-" for c in script["slug"]):
        errs.append("slug は半角英数字と _ - だけにしてください（出力ファイル名に使います）")
    for i, sc in enumerate(script.get("scenes", [])):
        if not (sc.get("read") or sc.get("sub")):
            errs.append(f"場面 {i:02d}: read（読み上げ文）も sub（字幕）も空です")
    if errs:
        sys.exit("\n".join(errs))


def write_prompts(proj, script):
    style = script.get("image_style", "")
    rows = []
    for i, sc in enumerate(script["scenes"]):
        if sc.get("image_prompt"):
            have = any(os.path.exists(os.path.join(proj, "scenes", f"{i:02d}.{e}")) for e in ("png", "jpg", "jpeg", "webp"))
            rows.append(f"| `scenes/{i:02d}.png` | {sc.get('head') or sc.get('sub', '')[:20]} | {'済' if have else '未'} "
                        f"| `{sc['image_prompt']}` |")
    lines = [f"# {script['title']} 素材プロンプト", "",
             "生成した画像を `scenes\\NN.png`（16:9、1920x1080 以上推奨）として置き、`run.bat` を再実行すると、その場面に反映される。",
             "画像が無い場面は、scroll（1枚絵）があればその切り出し、無ければ見出しを大きく出した仮画面になる。", ""]
    if style:
        lines += ["## 共通（全プロンプトの末尾に付ける）", "", "```", style, "```", "",
                  "※「no text」は必須（字幕と二重になり、崩れた文字も出やすいため）。", ""]
    lines += ["## 場面ごとのプロンプト", "", "| ファイル | 場面 | 状態 | プロンプト |", "|---|---|---|---|"] + rows
    if script.get("bgm_prompt"):
        lines += ["", "## BGM を差し替える場合（任意）", "", "```", script["bgm_prompt"], "```"]
    with open(os.path.join(proj, "素材プロンプト.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


def preview(proj, n):
    subprocess.check_call([sys.executable, "make_video.py", "--preview"], cwd=proj)
    from PIL import Image

    cols = 4
    tw, th = 480, 270
    sheet = Image.new("RGB", (tw * cols, th * ((n + cols - 1) // cols)), "white")
    for i in range(n):
        p = os.path.join(proj, f"preview_{i:02d}.png")
        sheet.paste(Image.open(p).resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    out = os.path.join(proj, "preview_sheet.png")
    sheet.save(out)
    print("preview:", out)


def make_zip(proj, slug, zip_dir):
    os.makedirs(zip_dir, exist_ok=True)
    path = os.path.join(zip_dir, f"{slug}.zip")
    base = os.path.dirname(os.path.abspath(proj))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(proj):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(".mp4") or f.startswith("preview_") or f in (".env", "エラーログ.txt"):
                    continue
                full = os.path.join(root, f)
                z.write(full, os.path.join(slug, os.path.relpath(full, proj)))
    print("zip:", path, f"({os.path.getsize(path) / 1e6:.1f} MB)")
    return path


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    proj = os.path.abspath(sys.argv[1])
    with open(os.path.join(proj, "script.json"), encoding="utf-8-sig") as fp:
        script = json.load(fp)
    validate(script)
    shutil.copy(os.path.join(SKILL, "scripts", "make_video.py"), os.path.join(proj, "make_video.py"))
    for src, dst in COPY.items():
        shutil.copy(os.path.join(ASSETS, src), os.path.join(proj, dst))
    os.makedirs(os.path.join(proj, "scenes"), exist_ok=True)
    write_prompts(proj, script)
    if "--preview" in sys.argv:
        preview(proj, len(script["scenes"]))
    zip_dir = sys.argv[sys.argv.index("--zip-dir") + 1] if "--zip-dir" in sys.argv else os.path.dirname(proj)
    make_zip(proj, script["slug"], zip_dir)


if __name__ == "__main__":
    main()
