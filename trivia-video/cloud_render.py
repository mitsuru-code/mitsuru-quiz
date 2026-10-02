# クラウド（GitHub Actions）用の書き出し入口
#   jobs/<doc_id>.json（ルーティンが置いた依頼）→ 画像を rclone で取得 → trivia_video.py で書き出し
#   → rclone で Googleドライブ「豆知識動画」へ保存、素材フォルダを「取り込み済み」へ → results/<key>.json
# 前提: rclone のリモート名は gdrive、環境変数 GOOGLE_TTS_API_KEY
import glob, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_job import build_script  # PC版と同じ原稿づくり

JOBS, RESULTS = os.path.join(HERE, "jobs"), os.path.join(HERE, "results")
WORK = os.path.join(HERE, "_work"); SOZAI = os.path.join(WORK, "sozai"); OUT = os.path.join(WORK, "out")
REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
for d in (RESULTS, SOZAI, OUT): os.makedirs(d, exist_ok=True)

def rclone(*args, check=False):
    return subprocess.run(["rclone", *args], capture_output=True, text=True, check=check)

def fetch_images(folder):
    """豆知識素材/<folder>（無ければ取り込み済み/<folder>）を取得し、画像の枚数を返す"""
    dst = os.path.join(SOZAI, folder)
    for src in (f"{REMOTE}:豆知識素材/{folder}", f"{REMOTE}:豆知識素材/取り込み済み/{folder}"):
        if rclone("copy", src, dst).returncode == 0 and os.path.isdir(dst) and os.listdir(dst): break
    return len([f for f in glob.glob(os.path.join(dst, "*")) if f.lower().endswith(IMG_EXT)])

def main():
    # まずGoogleドライブに接続できるか確かめ、だめなら理由を results に残して止める（ログが見られない環境のため）
    chk = rclone("lsd", f"{REMOTE}:", "--max-depth", "1")
    if chk.returncode != 0:
        open(os.path.join(RESULTS, "_rclone_error.txt"), "w", encoding="utf-8").write(
            time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + (chk.stderr or chk.stdout)[-1500:])
        print("rclone error"); return
    now = int(time.time() * 1000)
    for f in sorted(glob.glob(os.path.join(JOBS, "*.json"))):
        job = json.load(open(f, encoding="utf-8"))
        doc_id = os.path.splitext(os.path.basename(f))[0]
        key = f"{doc_id}_{job.get('requestedAt', 0)}"
        rp = os.path.join(RESULTS, key + ".json")
        if os.path.exists(rp) or job.get("status") != "verified": continue
        sc0 = job.get("script") or {}
        folder = sc0.get("imageFolder")
        need = len(sc0.get("imagePrompts") or [])
        have = fetch_images(folder) if folder else 0
        until = sc0.get("imageWaitUntil") or job.get("requestedAt", 0) + 2 * 3600 * 1000
        if need and have < need and now < until:
            print("wait images", doc_id, have, need); continue
        res = {"key": key, "status": "error", "file": None, "error": None}
        try:
            sc, name = build_script(job)
            sp = os.path.join(WORK, name + ".json")
            json.dump(sc, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
            out = os.path.join(OUT, name + ".mp4")
            env = {**os.environ, "TRIVIA_NO_DRIVE": "1", "TRIVIA_SOZAI_DIR": SOZAI, "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, os.path.join(HERE, "trivia_video.py"), sp, out], env=env,
                               capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("書き出し失敗: " + (r.stdout + r.stderr).strip()[-200:])
            for g in glob.glob(os.path.join(OUT, glob.escape(name) + "*")):
                rclone("copy", g, f"{REMOTE}:豆知識動画", check=True)
            if folder and have:
                rclone("moveto", f"{REMOTE}:豆知識素材/{folder}", f"{REMOTE}:豆知識素材/取り込み済み/{folder}")
            res.update(status="done", file=name + ".mp4")
        except Exception as e:
            res["error"] = str(e)[:200]
        res["finishedAt"] = int(time.time() * 1000)
        json.dump(res, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
        print(res["status"], doc_id, res.get("file") or res.get("error"))

if __name__ == "__main__":
    main()
