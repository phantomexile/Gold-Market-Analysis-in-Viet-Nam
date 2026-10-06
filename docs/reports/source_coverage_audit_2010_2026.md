# Source Coverage Audit 2010-2026

Run date: 2026-07-07

This audit was added after tightening the definition of "crawl success". A source is not considered historically useful just because it returns a response; it must return data over a meaningful historical range.

## Audit Results

| Source | Status | Records | Covered dates | Range | Covered years | Notes |
|---|---|---:|---:|---|---:|---|
| SJC official historical | `ok_sampled` | 595 accepted sampled dates | 595 | `2010-01-01..2026-07-01` | 17 | Sampled 1st/15th/28th of each month. Exact daily full backfill already verified for 2010 and 2011. |
| SBV central USD/VND | `ok` | 3,940 | 3,940 | `2011-07-06..2026-07-06` | 16 | Official central FX history. |
| yfinance market | `ok` | 29,201 | 4,303 | `2010-01-04..2026-07-07` | 17 | `GC=F`, `USDVND=X`, `^VIX`, `DX-Y.NYB`, `^GSPC`, `CL=F`, `SI=F`. |
| FRED windowed CSV | `ok` | 16,551 | 4,201 | `2010-01-04..2026-07-03` | 17 | `DGS10`, `DCOILWTICO`, `VIXCLS`, `DTWEXBGS`. |
| World Bank Vietnam macro | `ok` | 264 | 66 annual dates | `1960..2025` | 66 | Annual baseline indicators. |
| GSO macro-monitor | `ok` | 30,840 | 307 period dates | `1986-12-31..2025-04-01` | 40 | Vietnam macro archive. |
| vnstock VNINDEX VCI | `ok` | 4,309 | 4,309 | `2009-03-31..2026-07-06` | 18 | VN equity market feature. |
| VCB date API sample | `partial_recent` | 12 accepted sampled dates | 12 | `2020-07-15..2026-01-15` | 7 | Older 2010-2019 sampled dates are not accepted. |

## Important Caveats

- SJC exact daily coverage has been fully tested for 2010 and 2011. For 2012-2026, the audit currently proves sampled month-level historical availability, not a full daily backfill.
- VCB is not a long historical FX source for 2010-2019 in this environment. Old sampled dates were empty or failed the `payload.Date == requested_date` rule.
- GSO and World Bank are macro frequency sources, so their "covered dates" are period dates, not daily observations.
- yfinance and FRED are trading-day/business-day sources, so they naturally do not cover every calendar date.

## Reproduction Notes

This report is retained as historical evidence from the source-selection phase. The current repo keeps only the production pipeline commands:

```powershell
python scripts/pipeline/source_audit.py --out-dir data/experiments/audit_output
python scripts/pipeline/build_source_registry.py --audit-json data/experiments/audit_output/source_audit.json
python scripts/pipeline/backfill_target.py --from 2011-07-06 --to 2026-07-06 --out-dir data/lake/audited
python scripts/pipeline/collect_external_features.py --from 2011-07-06 --to 2026-07-06 --out-dir data/lake/external_features
```

SBV full historical coverage was verified directly through `collect_sbv_central_fx_history('2011-07-06', '2026-07-06')`.
