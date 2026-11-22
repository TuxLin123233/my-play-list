#!/usr/bin/env python3
"""Build js/data.js for the playlist site.

Merges:
  - the original CSV (authoritative titles/artists/albums)
  - data/songs_raw.json (QQ Music genre / language / ids, from fetch_metadata.py)
  - data/kuwo_songs.json (Kuwo cover art + durations)

Run:
    python3 tools/build_site_data.py --download-covers
"""
import argparse
import csv
import io
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "playlist.csv"
if not CSV_PATH.exists():
    CSV_PATH = Path("/home/tux/Downloads/lx_list_小林要自律喜欢的音乐.csv")
RAW_PATH = ROOT / "data" / "songs_raw.json"
KUWO_PATH = ROOT / "data" / "kuwo_songs.json"
OUT_JSON = ROOT / "data" / "songs.json"
OUT_JS = ROOT / "js" / "data.js"
COVER_DIR = ROOT / "covers"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)

GENRE_ORDER = [
    "流行",
    "电子 / 舞曲",
    "摇滚 / 另类",
    "嘻哈 / R&B",
    "原声 / ACG",
    "民谣 / 唱作",
    "纯音乐",
    "爵士 / 蓝调",
    "其他",
]

GENRE_RULES = [
    (r"rap|hip.?hop|嘻哈|说唱", "嘻哈 / R&B"),
    (r"r&b|rhythm|soul|节奏布鲁斯|灵魂", "嘻哈 / R&B"),
    (r"electronic|electronica|edm|house|techno|trance|dubstep|drum|bass|synth|电子", "电子 / 舞曲"),
    (r"dance|舞曲|club", "电子 / 舞曲"),
    (r"rock|metal|punk|grunge|摇滚|金属|朋克", "摇滚 / 另类"),
    (r"alternative|另类|shoegaze", "摇滚 / 另类"),
    (r"folk|民谣|singer|songwriter|唱作|acoustic|country|乡村", "民谣 / 唱作"),
    (r"classical|古典|instrumental|器乐|new age|新世纪|easy listening|轻音乐|piano|纯音乐", "纯音乐"),
    (r"soundtrack|原声|anime|动漫|game|游戏|score", "原声 / ACG"),
    (r"jazz|爵士|blues|蓝调", "爵士 / 蓝调"),
    (r"pop|流行|mandopop|cantopop", "流行"),
]

MANUAL_GENRE = {
    ("kiss me more", "doja cat、sza"): "嘻哈 / R&B",
    ("reality", "lost frequencies、janieck"): "电子 / 舞曲",
    ("唯一 (live)", "g.e.m.邓紫棋"): "流行",
    ("sold out", "hawk nelson、jonathan steingard"): "摇滚 / 另类",
    ("green to blue", "aurenth"): "纯音乐",
    ("fractures", "illenium、neuve"): "电子 / 舞曲",
    ("fractures", "illenium、neve"): "电子 / 舞曲",
    ("wake (studio)", "hillsong young & free"): "流行",
    ("take me hand", "daishi dance、cécile corbel"): "电子 / 舞曲",
    ("rain", "the one outs、chromatics、metrik、feint"): "电子 / 舞曲",
    ("catch my breath (0.8x)", "snc"): "流行",
}

MANUAL_LANGUAGE = {
    ("kiss me more", "doja cat、sza"): "英语",
    ("reality", "lost frequencies、janieck"): "英语",
    ("唯一 (live)", "g.e.m.邓紫棋"): "国语",
    ("sold out", "hawk nelson、jonathan steingard"): "英语",
    ("green to blue", "aurenth"): "纯音乐",
    ("fractures", "illenium、neuve"): "英语",
    ("wake (studio)", "hillsong young & free"): "英语",
    ("take me hand", "daishi dance、cécile corbel"): "英语",
    ("rain", "the one outs、chromatics、metrik、feint"): "英语",
    ("catch my breath (0.8x)", "snc"): "英语",
}

ELECTRONIC_HINTS = (
    "dj", "remix", "nightcore", "illenium", "vicetone", "lost frequencies",
    "daishi dance", "feint", "metrik", "martin garrix", "chainsmokers",
    "alan walker", "marshmello", "zedd", "avicii", "kygo", "tobu",
    "elektronomia", "janji", "drum", "bass", "synth", "flume", "odesza",
)
ROCK_HINTS = (
    "linkin park", "beyond", "one ok rock", "green day", "my chemical romance",
    "paramore", "evanescence", "sum 41", "blink-182", "metallica", "hawk nelson",
    "athletics", "she her her hers", "the one outs",
)
HIPHOP_HINTS = (
    "doja cat", "sza", "the weeknd", "travis scott", "kanye", "drake",
    "lil nas", "lil ", "xxxtentacion", "post malone", "eminem", "jay-z",
    "kendrick", "j. cole", "cardi b", "nicki", "playboi carti", "don toliver",
)
PURE_HINTS = (
    "lakey inspired", "dj okawari", "hshkgn", "youzee", "aurenth",
    "piano", "instrumental", "orchestra",
)


