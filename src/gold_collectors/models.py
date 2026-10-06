from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GoldPriceRecord:
    source: str
    provider: str
    branch: str | None
    gold_type: str
    buy_value: float | None
    sell_value: float | None
    unit: str
    currency: str
    observed_at: str | None
    reference_date: str | None
    raw_payload_hash: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
