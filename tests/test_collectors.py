from __future__ import annotations

import bootstrap  # noqa: F401

import json
import os
import unittest

from gold_collectors.collectors import SjcOfficialCollector
from gold_collectors.http import HttpResponse
from gold_collectors.parsing import extract_table_rows, parse_dotnet_date


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post_form(self, url, data, use_cache=True):
        key = data["method"]
        if key == "GetGoldPriceHistory":
            key = f"{key}:{data['goldPriceId']}"
        self.calls.append((url, data))
        text = self.responses[key]
        return HttpResponse(url=url, status=200, text=text, raw_payload_hash="hash", from_cache=False)


class SjcOfficialCollectorTests(unittest.TestCase):
    def test_get_price_by_date_parses_historical_date_records(self):
        fake = FakeHttp(
            {
                "GetSJCGoldPriceByDate": json.dumps(
                    {
                        "success": True,
                        "currentDate": "18/11/2013",
                        "data": [
                            {
                                "Id": 0,
                                "TypeName": "VÃ ng SJC 1L, 10L, 1KG",
                                "BranchName": "Há»“ ChÃ­ Minh",
                                "Buy": "36,460",
                                "BuyValue": 36460000.0,
                                "Sell": "36,510",
                                "SellValue": 36510000.0,
                                "GroupDate": "/Date(-62135596800000)/",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            }
        )
        records = SjcOfficialCollector(fake).get_price_by_date("18/11/2013")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].branch, "Há»“ ChÃ­ Minh")
        self.assertEqual(records[0].buy_value, 36460000.0)
        self.assertEqual(records[0].reference_date, "2013-11-18")

    def test_get_history_distinguishes_empty_success_from_failure(self):
        fake = FakeHttp({"GetGoldPriceHistory:49": json.dumps({"success": True, "data": []})})
        records = SjcOfficialCollector(fake).get_history(49, "18/11/2013", "18/11/2013")
        self.assertEqual(records, [])

    def test_get_history_parses_intraday_records(self):
        fake = FakeHttp(
            {
                "GetGoldPriceHistory:1": json.dumps(
                    {
                        "success": True,
                        "data": [
                            {
                                "Id": 0,
                                "TypeName": "VÃ ng SJC 1L, 10L, 1KG",
                                "BranchName": "Há»“ ChÃ­ Minh",
                                "Buy": "36,440",
                                "BuyValue": 36440000.0,
                                "Sell": "36,540",
                                "SellValue": 36540000.0,
                                "GroupDate": "/Date(1384707600000)/",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            }
        )
        records = SjcOfficialCollector(fake).get_history(1, "18/11/2013", "18/11/2013")
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].observed_at)
        self.assertEqual(records[0].metadata["raw_group_date"], "/Date(1384707600000)/")


class ParserTests(unittest.TestCase):
    def test_dotnet_negative_sentinel_returns_none(self):
        self.assertIsNone(parse_dotnet_date("/Date(-62135596800000)/"))

    def test_html_table_rows(self):
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>1</td></tr></table>"
        self.assertEqual(extract_table_rows(html), [["A", "B"], ["x", "1"]])


@unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "1", "Set RUN_LIVE_TESTS=1 to run live integration tests.")
class LiveSmokeTests(unittest.TestCase):
    def test_sjc_gold_price_id_1_has_2013_history(self):
        records = SjcOfficialCollector().get_history(1, "18/11/2013", "18/11/2013")
        self.assertGreater(len(records), 0)

    def test_sjc_unavailable_type_returns_empty_success(self):
        records = SjcOfficialCollector().get_history(49, "18/11/2013", "18/11/2013")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()

