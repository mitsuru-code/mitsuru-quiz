"""
豆知識帳（時事モード）用のニュース見出し収集。GitHub Actions から1日3回実行される。

出力 mamechishiki/news.json を同フォルダに書き出し、変更があればワークフローがコミットする。
このJSONは claude.ai のクラウドルーティンが読み、選別して豆知識帳のデータベースへ入れる
（クラウド側はニュースサイトへ直接アクセスできないため、ここが取得役）。

取得だけを行い、センシティブ判定や要約はしない。
"""
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

FEEDS = [
    ("yahoo", "Yahoo!ニュース", "https://news.yahoo.co.jp/rss/topics/top-picks.xml"),
    ("jiji", "時事ドットコム", "https://www.jiji.com/rss/ranking.rdf"),
    ("nhk", "NHK", "https://www.nhk.or.jp/rss/news/cat0.xml"),
    ("itmedia", "ITmedia", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("nazology", "ナゾロジー", "https://nazology.kusuguru.co.jp/feed"),
]

PER_FEED = 12
DROP_PARAMS = {"source", "m", "utm_source", "utm_medium", "utm_campaign"}
OUT_PATH = Path(__file__).with_name("news.json")


def clean_link(link):
    p = urllib.parse.urlsplit(link)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k not in DROP_PARAMS]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


def fetch_feed(key, name, url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mamechishiki news collector)"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        print(f"[warn] {name}: {e}", file=sys.stderr)
        return []

    items = []
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue
        title = link = None
        for child in item:
            tag = child.tag.split("}")[-1]
            if tag == "title" and child.text:
                title = re.sub(r"\s+", " ", child.text).strip()
            elif tag == "link" and child.text:
                link = clean_link(child.text.strip())
        if title and link:
            doc_id = f"{key}-{hashlib.sha1(link.encode('utf-8')).hexdigest()[:16]}"
            items.append({"doc_id": doc_id, "title": title, "source": name, "link": link})
        if len(items) >= PER_FEED:
            break
    return items


def main():
    candidates, counts = [], {}
    for key, name, url in FEEDS:
        got = fetch_feed(key, name, url)
        counts[name] = len(got)
        candidates.extend(got)

    if not candidates:
        print("[error] 全媒体で0件だったため news.json は更新しない", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    data = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "now_ms": int(now.timestamp() * 1000),
        "counts": counts,
        "candidates": candidates,
    }
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(candidates)}件を {OUT_PATH.name} に書き出しました: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
