import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis_engine import PlanningInsight, PlanningReport, synthesize_display
from followup_brief import Pick, Picks, ranked_candidates, refresh_followup, select_products
from planning_view import sentiment_rates, video_coverage
from morning_brief import edition
from product_specs import CATALOG, official_image_url, resolve_specs


class PlanningTests(unittest.TestCase):
    def test_product_specs_only_match_exact_model_and_use_manufacturer_images(self):
        self.assertEqual(resolve_specs("Google Pixel 10 Pro")["fields"]["해상도"], "1280 × 2856")
        self.assertIsNone(resolve_specs("Pixel 10 Pro XL"))
        self.assertIsNone(resolve_specs("AI Glasses"))
        for product, entry in CATALOG.items():
            self.assertTrue(official_image_url(resolve_specs(product)["image"], entry["url"]), product)
        unofficial = {"url": "https://www.gsmarena.com/example", "text": "화면: OLED",
                      "image": "https://i.ytimg.com/vi/example/default.jpg"}
        resolved = resolve_specs("Example", unofficial)
        self.assertFalse(resolved.get("official"))
        self.assertEqual(resolved["image"], "")
    def test_coverage_counts_unique_videos_and_channels_and_preserves_unknown_views(self):
        videos = [
            {"원본 URL": "a", "채널 ID": "1", "채널명": "리뷰 채널", "영상 조회수": "30"},
            {"원본 URL": "a", "채널 ID": "1", "채널명": "리뷰 채널", "영상 조회수": "30"},
            {"원본 URL": "b", "채널 ID": "1", "채널명": "리뷰 채널", "영상 조회수": "80"},
            {"원본 URL": "c", "채널 ID": "2", "채널명": "리뷰 채널", "영상 조회수": ""},
        ]
        channels, peak = video_coverage(videos)
        self.assertEqual([count for _, count in channels.values()], [2, 1])
        self.assertEqual(peak, 80)
        self.assertIsNone(video_coverage(videos[3:])[1])

    def test_followup_card_opens_analysis_detail(self):
        now = datetime.now(timezone.utc)
        product = {"name": "Pixel 10", "category": "폰", "keyword": "Pixel 10 review",
                   "reason": "장기 리뷰", "question": "야외 가독성은 어떤가?",
                   "video": {"url": "https://www.youtube.com/watch?v=video"}}
        cutoff = edition(now).isoformat()
        with patch("discovery.settings", return_value={"followup_ai": True, "followup_scope": 2, "days": 30, "videos": 20, "language": "ko",
                                                       "comments": 100, "analysis_limit": 10}), \
             patch("discovery.key_from_files", return_value=""), \
             patch("morning_brief.read_brief", return_value={"edition": cutoff, "checked_at": now.isoformat(), "products": []}), \
             patch("followup_brief.read_followup", return_value={"edition": cutoff, "rules_version": 2, "products": [product]}):
            app = AppTest.from_file("product_hub.py", default_timeout=30).run()
            next(button for button in app.button if button.label == "이 제품 분석하기").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any(header.value == "Pixel 10 · 출시 후 반응" for header in app.header))

    def test_valid_comment_denominator(self):
        rates = sentiment_rates(pd.DataFrame({"감정": ["긍정"] * 6 + ["부정"] * 2 + ["복합", "중립"]}))
        self.assertEqual(rates.loc["긍정", "비율 (%)"], 60)
        self.assertEqual(rates.loc["부정", "비율 (%)"], 20)

    def test_followup_disabled_before_search(self):
        with patch("followup_brief.settings", return_value={}), patch("followup_brief.search_video_metadata") as search:
            with self.assertRaises(PermissionError):
                refresh_followup()
            search.assert_not_called()

    def test_followup_rejects_duplicate_and_unmatched_products(self):
        client = Mock()
        picks = [Pick(product=name, category="폰", video_id=index, reason="장기 사용", question="야외 가독성?")
                 for name, index in [("Pixel 10", 1), ("Pixel 10", 2), ("Pixel 1", 2), ("iPhone 18", 3)]]
        client.responses.parse.return_value = Mock(status="completed", output_parsed=Picks(products=picks))
        videos = [{"title": title, "published": "", "url": f"https://www.youtube.com/watch?v={i}"}
                  for i, title in enumerate(["Pixel 10 long-term review", "Pixel 10 after 4 months", "iPhone 17 revisited"])]
        candidates = ranked_candidates(videos, datetime.now(timezone.utc), {})
        self.assertEqual([row["name"] for row in select_products(client, candidates)], ["Pixel 10"])

    def test_views_and_distinct_channels_support_shortlist_without_long_use(self):
        now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        rows = [("iPhone 18", "a", 2000), ("Pixel 10", "b", 100), ("Galaxy S26", "c", 200),
                ("vivo X300", "d", 300), ("Xiaomi 17", "e", 0), ("Xiaomi 17", "f", 0),
                ("Xiaomi 17", "g", 0), ("Xiaomi 17", "g", 0)]
        videos = [{"id": str(i), "title": name + " review", "published": now.isoformat(),
                   "url": str(i), "channel_id": channel} for i, (name, channel, _) in enumerate(rows)]
        views = {str(i): count for i, (_, _, count) in enumerate(rows) if count}
        signals = {item["name"]: item for item in ranked_candidates(videos, now, views)}
        self.assertEqual(signals["iPhone 18"]["view_signal"]["ratio"], 10)
        self.assertEqual(signals["Xiaomi 17"]["channel_count"], 3)
        self.assertNotIn("Pixel 10", signals)

    def test_report_discards_invalid_citations(self):
        client = Mock()
        insights = [PlanningInsight(kind="개선 우선순위", headline="반사", observation="야외 반사 언급",
                                    proposal="반사 저감 시험", validation="동일 조도에서 비교", evidence_ids=[i])
                    for i in [1, 99]]
        client.responses.parse.return_value = Mock(status="completed", output_parsed=PlanningReport(insights=insights))
        self.assertEqual(synthesize_display(client, "Phone", [{"id": 1}]), insights[:1])