def norm_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u00a0", " ").replace("\t", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def display(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u00a0", " ").replace("\t", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def classify_genre(raw_genre: str, language: str, title: str, artist: str, key) -> str:
    if key in MANUAL_GENRE:
        return MANUAL_GENRE[key]

    raw = (raw_genre or "").lower()
    for pattern, label in GENRE_RULES:
        if re.search(pattern, raw):
            return label

    # Unknown / missing genre: fall back to artist and language heuristics.
    haystack = f"{title} {artist}".lower()
    if language == "纯音乐":
        return "纯音乐"
    if any(h in haystack for h in ELECTRONIC_HINTS):
        return "电子 / 舞曲"
    if any(h in haystack for h in ROCK_HINTS):
        return "摇滚 / 另类"
    if any(h in haystack for h in HIPHOP_HINTS):
        return "嘻哈 / R&B"
    if any(h in haystack for h in PURE_HINTS):
        return "纯音乐"
    if language in ("国语", "粤语", "英语", "日语", "韩语", "俄语", "德语", "西班牙语", "印尼语"):
        return "流行"
    return "其他"


def language_for(raw_language: str, key) -> str:
    if key in MANUAL_LANGUAGE:
        return MANUAL_LANGUAGE[key]
    return raw_language or ""


def qq_urls(title: str, artist: str, meta: dict):
    query = f"{title} {artist}"
    search = "https://y.qq.com/n/ryqq/search?w=" + urllib.parse.quote(query)
    netease = (
        "https://music.163.com/#/search/m/?s="
        + urllib.parse.quote(query)
        + "&type=1"
    )
    score = meta.get("score", 0) or 0
    songmid = meta.get("songmid") or ""
    if songmid and score >= 0.9:
        return f"https://y.qq.com/n/ryqq/songDetail/{songmid}", netease
    return search, netease


def load_kuwo():
    data = json.loads(KUWO_PATH.read_text(encoding="utf-8"))
    out = {}
    for song in data.get("songs", []):
        key = (norm_key(song.get("title")), norm_key(song.get("artist")))
        out.setdefault(key, song)
    return out


def load_raw():
    data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    out = {}
    for row in data:
        key = (norm_key(row.get("title")), norm_key(row.get("artist")))
        out.setdefault(key, row.get("meta") or {})
    return out


def build_songs():
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    raw = load_raw()
    kuwo = load_kuwo()

    songs = []
    seen = set()
    for row in rows:
        title = display(row.get("歌曲名", ""))
        artist = display(row.get("艺术家", ""))
        album = display(row.get("专辑名", ""))
        key = (norm_key(title), norm_key(artist))
        if not title or key in seen:
            continue
        seen.add(key)

        meta = raw.get(key, {})
        k = kuwo.get(key, {})
        genre = classify_genre(meta.get("genre", ""), language_for(meta.get("language", ""), key), title, artist, key)
        language = language_for(meta.get("language", ""), key)
        qq_url, netease_url = qq_urls(title, artist, meta)

        cover_remote = k.get("cover") or meta.get("cover") or ""
        cover = cover_remote
        songs.append(
            {
                "id": f"{len(songs) + 1:03d}",
                "title": title,
                "artist": artist,
                "album": album or display(meta.get("album", "")),
                "genre": genre,
                "language": language,
                "duration": k.get("duration", ""),
                "cover": cover,
                "coverRemote": cover_remote,
                "qqUrl": qq_url,
                "neteaseUrl": netease_url,
            }
        )

    genres = []
    counts = {}
    for song in songs:
        counts[song["genre"]] = counts.get(song["genre"], 0) + 1
    for genre in GENRE_ORDER:
        if counts.get(genre):
            genres.append({"name": genre, "count": counts[genre]})

    artists = {song["artist"] for song in songs if song["artist"]}
    albums = {song["album"] for song in songs if song["album"]}
    data = {
        "title": "小林要自律喜欢的音乐",
        "owner": "TuxLin123233",
        "updated": "2026-11-22",
        "songs": songs,
        "genres": genres,
        "stats": {
            "songs": len(songs),
            "artists": len(artists),
            "albums": len(albums),
            "genres": len(genres),
        },
    }
    return data


def download_one(song: dict):
    cover_dir = COVER_DIR
    ext = ".webp"
    dest = cover_dir / f'{song["id"]}{ext}'
    if dest.exists() and dest.stat().st_size > 1000:
        return song["id"], f"covers/{dest.name}"

    url = song.get("coverRemote") or ""
    if not url:
        return song["id"], None
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://y.qq.com/"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read()
    if Image is None:
        return song["id"], None
    img = Image.open(io.BytesIO(payload)).convert("RGB")
    img = ImageOps.fit(img, (320, 320), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "WEBP", quality=82, method=6)
    return song["id"], f"covers/{dest.name}"


def download_covers(data: dict):
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    songs = data["songs"]
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(download_one, song): song for song in songs}
        for fut in as_completed(futures):
            song = futures[fut]
            try:
                song_id, path = fut.result()
                if path:
                    song["cover"] = path
            except Exception as exc:  # noqa: BLE001
                print("cover ERR", song["id"], song["title"], repr(exc)[:120])
            done += 1
            if done % 25 == 0 or done == len(songs):
                print(f"  covers {done}/{len(songs)}")
    return data


def write_outputs(data: dict):
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_JS.write_text(
        "window.PLAYLIST_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size / 1024:.0f} KB)")
    print(f"wrote {OUT_JS} ({OUT_JS.stat().st_size / 1024:.0f} KB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-covers", action="store_true")
    args = parser.parse_args()

    data = build_songs()
    print(f'songs={data["stats"]["songs"]} artists={data["stats"]["artists"]} albums={data["stats"]["albums"]}')
    print("genres:", ", ".join(f'{g["name"]} {g["count"]}' for g in data["genres"]))
    if args.download_covers:
        data = download_covers(data)
    write_outputs(data)


if __name__ == "__main__":
    main()
