from __future__ import annotations

import json
from typing import Any

from .http import CachedHttpClient
from .models import GoldPriceRecord
from .parsing import (
    extract_table_rows,
    normalize_date,
    normalize_webgia_date,
    parse_dotnet_date,
    parse_number,
)


class SjcOfficialCollector:
    source = "sjc_official"
    provider = "SJC"
    endpoint = "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx"

    def __init__(self, http: CachedHttpClient | None = None):
        self.http = http or CachedHttpClient()

    def get_current_catalog(self) -> list[GoldPriceRecord]:
        response = self.http.post_form(self.endpoint, {"method": "GetCurrentGoldPrice"})
        payload = json.loads(response.text)
        return [self._record_from_item(item, response.raw_payload_hash, None) for item in payload.get("data", [])]

    def get_price_by_date(self, value: str) -> list[GoldPriceRecord]:
        ddmmyyyy, iso_date = normalize_date(value)
        response = self.http.post_form(
            self.endpoint,
            {"method": "GetSJCGoldPriceByDate", "toDate": ddmmyyyy},
        )
        payload = json.loads(response.text)
        return [self._record_from_item(item, response.raw_payload_hash, iso_date) for item in payload.get("data", [])]

    def get_history(self, gold_price_id: int, from_date: str, to_date: str) -> list[GoldPriceRecord]:
        from_ddmmyyyy, from_iso = normalize_date(from_date)
        to_ddmmyyyy, to_iso = normalize_date(to_date)
        response = self.http.post_form(
            self.endpoint,
            {
                "method": "GetGoldPriceHistory",
                "goldPriceId": gold_price_id,
                "fromDate": from_ddmmyyyy,
                "toDate": to_ddmmyyyy,
            },
        )
        payload = json.loads(response.text)
        reference_date = from_iso if from_iso == to_iso else f"{from_iso}/{to_iso}"
        return [self._record_from_item(item, response.raw_payload_hash, reference_date) for item in payload.get("data", [])]

    def _record_from_item(
        self,
        item: dict[str, Any],
        raw_payload_hash: str,
        reference_date: str | None,
    ) -> GoldPriceRecord:
        return GoldPriceRecord(
            source=self.source,
            provider=self.provider,
            branch=item.get("BranchName"),
            gold_type=item.get("TypeName") or "",
            buy_value=parse_number(item.get("BuyValue")),
            sell_value=parse_number(item.get("SellValue")),
            unit="VND/lượng",
            currency="VND",
            observed_at=parse_dotnet_date(item.get("GroupDate")),
            reference_date=reference_date,
            raw_payload_hash=raw_payload_hash,
            metadata={
                "id": item.get("Id"),
                "buy_display": item.get("Buy"),
                "sell_display": item.get("Sell"),
                "raw_group_date": item.get("GroupDate"),
                "buy_differ": item.get("BuyDiffer"),
                "sell_differ": item.get("SellDiffer"),
            },
        )


class PnjCurrentCollector:
    source = "pnj_official_current"
    provider = "PNJ"
    endpoint = "https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price"

    def __init__(self, http: CachedHttpClient | None = None):
        self.http = http or CachedHttpClient()

    def get_current(self, zone: str = "00") -> list[GoldPriceRecord]:
        response = self.http.get(f"{self.endpoint}?zone={zone}")
        payload = json.loads(response.text)
        branch = payload.get("chinhanh") or zone
        reference_date = payload.get("updateDate")
        return [
            GoldPriceRecord(
                source=self.source,
                provider=self.provider,
                branch=branch,
                gold_type=item.get("tensp") or item.get("masp") or "",
                buy_value=parse_number(item.get("giamua")),
                sell_value=parse_number(item.get("giaban")),
                unit="1,000 VND/chỉ",
                currency="VND",
                observed_at=reference_date,
                reference_date=reference_date,
                raw_payload_hash=response.raw_payload_hash,
                metadata={
                    "product_code": item.get("masp"),
                    "zone": zone,
                    "note": item.get("note") or payload.get("note"),
                    "historical_capable": False,
                },
            )
            for item in payload.get("data", [])
        ]


class DojiCurrentHtmlCollector:
    source = "doji_official_current_html"
    provider = "DOJI"
    endpoint = "https://giavang.doji.vn/"

    def __init__(self, http: CachedHttpClient | None = None):
        self.http = http or CachedHttpClient()

    def get_current(self) -> list[GoldPriceRecord]:
        response = self.http.get(self.endpoint)
        rows = extract_table_rows(response.text)
        records: list[GoldPriceRecord] = []
        for row in rows:
            if len(row) < 3:
                continue
            if row[0].lower() in {"giá vàng trong nước", "loại"}:
                continue
            buy = parse_number(row[1])
            sell = parse_number(row[2])
            if buy is None and sell is None:
                continue
            records.append(
                GoldPriceRecord(
                    source=self.source,
                    provider=self.provider,
                    branch=None,
                    gold_type=row[0],
                    buy_value=buy,
                    sell_value=sell,
                    unit="1,000 VND/chỉ",
                    currency="VND",
                    observed_at=None,
                    reference_date=None,
                    raw_payload_hash=response.raw_payload_hash,
                    metadata={"fragile": True, "historical_capable": False},
                )
            )
        return records


class ThirdPartyArchiveCollector:
    source = "webgia_archive"
    provider = "WebGia"
    sjc_url_template = "https://webgia.com/gia-vang/sjc/{date}.html"

    def __init__(self, http: CachedHttpClient | None = None):
        self.http = http or CachedHttpClient()

    def get_webgia_sjc_history(self, value: str) -> list[GoldPriceRecord]:
        ddmmyyyy_dash, iso_date = normalize_webgia_date(value)
        response = self.http.get(self.sjc_url_template.format(date=ddmmyyyy_dash))
        rows = extract_table_rows(response.text)
        records: list[GoldPriceRecord] = []
        for row in rows:
            if len(row) < 4 or not row[0].isdigit():
                continue
            records.append(
                GoldPriceRecord(
                    source=self.source,
                    provider=self.provider,
                    branch="Việt Nam",
                    gold_type="SJC 1 lượng",
                    buy_value=parse_number(row[2]) * 1_000_000 if parse_number(row[2]) is not None else None,
                    sell_value=parse_number(row[3]) * 1_000_000 if parse_number(row[3]) is not None else None,
                    unit="VND/lượng",
                    currency="VND",
                    observed_at=f"{iso_date}T{row[1]}:00+07:00",
                    reference_date=iso_date,
                    raw_payload_hash=response.raw_payload_hash,
                    metadata={"sequence": int(row[0]), "third_party": True},
                )
            )
        return records
