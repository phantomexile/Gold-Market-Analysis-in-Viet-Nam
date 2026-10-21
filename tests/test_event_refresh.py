"""Kiểm tra dữ liệu sự kiện mới trước khi đưa vào model."""

from datetime import date
import unittest

import pandas as pd

from scripts.pipeline.refresh_event_inputs import merge_news_rows, new_regime_rows, parse_rss_items, prepare_gpr


class EventRefreshTests(unittest.TestCase):
    def test_rss_requires_a_real_publication_date_and_url(self):
        xml = b"""<rss><channel>
      <item><title>Gia vang SJC tang</title><link>https://example.org/one</link>
        <pubDate>Tue, 20 Oct 2026 08:00:00 GMT</pubDate></item>
      <item><title>Undated</title><link>https://example.org/two</link></item>
      <item><title>Future</title><link>https://example.org/three</link>
        <pubDate>Thu, 22 Oct 2026 08:00:00 GMT</pubDate></item>
    </channel></rss>"""
        rows = parse_rss_items(xml, "giá vàng SJC", date(2026, 10, 21))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_date"], "2026-10-20")
        self.assertEqual(rows[0]["availability_from"], "2026-10-21")


    def test_merge_preserves_existing_metadata_and_deduplicates_url(self):
        old = [{"event_date": "2026-07-11", "url": "https://example.org/old", "feature_mode_strict": "backfilled_not_realtime"}]
        fresh = [{"event_date": "2026-10-20", "url": "https://example.org/new", "headline": "Giá vàng"}]
        merged, added = merge_news_rows(old, fresh + fresh)
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["feature_mode_strict"], "backfilled_not_realtime")


    def test_gpr_keeps_existing_schema_and_only_published_dates(self):
        source = pd.DataFrame({"DAY": [20261019, 20261022], "GPRD": [200.0, 300.0], "date": ["2026-10-19", "2026-10-22"]})
        current = pd.DataFrame({"DAY": [20260707], "GPRD": [100.0], "date": ["2026-07-07"]})
        updated = prepare_gpr(source, current, date(2026, 10, 21))
        self.assertEqual(updated["date"].tolist(), ["2026-07-07", "2026-10-19"])
        self.assertEqual(updated["GPRD"].tolist(), [100.0, 200.0])

    def test_regime_rows_keep_auditable_news_source(self):
        news = [{"event_date": "2026-10-20", "headline": "Ngân hàng Nhà nước thay đổi chính sách vàng", "url": "https://example.org/policy", "source": "google_news_rss:Example", "crawl_date": "2026-10-21"}]
        result = new_regime_rows(news, [], date(2026, 10, 21))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_url"], "https://example.org/policy")
        self.assertEqual(result[0]["source"], "google_news_rss_event_proxy")


if __name__ == "__main__":
    unittest.main()
