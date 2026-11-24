"""Product watch list and 24-hour YouTube search cache."""
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from collectors import CollectionError, get_json

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "product_settings.json"
CACHE = ROOT / "review_cache.json"
DEFAULTS = {"products": [{"name": n, "keyword": n + " review"} for n in
    ("iPhone", "iPad", "MacBook", "Apple Watch", "Galaxy phone", "Galaxy Book", "Galaxy Watch")],
    "language": "ko", "days": 30, "videos": 20, "comments": 100, "analysis_limit": 10}


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return default


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", encoding="utf-8", delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        except Exception:
            handle.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def settings():
    value = read_json(SETTINGS, {})
    return {**deepcopy(DEFAULTS), **value}


def key_from_files():
    load_dotenv(ROOT / ".env", override=False)
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    path = ROOT / "2.env"
    if not key and path.is_file():
        key = path.read_text(encoding="utf-8-sig").strip()
        if ":" in key:
            label, value = key.split(":", 1)
            if label.strip().lower() in ("youtube_api_key", "youtube key"):
                key = value.strip()
        elif "=" in key:
            label, value = key.split("=", 1)
            if label.strip().lower() == "youtube_api_key": key = value.strip().strip('"\'')
    return key if "\n" not in key and "\r" not in key else ""


def load_api_keys():
    # Streamlit exports top-level string secrets as environment variables.
    key = key_from_files()
    if key:
        os.environ["YOUTUBE_API_KEY"] = key


def discover(key, product, language, now=None):
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    response = get_json("https://www.googleapis.com/youtube/v3/search", {"key":key, "part":"snippet", "type":"video", "q":product["keyword"], "order":"date", "relevanceLanguage":language, "publishedAfter":since, "maxResults":5})
    videos = []
    for item in response.get("items", []):
        snip = item.get("snippet", {})
        videos.append({"title":snip.get("title", ""), "channel":snip.get("channelTitle", ""),
                       "published":snip.get("publishedAt", ""), "thumbnail":snip.get("thumbnails", {}).get("medium", {}).get("url", ""),
                       "url":"https://www.youtube.com/watch?v=" + item["id"]["videoId"]})
    return {"checked_at":now.isoformat(), "videos":videos, "error":""}


def read_cache(now=None):
    now = now or datetime.now(timezone.utc)
    data = read_json(CACHE, {})
    valid = {}
    for name, entry in data.items():
        try:
            lifetime = timedelta(minutes=1) if entry.get("error") else timedelta(hours=24)
            if now - datetime.fromisoformat(entry["checked_at"]) < lifetime: valid[name] = entry
        except (ValueError, TypeError, KeyError): pass
    if len(valid) != len(data): write_json(CACHE, valid)
    return valid


def refresh_all(progress=lambda *args: None):
    config = settings()
    key = key_from_files()
    if not key: raise CollectionError("YouTube API 키가 없습니다. 2.env를 확인하세요.")
    cache = read_cache()
    for i, product in enumerate(config["products"]):
        try: cache[product["name"]] = discover(key, product, config["language"])
        except CollectionError as exc:
            cache[product["name"]] = {"checked_at":datetime.now(timezone.utc).isoformat(), "videos":[], "error":str(exc)}
        progress(i + 1, len(config["products"]))
    write_json(CACHE, cache)
    return cache


if __name__ == "__main__":
    try:
        result = refresh_all()
        print("Product checks:", len(result), "failed:", sum(bool(x["error"]) for x in result.values()))
    except (CollectionError, OSError):
        print("Daily check failed. Check API key, network and file permissions.")
        raise SystemExit(1)
