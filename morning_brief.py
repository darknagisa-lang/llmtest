"""Search across devices, then organize the returned review candidates."""
import re
from datetime import datetime, time, timedelta, timezone
from html import unescape

from collectors import CollectionError, get_json
from discovery import ROOT, key_from_files, read_json, write_json

KST = timezone(timedelta(hours=9), "KST")
CACHE = ROOT / "morning_brief.json"
SPECS = ROOT / "product_specs.json"
QUERIES = {
    "ko": ("픽셀 리뷰|갤럭시 리뷰|아이폰 리뷰|아이패드 리뷰|맥북 리뷰|애플워치 리뷰",
           "화웨이 리뷰|오포 리뷰|비보 리뷰|샤오미 리뷰|레드미 리뷰",
           "AI 글라스 리뷰|스마트 안경 리뷰|AI 기기 리뷰|AI 녹음기 리뷰"),
    "en": ("Google Pixel review|Samsung Galaxy review|Apple iPhone review|Apple iPad review|MacBook first look|Apple Watch review",
           "Huawei device review|OPPO Find review|vivo device review|Xiaomi device review|Redmi review",
           "AI glasses review|smart glasses hands on|AI device review|AI recorder review"),
}
ALIASES = {"갤럭시": "Galaxy", "폴드": "Fold", "플립": "Flip", "픽셀": "Pixel", "아이폰": "iPhone",
           "아이패드": "iPad", "맥북": "MacBook", "애플워치": "Apple Watch", "애플 워치": "Apple Watch",
           "화웨이": "Huawei", "오포": "OPPO", "비보": "vivo", "샤오미": "Xiaomi", "레드미": "Redmi",
           "울트라": " Ultra ", "프로 맥스": " Pro Max ", "프로": " Pro ", "플러스": " Plus ",
           "워치": " Watch ", "탭": " Tab ", "시리즈": " Series "}
PATTERNS = [
    ("AI 글라스", r"(?:Ray-Ban Meta(?:\s+(?:Gen\s*\d|Display))?|Meta Ray-Ban Display|Xiaomi AI Glasses|Samsung Galaxy Glasses|Huawei Eyewear(?:\s*\d)?|OPPO Air Glass\s*\d?|Even Realities G\d|XREAL (?:One(?: Pro)?|Air\s*\d(?: Pro)?)|Rokid Glasses|VITURE (?:Luma(?: Pro)?|Beast)|Google Android XR Glasses)"),
    ("AI 기기", r"(?:PLAUD Note(?: Pro|Pin(?: S)?)?|Rabbit R1|Humane AI Pin|Limitless Pendant|Bee Pioneer|Friend Pendant|Omi (?:AI|Pendant))"),
    ("폰", r"(?:Huawei\s+(?:Mate|Pura|Nova)\s*\d{1,3}|OPPO Reno\s*\d{1,3}|vivo V\s*\d{1,3}|Redmi K\s*\d{1,3}|POCO [FX]\s*\d{1,3})(?:\s+(?:Pro\s+Max|Pro\+?|Ultra|RS|SE|Air))?"),
    ("태블릿", r"(?:(?:Huawei MatePad|OPPO Pad|vivo Pad)\s*(?:Pro\s+|Air\s+)?\d{1,2}(?:\.\d)?(?:\s+(?:Pro|Air|Ultra))?)"),
    ("웨어러블", r"(?:(?:OPPO Enco|vivo TWS|Huawei FreeBuds)\s*(?:Pro\s*)?\d{1,2}(?:\s+Pro)?)"),
    ("워치", r"(?:Apple Watch|Galaxy Watch|Pixel Watch|Huawei Watch|Xiaomi Watch|OPPO Watch|vivo Watch)\s+(?:(?:Series|Ultra|SE|GT|Fit|S)\s*)?\d{1,3}(?:\s+(?:Classic|Pro|Ultra))?"),
    ("웨어러블", r"(?:Galaxy Ring|AirPods|Galaxy Buds|Pixel Buds|Xiaomi Smart Band)\s+(?:\d{1,2}|Pro(?:\s+\d{1,2})?)(?:\s+(?:Pro|Ultra))?"),
    ("태블릿", r"(?:iPad(?:\s+(?:Pro|Air|mini))?\s+(?:M\d|A\d{2}|\d{1,2}(?:th)?(?:\s*세대)?)|(?:Galaxy Tab S|Xiaomi Pad |Redmi Pad )\d{1,2}(?:\s*(?:Ultra|Pro|Plus|FE|\+))?)"),
    ("노트북", r"(?:MacBook(?:\s+(?:Pro|Air))?\s+M\d(?:\s+(?:Pro|Max))?|(?:Galaxy Book|Huawei MateBook|RedmiBook)\s*\d{1,2}(?:\s+(?:Pro|Ultra|360))?)"),
    ("폰", r"(?:iPhone|Pixel|Galaxy\s+(?:S|A|(?:Z\s+)?Fold|(?:Z\s+)?Flip)|Xiaomi|Redmi\s+Note|OPPO\s+Find\s+[XN]|vivo\s+X)\s*\(?\d{1,3}\)?(?:\s+(?:Pro\s+Max|Pro\s+XL|Pro\s+Fold|Pro|Ultra|Plus|FE|Air|Fold)|[ea](?!\w)|\+)?"),
]
REVIEW = re.compile(r"review|hands[ -]on|first (?:look|impressions)|unbox|리뷰|첫인상|실사용|사용기|언박싱|체험|개봉", re.I)
NON_REVIEW = re.compile(r"\b(?:trailer|concept|rumou?rs?|leaks?)\b|루머|유출|콘셉트|예고편", re.I)
LONG_USE = re.compile(r"\b(?:long[ -]term|revisited|(?:one|a|\d+)\s*(?:months?|years?)|(?:[3-9]\d|\d{3,})\s*days?)\b|장기 사용|한\s*달|\d+\s*(?:개월|년)|(?:[3-9]\d|\d{3,})\s*일\s*(?:사용|후)", re.I)
NEW_REVIEW = re.compile(r"hands[ -]on|first (?:look|impressions)|unbox|launch|\bnew\b|신제품|출시|첫인상|언박싱|개봉|체험", re.I)
SPEC = re.compile(r"\b(?:\d{2,3}\s*Hz|\d{3,5}\s*(?:nits|니트)|\d{3,5}\s*mAh|\d{1,2}(?:\.\d)?\s*(?:inch(?:es)?|인치)|(?:AM)?OLED|Mini[ -]LED|LCD)\b", re.I)


