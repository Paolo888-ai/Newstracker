from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generate_report import render_report  # noqa: E402
from news_tracker import generate_business_lesson  # noqa: E402


class BusinessLessonTests(unittest.TestCase):
    def test_same_date_selects_same_fallback_lesson(self) -> None:
        now = datetime(2026, 8, 24, 1, tzinfo=timezone.utc)
        with patch.dict("news_tracker.os.environ", {}, clear=True):
            first = generate_business_lesson(now, [])
            second = generate_business_lesson(now, [])
        self.assertEqual(first["title"], second["title"])
        self.assertTrue(first["answer"])
        self.assertGreater(len(first["sections"][0]), 40)
        self.assertNotIn("先用自己的话解释", " ".join(first["sections"]))
        self.assertIn("不构成", first["disclaimer"])

    def test_retries_malformed_deepseek_json(self) -> None:
        now = datetime(2026, 9, 14, 1, tzinfo=timezone.utc)
        valid = {
            "title": "资产负债表入门", "category": "财务报表", "summary": "看清企业资源和资金来源。",
            "sections": ["核心概念：资产等于负债加权益。", "为什么重要：观察偿债能力。", "常见误区：资产多不等于现金多。"],
            "example": "公司有100万元资产，其中60万元来自借款。",
            "question": "公司的所有者权益是多少？", "answer": "按资产减负债计算，所有者权益为40万元。", "disclaimer": "仅供学习"
        }
        bad_response = Mock()
        bad_response.raise_for_status.return_value = None
        bad_response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": '{"title":"未结束'}}]}
        good_response = Mock()
        good_response.raise_for_status.return_value = None
        good_response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(valid, ensure_ascii=False)}}]}
        failures = []
        with patch.dict("news_tracker.os.environ", {"DEEPSEEK_API_KEY": "test-key"}, clear=True), patch(
            "news_tracker.requests.post", side_effect=[bad_response, good_response]
        ) as post:
            lesson = generate_business_lesson(now, failures)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(lesson["title"], "资产负债表入门")
        self.assertEqual(failures, [])

    def test_lesson_renders_before_highlights_and_escapes_content(self) -> None:
        data = {
            "title": "日报",
            "date": "2026-08-24",
            "stats": {},
            "business_lesson": {
                "title": "股权 < 分红权",
                "category": "股权基础",
                "summary": "测试",
                "sections": ["核心概念：测试"],
                "example": "甲公司",
                "question": "谁承担风险？",
                "answer": "甲承担经营风险，乙承担资金风险。",
                "disclaimer": "仅供学习"
            },
            "highlights": [], "domains": [], "failures": []
        }
        template = (ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        result = render_report(data, template)
        self.assertLess(result.index("每日商业课"), result.index("今日要点"))
        self.assertIn("股权 &lt; 分红权", result)
        self.assertNotIn("股权 < 分红权", result)
        self.assertIn("查看参考解答", result)
        self.assertIn("甲承担经营风险", result)


if __name__ == "__main__":
    unittest.main()
