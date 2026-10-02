# 豆知識帳の「動画にする」依頼（Artifact DB: videoJobs）をPCで処理する
#   python run_job.py         … jobs\videoJobs\*.json の未着手 verified（事実確認済み）を、裏の1プロセスで順番に書き出し開始し、状況をJSONで出力
#   python run_job.py worker  … （内部用）state\*.pending を投稿順に1本ずつ書き出して results\KEY.json に結果を書く
# DBの読み書きはClaude（ArtifactData）が行う。このスクリプトはローカルファイルだけを扱う
import glob, json, os, re, subprocess, sys, time, traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(HERE, "jobs", "videoJobs")
STATE = os.path.join(HERE, "jobs", "state")
RESULTS = os.path.join(HERE, "jobs", "results")
SCRIPTS = os.path.join(HERE, "scripts")
LOCK = os.path.join(STATE, "worker.pid")
OUTDIR = os.path.join(os.path.expanduser("~"), "Videos", "豆知識")
DEFAULTS = {"outro": "毎日ひとつ、話したくなる豆知識。フォローしてね。", "handle": "@apricotkinkuma"}
for d in (STATE, RESULTS, SCRIPTS, OUTDIR): os.makedirs(d, exist_ok=True)

def key_of(doc_id, job): return f"{doc_id}_{job.get('requestedAt', 0)}"

def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\s、。！？!?「」『』（）()…・]+', "", s)[:24] or "trivia"

def file_name(job, sc):
    # 投稿枠つき: 20260927_0700_題名 / 単発: 20260926_題名
    date = job.get("postDate") or datetime.fromtimestamp(job.get("requestedAt", time.time() * 1000) / 1000).strftime("%Y%m%d")
    return "_".join(x for x in (date, "時事" if job.get("news") else None, job.get("slot"), safe_name(sc["title"])) if x)

def archive_images(folder):
    """書き出しに使った素材フォルダを「豆知識素材\\取り込み済み」へ移す（削除はしない）。
    同じ日付のフォルダが残っていなければ、その日の「画像の指示文.txt」も一緒に移す"""
    import shutil
    root = next((f"{dl}:\\{m}" for dl in "GHIJKLMNOPQRSTUVWXYZDEF" for m in ("マイドライブ", "My Drive") if os.path.isdir(f"{dl}:\\{m}")), None)
    if not root or not folder or not re.fullmatch(r"[0-9A-Za-z_\-]{1,40}", folder): return
    base = os.path.join(root, "豆知識素材"); done = os.path.join(base, "取り込み済み")
    src = os.path.join(base, folder)
    if not os.path.isdir(src): return
    os.makedirs(done, exist_ok=True)
    dst = os.path.join(done, folder); k = 2
    while os.path.exists(dst): dst = os.path.join(done, f"{folder}_{k}"); k += 1
    shutil.move(src, dst)
    date = folder.split("_")[0]
    note = os.path.join(base, f"{date}_画像の指示文.txt")
    left = [d for d in os.listdir(base) if d.startswith(date + "_") and os.path.isdir(os.path.join(base, d))]
    if os.path.exists(note) and not left:
        shutil.move(note, os.path.join(done, os.path.basename(note)))

def build_script(job):
    """依頼（videoJobs の文書）から書き出し用の原稿を作る。PC版とクラウド版で共通"""
    sc = {**DEFAULTS, **job["script"]}
    sc.setdefault("title", job.get("title", ""))
    sc.setdefault("genre", job.get("genre", "豆知識"))
    if job.get("postDate"): sc.setdefault("postDate", job["postDate"])  # 背景テーマの日替わり用
    pts = sc.get("points") or []
    if len(pts) != 3 or not all(p.get("head") and p.get("text") for p in pts):
        raise ValueError("深掘りポイントが3つそろっていません")
    for k in ("hook", "intro", "question", "conclusion", "share"):
        if not str(sc.get(k, "")).strip(): raise ValueError(f"{k} が空です")
    v = job.get("verify") or {}
    if v.get("claims"):
        mark = {"confirmed": "○ 確認済み", "contradicted": "× 食い違い", "unverified": "△ 裏付けなし"}
        lines = [f"事実確認 {datetime.fromtimestamp(v.get('checkedAt', time.time() * 1000) / 1000):%Y-%m-%d %H:%M}"
                 + ("（人の判断で作成）" if v.get("override") else ""), ""]
        for c in v["claims"]:
            lines.append(f"{mark.get(c.get('verdict'), c.get('verdict'))}  {c.get('claim', '')}")
            if c.get("note"): lines.append(f"    {c['note']}")
            for s in c.get("sources") or []: lines.append(f"    - {s.get('title', '')} {s.get('url', '')}")
        sc["sources"] = "\n".join(lines)
    return sc, file_name(job, sc)

def render(key):
    res = {"key": key, "status": "error", "file": None, "error": None, "finishedAt": None}
    try:
        job = json.load(open(os.path.join(STATE, key + ".job.json"), encoding="utf-8"))
        sc, name = build_script(job)
        sp = os.path.join(SCRIPTS, name + ".json")
        json.dump(sc, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        out = os.path.join(OUTDIR, name + ".mp4")
        logp = os.path.join(STATE, key + ".log")
        with open(logp, "w", encoding="utf-8") as log:
            r = subprocess.run([sys.executable, os.path.join(HERE, "trivia_video.py"), sp, out], stdout=log, stderr=subprocess.STDOUT,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})  # ログの日本語ファイル名を化けさせない
        text = open(logp, encoding="utf-8", errors="replace").read()
        if r.returncode != 0 or not os.path.exists(out):
            last = text.strip().splitlines()[-1] if text.strip() else ""
            raise RuntimeError("書き出し失敗: " + last[-150:])
        drive = [l.split(" ", 1)[1].strip() for l in text.splitlines() if l.startswith("drive ") and l.strip().endswith(".mp4")]
        res.update(status="done", file=os.path.basename(drive[0]) if drive else os.path.basename(out))
        archive_images(sc.get("imageFolder"))
        if not drive: res["error"] = "Googleドライブ未接続のためPCの「ビデオ\\豆知識」にだけ保存"
    except Exception as e:
        res["error"] = str(e)[:200]
        open(os.path.join(STATE, key + ".err"), "w", encoding="utf-8").write(traceback.format_exc())
    res["finishedAt"] = int(time.time() * 1000)
    json.dump(res, open(os.path.join(RESULTS, key + ".json"), "w", encoding="utf-8"), ensure_ascii=False)

