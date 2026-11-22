#!/usr/bin/env python3
"""Fetch cover art and genre metadata from QQ Music for the playlist CSV.

Usage:
    python3 fetch_metadata.py

Reads  data/playlist.csv
Writes data/metadata_cache.json and data/songs_raw.json
"""
import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "playlist.csv"
if not CSV_PATH.exists():
    CSV_PATH = Path("/home/tux/Downloads/lx_list_小林要自律喜欢的音乐.csv")
CACHE_PATH = ROOT / "data" / "metadata_cache.json"
OUT_PATH = ROOT / "data" / "songs_raw.json"
WORKERS = 6

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://y.qq.com/"}

NOISE_RE = re.compile(
    r"(feat\.?|ft\.?|featuring|explicit|remaster(ed)?|live|acoustic|"
    r"instrumental|remix|edit|version|demo|cover|翻唱|伴奏|现场|纯音乐)",
    re.I,
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.replace("&", "and")
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）|【[^】]*】", " ", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(s: str) -> str:
    s = norm(s)
    s = NOISE_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        ratio = max(ratio, 0.86)
    return ratio


def http_json(url: str, tries: int = 4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                if raw.startswith("callback("):
                    raw = raw[len("callback("):-1]
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise last  # type: ignore[misc]


def search_qq(title: str, artist: str):
    queries = [f"{title} {artist}", title]
    seen = set()
    for q in queries:
        url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp?" + urllib.parse.urlencode(
            {"p": 1, "n": 8, "w": q, "format": "json"}
        )
        try:
            data = http_json(url)
        except Exception:
            continue
        songs = ((data.get("data") or {}).get("song") or {}).get("list") or []
        for song in songs:
            mid = song.get("songmid")
            if mid and mid not in seen:
                seen.add(mid)
                yield song


def score_song(row, song) -> float:
    t = clean_title(row["歌曲名"])
    ct = clean_title(song.get("songname", ""))
    a = norm(row["艺术家"])
    singers = [norm(s.get("name", "")) for s in song.get("singer") or []]
    al = norm(row.get("专辑名", ""))
    cal = norm(song.get("albumname", ""))

    title_score = sim(t, ct)
    artist_score = max([sim(a, s) for s in singers] + [0.0])
    album_score = sim(al, cal) if al else 0.0

    score = 0.62 * title_score + 0.28 * artist_score + 0.10 * album_score

    # Prefer exact-ish matches.
    if t and ct and t == ct:
        score += 0.08
    if a and any(a == s for s in singers):
        score += 0.06
    if al and cal and al == cal:
        score += 0.04

    # Penalise versions that the source title did not ask for.
    raw_title = unicodedata.normalize("NFKC", row["歌曲名"]).lower()
    cand_title = unicodedata.normalize("NFKC", song.get("songname", "")).lower()
    for word in ("live", "remix", "acoustic", "instrumental", "伴奏", "翻唱", "现场", "demo", "cover"):
        if word in cand_title and word not in raw_title:
            score -= 0.12
    return score


def match(row):
    best = None
    best_score = 0.0
    for song in search_qq(row["歌曲名"], row["艺术家"]):
        s = score_song(row, song)
        if s > best_score:
            best, best_score = song, s
    if best and best_score >= 0.58:
        return best, best_score
    return None, best_score


def album_info(albummid: str):
    if not albummid:
        return {}
    url = (
        "https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_info_cp.fcg?"
        + urllib.parse.urlencode({"albummid": albummid, "format": "json"})
    )
    try:
        data = http_json(url)
        return data.get("data") or {}
    except Exception:
        return {}


def process(row):
    key = f'{row["歌曲名"]}\u0001{row["艺术家"]}'
    song, score = match(row)
    if not song:
        return key, {"matched": False, "score": round(score, 3)}
    info = album_info(song.get("albummid", ""))
    albummid = song.get("albummid", "")
    return key, {
        "matched": True,
        "score": round(score, 3),
        "title": song.get("songname", ""),
        "artists": [s.get("name", "") for s in song.get("singer") or []],
        "album": song.get("albumname", ""),
        "albummid": albummid,
        "songmid": song.get("songmid", ""),
        "cover": f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{albummid}.jpg" if albummid else "",
        "genre": info.get("genre", ""),
        "language": info.get("lan", ""),
        "genre_id": info.get("genre_id"),
        "album_date": info.get("aDate", ""),
        "company": (info.get("company_new") or {}).get("name", ""),
    }


def main():
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)

    pending = []
    seen = set()
    for row in rows:
        key = f'{row["歌曲名"]}\u0001{row["艺术家"]}'
        if key in seen:
            continue
        seen.add(key)
        if key not in cache:
            pending.append(row)

    print(f"rows={len(rows)} unique={len(seen)} cached={len(cache)} pending={len(pending)}", flush=True)

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process, row): row for row in pending}
        for fut in as_completed(futures):
            row = futures[fut]
            key = f'{row["歌曲名"]}\u0001{row["艺术家"]}'
            try:
                k, result = fut.result()
                cache[k] = result
            except Exception as exc:  # noqa: BLE001
                print("ERR", row["歌曲名"], repr(exc)[:120], flush=True)
                cache[key] = {"matched": False, "error": repr(exc)[:200]}
            done += 1
            if done % 10 == 0 or done == len(pending):
                print(f"  {done}/{len(pending)}", flush=True)
                with open(CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False, indent=1)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)

    out = []
    for row in rows:
        key = f'{row["歌曲名"]}\u0001{row["艺术家"]}'
        meta = cache.get(key) or {}
        out.append(
            {
                "title": row["歌曲名"].strip(),
                "artist": row["艺术家"].strip(),
                "album": row["专辑名"].strip(),
                "meta": meta,
            }
        )
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    matched = sum(1 for v in cache.values() if v.get("matched"))
    print(f"matched {matched}/{len(cache)} -> {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
