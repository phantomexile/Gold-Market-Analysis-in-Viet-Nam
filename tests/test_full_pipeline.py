from __future__ import annotations

import bootstrap  # noqa: F401

import tempfile
import unittest
from pathlib import Path

from gold_collectors.full_pipeline import (
    DataLakeWriter,
    SourceResult,
    date_range,
    run_quality_checks,
)


class FullPipelineUtilityTests(unittest.TestCase):
    def test_date_range_inclusive(self):
        self.assertEqual(date_range("2026-07-01", "2026-07-03"), ["2026-07-01", "2026-07-02", "2026-07-03"])

    def test_writer_creates_manifest_and_csv_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = DataLakeWriter(tmp, formats=["csv"])
            writer.write_dataset("events", [{"event_date": "2026-01-01", "event_type": "test"}])
            writer.write_manifest([SourceResult("manual_policy_events", "events", "ok", 1, "events")])
            self.assertTrue((Path(tmp) / "normalized" / "events.csv").exists())
            self.assertTrue((Path(tmp) / "manifests" / "source_manifest.json").exists())

    def test_quality_check_flags_empty_dataset(self):
        issues = run_quality_checks({"gold_prices": []})
        self.assertTrue(any(issue.dataset == "gold_prices" and issue.check == "non_empty" for issue in issues))

if __name__ == "__main__":
    unittest.main()

