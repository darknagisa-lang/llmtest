import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from discovery import discover
from morning_brief import KST, edition, group_reviews


class ProductHubTests(unittest.TestCase):
    def test_home_search_passes_only_confirmed_videos_to_analysis(self):
        cfg = {"language": "en", "days": 30, "videos": 12, "comments": 100, "analysis_limit": 10}
        now = datetime.now(timezone.utc)
        brief = {"edition": edition(now).isoformat(), "rules_version": 2, "checked_at": now.isoformat(), "products": []}
        videos = [{"id": video_id, "영상 제목": title, "채널": "Review channel", "게시일": "2026-11-24",
                   "썸네일": "", "영상 링크": f"https://www.youtube.com/watch?v={video_id}"}
                  for video_id, title in [("aaaaaaaaaaa", "Pixel 10 Pro review"), ("bbbbbbbbbbb", "Pixel 10 review")]]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake"}), patch("discovery.settings", return_value=cfg), \
             patch("discovery.key_from_files", return_value="fake"), patch("morning_brief.read_brief", return_value=brief), \
             patch("collectors.search_product_reviews", return_value=videos), \
             patch("collectors.youtube_collect", return_value=([], [], [])) as collect:
            app = AppTest.from_file("product_hub.py", default_timeout=30).run()
            app.text_input[0].set_value("Pixel 10 Pro")
            next(b for b in app.button if b.label == "YouTube 검색").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.multiselect)
            self.assertTrue(next(b for b in app.button if b.key == "prepare_selected_videos").disabled)
            app.session_state[app.dataframe[0].key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
            app.run()
            action = next(b for b in app.button if b.key == "prepare_selected_videos")
            self.assertEqual(action.label, "선택한 영상 1편 분석하기")
            action.click().run()
            self.assertFalse(any(b.label == "영상과 댓글만 수집" for b in app.button))
            for checkbox in app.checkbox:
                checkbox.check()
            app.run()
            next(b for b in app.button if b.label == "리뷰 수집 및 분석 시작").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(collect.call_args.kwargs["selected_video_ids"], ["aaaaaaaaaaa"])
            self.assertEqual(next(radio.value for radio in app.radio if radio.label == "분석 범위"), "수집한 댓글 전체")

    def test_morning_window_and_discovered_devices(self):
        self.assertEqual(edition(datetime(2026, 11, 24, 7, 59, tzinfo=KST)).day, 23)
        self.assertEqual(edition(datetime(2026, 11, 24, 8, tzinfo=KST)).day, 24)
        products, unmatched = group_reviews([
            {"title": "vivo X300 first look: 165Hz OLED", "url": "https://www.youtube.com/watch?v=a"},
            {"title": "Galaxy Watch 8 첫인상", "url": "https://www.youtube.com/watch?v=b"},
            {"title": "New Acme device hands-on", "url": "https://www.youtube.com/watch?v=c"},
            {"title": "iPhone 18 First Look Trailer", "url": "https://www.youtube.com/watch?v=d"},
            {"title": "Galaxy Z Fold 8 Review - 4 Months Later", "url": "https://www.youtube.com/watch?v=e"},
        ])
        self.assertEqual([(p["name"], p["category"]) for p in products],
                         [("vivo X300", "폰"), ("Galaxy Watch 8", "워치")])
        self.assertEqual(products[0]["mentions"][0]["value"], "165Hz")
        self.assertEqual(len(unmatched), 1)

    def test_discovery_maps_video(self):
        item = {"id":{"videoId":"x"}, "snippet":{"title":"Review", "channelTitle":"Reviewer", "publishedAt":"2026-11-24T00:00:00Z", "thumbnails":{"medium":{"url":"https://example.test/image"}}}}
        with patch("discovery.get_json", return_value={"items":[item]}) as get:
            result = discover("secret", {"name":"Phone", "keyword":"Phone review"}, "en", datetime(2026,11,24,tzinfo=timezone.utc))
        self.assertEqual(result["videos"][0]["channel"], "Reviewer")
        self.assertEqual(get.call_args.args[1]["relevanceLanguage"], "en")

    def test_product_to_analysis(self):
        cfg = {"products":[{"name":"Phone", "keyword":"Phone review"}], "language":"en", "days":30, "videos":20, "comments":100, "analysis_limit":10}
        cache = {"Phone":{"checked_at":datetime.now(timezone.utc).isoformat(), "videos":[], "error":""}}
        comment = {"댓글":"Great screen", "댓글 작성일":"2026-11-24T00:00:00Z", "원본 URL":"https://youtube.com/watch?v=x", "영상 제목":"Review"}
        response = {"is_spam":False, "is_relevant":True, "aspects":[{"feature":"디스플레이", "sentiment":"긍정", "evidence":"화면 만족"}], "language":"영어", "sentiment":"긍정", "needs":[], "future_features":[], "complaints":[], "defects":[], "purchase_intent":"미확인", "summary":"화면 호평"}
        with patch.dict(os.environ, {"OPENAI_API_KEY":"fake"}), patch("discovery.settings", return_value=cfg), patch("discovery.read_cache", return_value=cache), patch("discovery.key_from_files", return_value="fake"), patch("collectors.youtube_collect", return_value=([], [comment], [])), patch("youtube_pipeline.analyze_text", return_value=response), patch("analysis_engine.synthesize_display", return_value=[]) as synthesize:
            app = AppTest.from_file("product_hub.py", default_timeout=30).run()
            app.radio[0].set_value("관심 제품 검색").run()
            next(b for b in app.button if b.label == "리뷰 살펴보기").click().run()
            self.assertTrue(next(b for b in app.button if b.label == "리뷰 수집 및 분석 시작").disabled)
            for checkbox in app.checkbox: checkbox.check()
            app.run()
            next(b for b in app.button if b.label == "리뷰 수집 및 분석 시작").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["hub_result"]["result"].iloc[0]["내용"], "Great screen")
            self.assertEqual(app.session_state["hub_result"]["result"].iloc[0]["URL"], comment["원본 URL"])
            self.assertEqual(synthesize.call_args.args[2][0]["excerpt"], "Great screen")


if __name__ == "__main__": unittest.main()
