# クラウド版の「投稿し忘れ整理」（PC版 sweep_unposted.py と同じ規則を rclone で行う。削除はしない）
#   豆知識動画 直下に残った前日以前の動画 → 18:00枠は 期限切れ/、他は 未投稿ストック/ へ（投稿文・出典も一緒に）
import os, re, subprocess
from datetime import datetime, timedelta, timezone
REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive")
BASE = f"{REMOTE}:豆知識動画"

def main():
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    files = subprocess.run(["rclone", "lsf", BASE, "--files-only"], capture_output=True, text=True, check=True).stdout.splitlines()
    moved = 0
    for name in files:
        if not name.endswith(".mp4"): continue
        m = re.match(r"(\d{8})_(\d{4})?_?", name)
        if not m or m.group(1) >= today: continue
        dest = "期限切れ" if m.group(2) == "1800" else "未投稿ストック"
        stem = name[:-4]
        for f in [x for x in files if x.startswith(stem)]:
            subprocess.run(["rclone", "moveto", f"{BASE}/{f}", f"{BASE}/{dest}/{f}"], check=True)
        moved += 1
    print("moved", moved)

if __name__ == "__main__":
    main()