def edition(now):
    local = now.astimezone(KST)
    cutoff = datetime.combine(local.date(), time(8), KST)
    return cutoff if local >= cutoff else cutoff - timedelta(days=1)


def product_identity(name):
    return re.sub(r"[^a-z0-9가-힣]", "", name.casefold())


def model_matches(title):
    for alias, canonical in ALIASES.items():
        title = title.replace(alias, canonical)
    title = " ".join(title.split())
    return [(category, " ".join(match.group().split()))
            for category, pattern in PATTERNS
            for match in re.finditer(r"(?<![A-Za-z0-9])" + pattern + r"(?![A-Za-z0-9])", title, re.I)]


def group_reviews(videos, *, early=True):
    products, unmatched = {}, []
    for video in videos:
        title = unescape(video["title"])
        if not (REVIEW.search(title) or (not early and LONG_USE.search(title))):
            continue
        if NON_REVIEW.search(title) or (early and (LONG_USE.search(title) or not NEW_REVIEW.search(title))):
            continue
        matches = model_matches(title)
        # A comparison title alone does not identify which device is being reviewed.
        if len({name.casefold() for _, name in matches}) != 1:
            unmatched.append(video)
            continue
        category, name = matches[0]
        identity = product_identity(name)
        product = products.setdefault(identity, {"name": name, "keyword": name + " 리뷰|" + name + " review",
                                                   "category": category, "videos": [], "mentions": []})
        product["videos"].append(video)
        for match in SPEC.finditer(title):
            product["mentions"].append({"value": match.group(), "source": video["url"]})
    return list(products.values()), unmatched


def search_video_metadata(key, queries, start, end, limit=50):
    videos = {}
    searches = ((language, query) for language, terms in queries.items()
                for query in ((terms,) if isinstance(terms, str) else terms))
    for language, query in searches:
        data = get_json("https://www.googleapis.com/youtube/v3/search", {
            "key": key, "part": "snippet", "type": "video", "videoCategoryId": "28",
            "q": query, "relevanceLanguage": language, "order": "relevance", "maxResults": limit,
            "publishedAfter": start.astimezone(timezone.utc).isoformat(),
            "publishedBefore": end.astimezone(timezone.utc).isoformat(),
        })
        for item in data.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]
            videos[video_id] = {
                "title": unescape(snippet.get("title", "")), "channel": unescape(snippet.get("channelTitle", "")),
                "published": snippet.get("publishedAt", ""),
                "id": video_id, "channel_id": snippet.get("channelId", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
    return sorted(videos.values(), key=lambda item: item["published"], reverse=True)


def refresh(now=None):
    now = now or datetime.now(timezone.utc)
    key = key_from_files()
    if not key:
        raise CollectionError("YouTube API 키가 없습니다. 2.env를 확인하세요.")
    cutoff = edition(now)
    ordered = search_video_metadata(key, QUERIES, cutoff - timedelta(days=1), cutoff)
    products, _ = group_reviews(ordered)
    result = {"edition": cutoff.isoformat(), "checked_at": now.isoformat(),
              "products": products, "rules_version": 2}
    write_json(CACHE, result)
    return result


def read_brief(now=None):
    now = now or datetime.now(timezone.utc)
    result = read_json(CACHE, {})
    try:
        if now - datetime.fromisoformat(result["checked_at"]) < timedelta(days=2):
            return result
    except (KeyError, TypeError, ValueError):
        pass
    return {}


if __name__ == "__main__":
    try:
        result = refresh()
        print("Morning briefing candidates:", len(result["products"]))
    except (CollectionError, OSError) as exc:
        print("Morning briefing failed:", type(exc).__name__)
        raise SystemExit(1) from None
