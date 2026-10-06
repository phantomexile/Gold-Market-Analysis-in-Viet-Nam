from __future__ import annotations

import bootstrap  # noqa: F401

import unittest

from gold_collectors.models import GoldPriceRecord
from gold_collectors.reliability import (
    AuditRecord,
    STATUS_CURRENT_ONLY,
    STATUS_HISTORICAL_VALID,
    build_registry_from_audit,
    business_date_from_record,
    gold_record_to_target_row,
)


class SourceReliabilityTests(unittest.TestCase):
    def test_current_leak_is_not_historical_valid(self):
        registry = build_registry_from_audit(
            [
                AuditRecord("pnj_current", "2011-07-06", "2026-07-07", "current_leak", 20),
                AuditRecord("pnj_current", "2013-11-18", "2026-07-07", "current_leak", 20),
            ]
        )
        self.assertEqual(registry[0].status, STATUS_CURRENT_ONLY)
        self.assertFalse(registry[0].supports_historical)

    def test_matching_source_can_be_historical_valid(self):
        registry = build_registry_from_audit(
            [
                AuditRecord("sjc_official_history", "2011-07-06", "2011-07-06", "matched", 1),
                AuditRecord("sjc_official_history", "2013-11-18", "2013-11-18", "matched", 1),
            ]
        )
        self.assertEqual(registry[0].status, STATUS_HISTORICAL_VALID)
        self.assertTrue(registry[0].supports_historical)

    def test_business_date_uses_vietnam_date_from_timestamp(self):
        record = GoldPriceRecord(
            source="sjc_official",
            provider="SJC",
            branch="HCM",
            gold_type="SJC",
            buy_value=1.0,
            sell_value=2.0,
            unit="VND/lÆ°á»£ng",
            currency="VND",
            observed_at="2011-07-05T17:00:00+00:00",
            reference_date="2011-07-06",
            raw_payload_hash="hash",
            metadata={},
        )
        self.assertEqual(business_date_from_record(record), "2011-07-06")
        self.assertIsNotNone(gold_record_to_target_row(record, "2011-07-06", "sjc_official_history"))
        self.assertIsNone(gold_record_to_target_row(record, "2011-07-07", "sjc_official_history"))


if __name__ == "__main__":
    unittest.main()

