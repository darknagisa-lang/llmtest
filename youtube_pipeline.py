"""YouTube comment analysis; callers must obtain the applicable permissions first."""
import json
from collections import Counter, defaultdict
from itertools import zip_longest

import pandas as pd
import openai
from pydantic import ValidationError

from analysis_engine import CommentResponseError, analyze_text, analyze_text_batch

BATCH_SIZE = 8


COMMENT_ERRORS = {
    ValidationError: "응답 형식 불일치",
    openai.APIResponseValidationError: "API 응답 형식 불일치",
    CommentResponseError: "응답 미완료 또는 결과 없음",
    openai.LengthFinishReasonError: "응답 길이 제한",
    openai.ContentFilterFinishReasonError: "응답 생성 제한",
}


def api_error_message(exc):
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return "OpenAI API 키 또는 접근 권한을 확인해 주세요."
    if isinstance(exc, openai.RateLimitError):
        return "OpenAI 요청 또는 사용량 한도에 도달했습니다."
    if isinstance(exc, openai.APIConnectionError):
        return "OpenAI API에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요."
    if isinstance(exc, openai.APIStatusError):
        return f"OpenAI API 요청에 실패했습니다 (HTTP {exc.status_code})."
    return "OpenAI API 요청에 실패했습니다."


def comment_responses(client, model, product, comments):
    texts = [comment["댓글"].strip()[:12000] for comment in comments]
    try:
        if len(texts) == 1:
            yield analyze_text(client, model, product, texts[0]), None
        else:
            for response in analyze_text_batch(client, model, product, texts):
                yield response, None
    except tuple(COMMENT_ERRORS) as exc:
        if len(texts) > 1:
            midpoint = len(comments) // 2
            yield from comment_responses(client, model, product, comments[:midpoint])
            yield from comment_responses(client, model, product, comments[midpoint:])
        else:
            yield None, next(label for error, label in COMMENT_ERRORS.items() if isinstance(exc, error))


def batched_responses(client, model, product, candidates):
    for start in range(0, len(candidates), BATCH_SIZE):
        yield from comment_responses(client, model, product, candidates[start:start + BATCH_SIZE])


def analyze_comments(comments, product, client, model, limit, *, approved, transfer_authorized, progress=lambda *args: None):
    if not approved or not transfer_authorized:
        raise PermissionError("YouTube 분석 승인과 외부 전송 권한을 확인해야 합니다.")
    results, failed, skipped = [], 0, 0
    by_video = defaultdict(list)
    for comment in comments:
        if comment.get("댓글", "").strip():
            video = comment.get("원본 URL", "").split("&lc=", 1)[0] or comment.get("영상 제목", "")
            by_video[video].append(comment)
    eligible = [item for group in zip_longest(*by_video.values()) for item in group if item is not None]
    skipped = len(comments) - len(eligible)
    candidates = eligible if limit is None else eligible[:limit]
    beyond_limit = len(eligible) - len(candidates)
    unprocessed = beyond_limit
    row_errors = Counter()
    stop_reason = ""
    index = -1
    responses = batched_responses(client, model, product, candidates)
    try:
        for index, (r, error) in enumerate(responses):
            comment = candidates[index]
            text = comment["댓글"].strip()
            if error:
                failed += 1
                row_errors[error] += 1
            elif r["is_spam"] or not r["is_relevant"]:
                skipped += 1
            else:
                features = r["aspects"][:2] + [{"feature": "", "sentiment": ""}] * 2
                results.append({"제품": product, "내용": text, "출처": "YouTube 댓글", "유형": comment.get("종류", "댓글"),
                    "날짜": comment.get("댓글 작성일", "")[:10], "URL": comment.get("원본 URL", ""),
                    "영상 제목": comment.get("영상 제목", ""), "언어": r["language"], "감정": r["sentiment"],
                    "기능": features[0]["feature"], "기능 감정": features[0]["sentiment"],
                    "기능2": features[1]["feature"], "기능2 감정": features[1]["sentiment"],
                    "주요 요청": "; ".join(r["needs"] + r["future_features"]),
                    "불만": "; ".join(r["complaints"] + r["defects"]), "구매 의향": r["purchase_intent"],
                    "요약": r["summary"], "국가": "미확인", "분석 상태": "완료", "데이터 구분": "YouTube 실데이터",
                    "분석 JSON": json.dumps(r, ensure_ascii=False)})
            progress(index + 1, len(candidates), len(results), skipped, failed)
    except openai.APIError as exc:
        stop_reason = api_error_message(exc)
        unprocessed += len(candidates) - index - 1
    return pd.DataFrame(results), {
        "완료": len(results), "제외": skipped, "실패": failed, "미처리": unprocessed,
        "설정 상한 제외": beyond_limit, "댓글 오류": dict(row_errors), "오류": stop_reason, "분석 대상": len(candidates),
    }
