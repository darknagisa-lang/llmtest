import unittest
from unittest.mock import patch
import os

import httpx
import openai
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from analysis_engine import Reaction, cache_key
from collectors import youtube_collect
from youtube_pipeline import analyze_comments


class PlatformTests(unittest.TestCase):
    def test_collection_to_dashboard(self):
        comment = {"댓글":"화면은 좋아요", "댓글 작성일":"2026-01-02T10:00:00Z", "원본 URL":"https://youtube.com/watch?v=x", "영상 제목":"review"}
        response = {"is_spam":False, "is_relevant":True, "aspects":[{"feature":"디스플레이", "sentiment":"긍정"}], "language":"한국어", "sentiment":"긍정", "needs":[], "future_features":[], "complaints":[], "defects":[], "purchase_intent":"미확인", "summary":"화면 호평"}
        with patch.dict(os.environ, {"YOUTUBE_API_KEY":"dummy", "OPENAI_API_KEY":"dummy"}), patch("collectors.youtube_collect", return_value=([], [comment], [])), patch("youtube_pipeline.analyze_text", return_value=response):
            app = AppTest.from_file("dashboard.py", default_timeout=30).run()
            app.radio[0].set_value("Data Collection").run()
            next(c for c in app.checkbox if c.label.startswith("수집 후 댓글 AI")).check().run()
            self.assertTrue(next(b for b in app.button if b.label == "YouTube 검색 및 수집").disabled)
            for label in ["이 프로젝트와 수집 대상 범위", "이 데이터의 OpenAI 전송", "OpenAI 분석 호출에 따른"]:
                next(c for c in app.checkbox if c.label.startswith(label)).check()
            app.run()
            next(b for b in app.button if b.label == "YouTube 검색 및 수집").click().run()
            self.assertFalse(app.exception)
            app.radio[0].set_value("Overview").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["analysis_data"].iloc[0]["내용"], comment["댓글"])

    def test_pipeline_permission_and_mapping(self):
        comment = {"댓글":"화면은 좋아요", "댓글 작성일":"2026-01-02T10:00:00Z", "원본 URL":"https://youtube.com/watch?v=x", "영상 제목":"review"}
        with self.assertRaises(PermissionError):
            analyze_comments([comment], "제품", None, "model", 1, approved=False, transfer_authorized=True)
        result = {"is_spam":False, "is_relevant":True, "aspects":[{"feature":"디스플레이", "sentiment":"긍정"}], "language":"한국어", "sentiment":"긍정", "needs":[], "future_features":[], "complaints":[], "defects":[], "purchase_intent":"미확인", "summary":"화면 호평"}
        with patch("youtube_pipeline.analyze_text", return_value=result):
            data, stats = analyze_comments([comment], "제품", None, "model", 1, approved=True, transfer_authorized=True)
        self.assertEqual(stats["완료"], 1)
        self.assertEqual(data.iloc[0]["URL"], comment["원본 URL"])
        self.assertEqual(data.iloc[0]["출처"], "YouTube 댓글")

    def test_schema_multiple_aspects(self):
        data = {"sentiment":"복합", "language":"한국어", "translation_ko":"", "is_relevant":True, "is_spam":False,
                "aspects":[{"feature":"디스플레이", "sentiment":"긍정", "evidence":"화면 좋음"}, {"feature":"가격", "sentiment":"부정", "evidence":"비쌈"}],
                "complaints":[], "purchase_intent":"미확인", "needs":[], "future_features":[], "defects":[], "improvements":[], "comparisons":[], "review_stage":"미확인", "buyer_status":"미확인", "summary":"화면은 좋지만 비쌈"}
        self.assertEqual(len(Reaction.model_validate(data).aspects), 2)
        self.assertNotEqual(cache_key("m", "p", "a"), cache_key("m", "p", "b"))

    def test_pipeline_continues_after_invalid_structured_response(self):
        with self.assertRaises(ValidationError) as caught:
            Reaction.model_validate({})
        comments = [{"댓글": text} for text in ("잘못된 응답", "다음 댓글", "상한 밖")]
        with patch("youtube_pipeline.analyze_text_batch", side_effect=caught.exception), \
             patch("youtube_pipeline.analyze_text", side_effect=[caught.exception, {"is_spam": True}]) as analyze:
            _, stats = analyze_comments(comments, "제품", None, "model", 2, approved=True, transfer_authorized=True)
        self.assertEqual(analyze.call_count, 2)
        self.assertEqual(stats["댓글 오류"], {"응답 형식 불일치": 1})
        self.assertEqual((stats["제외"], stats["실패"], stats["미처리"], stats["설정 상한 제외"], stats["오류"]),
                         (1, 1, 1, 1, ""))

    def test_pipeline_stops_on_api_connection_failure(self):
        failure = openai.APIConnectionError(request=httpx.Request("POST", "https://example.test"))
        with patch("youtube_pipeline.analyze_text_batch", side_effect=failure) as analyze:
            _, stats = analyze_comments([{"댓글": "one"}, {"댓글": "two"}], "제품", None, "model", 2,
                                       approved=True, transfer_authorized=True)
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual((stats["실패"], stats["미처리"], stats["설정 상한 제외"]), (0, 2, 0))
        self.assertIn("연결하지 못했습니다", stats["오류"])

    def test_pipeline_processes_all_382_comments_in_bundles(self):
        comments = [{"댓글": f"댓글 {index}"} for index in range(382)]
        with patch("youtube_pipeline.analyze_text_batch", side_effect=lambda client, model, product, texts:
                   [{"is_spam": True}] * len(texts)) as analyze:
            _, stats = analyze_comments(comments, "제품", None, "model", None, approved=True, transfer_authorized=True)
        self.assertEqual(analyze.call_count, 48)
        self.assertEqual((stats["분석 대상"], stats["제외"], stats["미처리"]), (382, 382, 0))

    def test_youtube_pagination_and_dedup(self):
        video = {"id":{"videoId":"v1"}}
        comment = {"id":"c1", "snippet":{"textDisplay":"great", "publishedAt":"2026-01-01", "likeCount":1}}
        responses = [{"items":[video]}, {"items":[{"id":"v1", "snippet":{"title":"review"}, "statistics":{}}]},
                     {"items":[{"snippet":{"topLevelComment":comment}}], "nextPageToken":"next"},
                     {"items":[{"snippet":{"topLevelComment":comment}}]}]
        with patch("collectors.get_json", side_effect=responses):
            videos, comments, failures = youtube_collect("key", "test", "en", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", "date", 1, 3, False)
        self.assertEqual((len(videos), len(comments), len(failures)), (1, 1, 0))

    def test_demo_screens(self):
        app = AppTest.from_file("dashboard.py", default_timeout=30).run()
        app.radio[0].set_value("Data Collection").run()
        next(b for b in app.button if b.label == "가상 데이터 불러오기").click().run()
        self.assertFalse(app.exception)
        for page in ["Overview", "Sentiment Analysis", "Feature Analysis", "Product Comparison", "Customer Needs", "AI Insights", "Data Explorer", "Reports", "Settings"]:
            app.radio[0].set_value(page).run()
            self.assertFalse(app.exception, page)


if __name__ == "__main__": unittest.main()
