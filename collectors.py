"""Official API clients. Collected third-party data is deliberately not written to disk."""
import re
from html import unescape

import requests

BASE = "https://www.googleapis.com/youtube/v3/"

class CollectionError(Exception):
    pass


def get_json(url, params=None, headers=None):
    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        if not response.ok:
            # Never include request URL: it can contain API credentials.
            try:
                reason = response.json().get("error", {}).get("errors", [{}])[0].get("reason", "")
            except (ValueError, AttributeError, IndexError):
                reason = ""
            raise CollectionError(f"API 요청 실패 (HTTP {response.status_code}, {reason or '인증·할당량·설정 확인'})")
        return response.json()
    except requests.RequestException:
        # Request exceptions may contain a URL with an API key.
        raise CollectionError("네트워크 오류 또는 시간 초과") from None


def search_product_reviews(key, product, language, after, before, limit=12):
    terms = re.sub(r'["|]+', " ", product).strip()
    query = f'"{terms}" 리뷰|"{terms}" 실사용' if language == "ko" else f'"{terms}" review|"{terms}" hands-on'
    response = get_json(BASE + "search", {
        "key": key, "q": query, "part": "snippet", "type": "video", "order": "relevance",
        "relevanceLanguage": language, "publishedAfter": after, "publishedBefore": before, "maxResults": limit,
    })
    results = {}
    for item in response.get("items", []):
        video_id = item.get("id", {}).get("videoId", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue
        snippet = item.get("snippet", {})
        results[video_id] = {
            "id": video_id, "영상 제목": unescape(snippet.get("title", "")),
            "채널": unescape(snippet.get("channelTitle", "")),
            "게시일": snippet.get("publishedAt", "")[:10],
            "썸네일": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "영상 링크": "https://www.youtube.com/watch?v=" + video_id,
        }
    return list(results.values())


def youtube_collect(key, query, language, after, before, order, videos, limit, replies, progress=lambda *a: None,
                    *, selected_video_ids=None):
    base = BASE
    common = {"key": key}
    found, token = [], None
    while selected_video_ids is None and len(found) < videos:
        params = dict(common, part="snippet", type="video", q=query, relevanceLanguage=language,
                      publishedAfter=after, publishedBefore=before, order=order, maxResults=min(50, videos-len(found)))
        if token: params["pageToken"] = token
        page = get_json(base+"search", params)
        found.extend(page.get("items", []))
        token = page.get("nextPageToken")
        if not token: break
    if selected_video_ids is None:
        ids = list(dict.fromkeys(item["id"]["videoId"] for item in found))
    else:
        ids = list(dict.fromkeys(i for i in selected_video_ids if re.fullmatch(r"[A-Za-z0-9_-]{11}", i)))[:videos]
    metadata = {}
    for start in range(0, len(ids), 50):
        page = get_json(base+"videos", dict(common, part="snippet,statistics", id=",".join(ids[start:start+50])))
        metadata.update({x["id"]: x for x in page.get("items", [])})
    video_rows = [{"영상 제목": metadata.get(i, {}).get("snippet", {}).get("title", ""),
                   "영상 게시일": metadata.get(i, {}).get("snippet", {}).get("publishedAt", ""),
                   "영상 설명": metadata.get(i, {}).get("snippet", {}).get("description", ""),
                   "채널명": metadata.get(i, {}).get("snippet", {}).get("channelTitle", ""),
                   "채널 ID": metadata.get(i, {}).get("snippet", {}).get("channelId", ""),
                   "썸네일": metadata.get(i, {}).get("snippet", {}).get("thumbnails", {}).get("medium", {}).get("url", ""),
                   "영상 조회수": metadata.get(i, {}).get("statistics", {}).get("viewCount", ""),
                   "원본 URL": "https://www.youtube.com/watch?v=" + i} for i in ids]
    rows, failures, seen = [], [], set()
    for index, video_id in enumerate(ids):
        video = metadata.get(video_id, {})
        snippet = video.get("snippet", {})
        count, token = 0, None
        try:
            while count < limit:
                params = dict(common, part="snippet", videoId=video_id, maxResults=min(100, limit-count), textFormat="plainText")
                if token: params["pageToken"] = token
                page = get_json(base+"commentThreads", params)
                for thread in page.get("items", []):
                    top = thread["snippet"]["topLevelComment"]
                    candidates = [top]
                    if replies and thread["snippet"].get("totalReplyCount", 0):
                        rt = None
                        while True:
                            rp = dict(common, part="snippet", parentId=top["id"], maxResults=100, textFormat="plainText")
                            if rt: rp["pageToken"] = rt
                            reply_page = get_json(base+"comments", rp)
                            candidates.extend(reply_page.get("items", []))
                            rt = reply_page.get("nextPageToken")
                            if not rt or len(candidates) >= limit-count: break
                    for comment in candidates:
                        if count >= limit: break
                        if comment["id"] in seen: continue
                        seen.add(comment["id"])
                        s = comment["snippet"]
                        rows.append({"영상 제목": snippet.get("title", ""), "영상 게시일": snippet.get("publishedAt", ""),
                                     "영상 조회수": video.get("statistics", {}).get("viewCount", ""), "댓글 작성일": s.get("publishedAt", ""),
                                     "댓글": s.get("textDisplay", ""), "좋아요": s.get("likeCount", 0),
                                     "원본 URL": f"https://www.youtube.com/watch?v={video_id}&lc={comment['id']}",
                                     "종류": "대댓글" if comment is not top else "댓글"})
                        count += 1
                token = page.get("nextPageToken")
                if not token: break
        except CollectionError as exc:
            failures.append(f"영상 {index+1}: {exc}")
            if "quota" in str(exc).lower():
                progress(index+1, len(ids), len(rows), len(failures))
                break
        progress(index+1, len(ids), len(rows), len(failures))
    return video_rows, rows, failures