def _heartbeat():
    while True:
        try: open(LOCK, "w").write(str(os.getpid()))
        except OSError: pass
        time.sleep(15)

def worker():
    import threading
    threading.Thread(target=_heartbeat, daemon=True).start()  # 生存確認はファイルの更新時刻で行う（別環境からプロセス一覧が見えないため）
    time.sleep(0.5)
    try:
        while True:
            pend = sorted(glob.glob(os.path.join(STATE, "*.pending")),
                          key=lambda p: open(p, encoding="utf-8").read())  # 投稿日・枠の順
            if not pend: break
            key = os.path.splitext(os.path.basename(pend[0]))[0]
            os.replace(pend[0], os.path.join(STATE, key + ".started"))
            render(key)
    finally:
        try: os.remove(LOCK)
        except OSError: pass

IMAGE_WAIT_MS = 2 * 3600 * 1000
def waiting_images(job):
    """画像の指示文があるのに素材フォルダの枚数が足りない間は、最大2時間まで書き出しを待つ（過ぎたら絵文字で作る）"""
    sc = job.get("script") or {}
    need = len(sc.get("imagePrompts") or [])
    if not need or not sc.get("imageFolder"): return False
    until = sc.get("imageWaitUntil") or (job.get("requestedAt", 0) + IMAGE_WAIT_MS)
    if time.time() * 1000 > until: return False
    root = next((f"{dl}:\\{m}" for dl in "GHIJKLMNOPQRSTUVWXYZDEF" for m in ("マイドライブ", "My Drive") if os.path.isdir(f"{dl}:\\{m}")), None)
    if not root: return False
    d = os.path.join(root, "豆知識素材", sc["imageFolder"])
    have = len([f for f in glob.glob(os.path.join(d, "*")) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
    return have < need

def worker_alive():
    # 書き出し中の worker は15秒ごとに worker.pid を書き直す。90秒以上更新がなければ止まったとみなす
    try: return time.time() - os.path.getmtime(LOCK) < 90
    except OSError: return False

def main():
    started, running, finished = [], [], []
    for f in glob.glob(os.path.join(JOBS, "*.json")):
        doc_id = os.path.splitext(os.path.basename(f))[0]
        job = json.load(open(f, encoding="utf-8"))
        key = key_of(doc_id, job)
        folder = (job.get("script") or {}).get("imageFolder")
        if folder and job.get("status") in ("queued", "verified") and not os.path.exists(os.path.join(RESULTS, key + ".json")):  # 画像の置き場所を先に作っておく（書き出し済みの依頼では作らない）
            root = next((f"{dl}:\\{m}" for dl in "GHIJKLMNOPQRSTUVWXYZDEF" for m in ("マイドライブ", "My Drive") if os.path.isdir(f"{dl}:\\{m}")), None)
            if root and re.fullmatch(r"[0-9A-Za-z_\-]{1,40}", folder):
                if not os.path.isdir(os.path.join(root, "豆知識素材", "取り込み済み", folder)):
                    os.makedirs(os.path.join(root, "豆知識素材", folder), exist_ok=True)
        if os.path.exists(os.path.join(RESULTS, key + ".json")):
            finished.append({"doc_id": doc_id, **json.load(open(os.path.join(RESULTS, key + ".json"), encoding="utf-8"))}); continue
        if any(os.path.exists(os.path.join(STATE, key + ext)) for ext in (".started", ".pending")):
            running.append(doc_id); continue
        if job.get("status") != "verified": continue  # 事実確認を通ったものだけ書き出す
        if waiting_images(job):
            running.append(doc_id); continue
        json.dump(job, open(os.path.join(STATE, key + ".job.json"), "w", encoding="utf-8"), ensure_ascii=False)
        order = f"{job.get('postDate') or ''}_{job.get('slot') or '9999'}_{job.get('requestedAt', 0)}"
        open(os.path.join(STATE, key + ".pending"), "w", encoding="utf-8").write(order)
        started.append(doc_id)
    alive = worker_alive()
    if not alive:  # PCの電源断などで途中終了した分はやり直す
        for s in glob.glob(os.path.join(STATE, "*.started")):
            key = os.path.splitext(os.path.basename(s))[0]
            if not os.path.exists(os.path.join(RESULTS, key + ".json")):
                job = json.load(open(os.path.join(STATE, key + ".job.json"), encoding="utf-8"))
                open(os.path.join(STATE, key + ".pending"), "w", encoding="utf-8").write(
                    f"{job.get('postDate') or ''}_{job.get('slot') or '9999'}_{job.get('requestedAt', 0)}")
                os.remove(s)
    if (started or running) and not alive:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker"], creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=HERE)
    print(json.dumps({"started": started, "running": running, "finished": finished}))  # ASCIIで出す（実行環境の文字コードに左右されない）

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker": worker()
    else: main()
