from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from news_tracker import from_feed, looks_mojibake  # noqa: E402


class FeedEncodingTests(unittest.TestCase):
    def test_repairs_utf8_feed_with_one_invalid_byte(self) -> None:
        raw = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<rss version="2.0"><channel><title>News</title><item>'
            b'<title>\xe6\x96\xb0\xe6\x99\xba\xe5\x85\x83\xe4\xb8\xad\xe6\x96\x87\xe6\xa0\x87\xe9\xa2\x98</title>'
            b'<link>https://example.com/story</link>'
            b'<pubDate>Sun, 23 Aug 2026 01:00:00 GMT</pubDate>'
            b'<description>valid text \xe6\x8a</description>'
            b'</item></channel></rss>'
        )
        now = datetime(2026, 8, 23, 2, tzinfo=timezone.utc)
        with patch("news_tracker.get", return_value=SimpleNamespace(content=raw)):
            items = from_feed({"name": "新智元"}, "https://example.com/feed", now, now - timedelta(days=1))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "新智元中文标题")
        self.assertFalse(looks_mojibake(items[0].title))


if __name__ == "__main__":
    unittest.main()
