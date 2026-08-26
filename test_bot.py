import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from bot import (
    Topic,
    build_feed_url,
    build_line_messages,
    collect_topics,
    is_social_profile_or_home_url,
    load_state,
    merge_topic,
    parse_feed,
    send_line,
    update_state,
)


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>TikTok Lite 招待キャンペーン - X</title>
      <link>https://x.com/example/status/1</link>
      <description><![CDATA[<b>TikTok Lite</b> の報酬情報]]></description>
      <pubDate>Wed, 26 Aug 2026 03:00:00 GMT</pubDate>
    </item>
    <item>
      <title>古いTikTok情報</title>
      <link>https://x.com/example/status/old</link>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")


def make_topic(index: int, url: str | None = None) -> Topic:
    return Topic(
        id=f"id-{index}",
        platform="X" if index % 2 else "Threads",
        title=f"TikTok Lite 新着情報 {index}",
        url=url or f"https://x.com/example/status/{index}",
        summary="",
        published_at="2026-08-26T03:00:00+00:00",
        search_provider="test",
        score=index,
    )


class BotTests(unittest.TestCase):
    def test_parse_feed_removes_old_item_and_suffix(self):
        topics = parse_feed(
            RSS_SAMPLE,
            platform="X",
            search_provider="test",
            lookback_hours=48,
            now=datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0].title, "TikTok Lite 招待キャンペーン")
        self.assertIn("報酬情報", topics[0].summary)

    def test_merge_prefers_direct_social_link(self):
        indirect = make_topic(1, "https://news.google.com/rss/articles/abc")
        direct = make_topic(1, "https://x.com/example/status/1")
        merged = merge_topic(indirect, direct)
        self.assertEqual(merged.url, direct.url)

    def test_social_profiles_are_rejected_but_posts_are_allowed(self):
        self.assertTrue(is_social_profile_or_home_url("https://x.com/tiktok_japan"))
        self.assertTrue(
            is_social_profile_or_home_url("https://instagram.com/tiktok_japan/")
        )
        self.assertFalse(
            is_social_profile_or_home_url(
                "https://x.com/example/status/123456789"
            )
        )
        self.assertFalse(
            is_social_profile_or_home_url(
                "https://www.threads.net/@example/post/ABC123"
            )
        )

    def test_line_messages_stay_inside_line_limits(self):
        topics = [make_topic(index) for index in range(1, 41)]
        messages = build_line_messages(
            topics,
            total_new=len(topics),
            max_items=40,
            now=datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc),
        )
        self.assertLessEqual(len(messages), 5)
        self.assertTrue(all(len(message) <= 5000 for message in messages))
        self.assertIn("無料試作版", messages[-1])

    def test_state_round_trip_and_retention(self):
        now = datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)
        state = update_state(
            {"seen": {}}, [make_topic(i) for i in range(5)], now, retention=3
        )
        self.assertEqual(len(state["seen"]), 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            loaded = load_state(path)
            self.assertEqual(len(loaded["seen"]), 3)

    def test_feed_urls_are_https(self):
        self.assertTrue(
            build_feed_url("bing_web_rss", "test", 48).startswith("https://")
        )
        self.assertTrue(
            build_feed_url("google_news_rss", "test", 48).startswith("https://")
        )

    @patch("bot.fetch_url", return_value=RSS_SAMPLE)
    def test_collect_topics_end_to_end_with_duplicate_feeds(self, mocked_fetch):
        config = {
            "keywords": ["TikTok Lite"],
            "required_terms": ["TikTok"],
            "platforms": [
                {"name": "X", "domains": ["x.com"], "enabled": True}
            ],
            "search_providers": [
                {"name": "search-1", "kind": "bing_web_rss", "enabled": True},
                {"name": "search-2", "kind": "google_news_rss", "enabled": True},
            ],
            "score_terms": {"招待": 5},
            "lookback_hours": 48,
        }
        topics, errors = collect_topics(
            config, now=datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(mocked_fetch.call_count, 2)
        self.assertEqual(errors, [])
        self.assertEqual(len(topics), 1)
        self.assertGreater(topics[0].score, 0)

    def test_line_rejects_too_long_message_before_network(self):
        with self.assertRaises(RuntimeError):
            send_line(["x" * 5001])


if __name__ == "__main__":
    unittest.main()
