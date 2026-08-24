from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
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
        self.assertIn("不构成", first["disclaimer"])

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
                "disclaimer": "仅供学习"
            },
            "highlights": [], "domains": [], "failures": []
        }
        template = (ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        result = render_report(data, template)
        self.assertLess(result.index("每日商业课"), result.index("今日要点"))
        self.assertIn("股权 &lt; 分红权", result)
        self.assertNotIn("股权 < 分红权", result)


if __name__ == "__main__":
    unittest.main()
