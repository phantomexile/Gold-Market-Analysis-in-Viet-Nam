from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib import error, parse, request


class CollectorHttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    text: str
    raw_payload_hash: str
    from_cache: bool


class CachedHttpClient:
    """Small HTTP client with throttling, retries, and raw response caching."""

    def __init__(
        self,
        cache_dir: str | Path = ".cache/raw",
        timeout_seconds: int = 30,
        min_interval_seconds: float = 0.25,
        retries: int = 2,
        user_agent: str = "gold-data-collection-prototype/0.1",
    ):
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.retries = retries
        self.user_agent = user_agent
        self._last_request_at = 0.0
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, use_cache: bool = True) -> HttpResponse:
        return self._request("GET", url, None, use_cache)

    def post_form(self, url: str, data: Mapping[str, str | int], use_cache: bool = True) -> HttpResponse:
        encoded = parse.urlencode({k: str(v) for k, v in data.items()})
        return self._request("POST", url, encoded, use_cache)

    def _request(self, method: str, url: str, body: str | None, use_cache: bool) -> HttpResponse:
        cache_key = hashlib.sha256(f"{method}\n{url}\n{body or ''}".encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if use_cache and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return HttpResponse(
                url=cached["url"],
                status=cached["status"],
                text=cached["text"],
                raw_payload_hash=cached["raw_payload_hash"],
                from_cache=True,
            )

        payload = body.encode("utf-8") if body is not None else None
        headers = {"User-Agent": self.user_agent}
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                req = request.Request(url=url, data=payload, headers=headers, method=method)
                with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read()
                    text = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
                    raw_hash = hashlib.sha256(raw).hexdigest()
                    result = HttpResponse(
                        url=resp.geturl(),
                        status=resp.status,
                        text=text,
                        raw_payload_hash=raw_hash,
                        from_cache=False,
                    )
                    cache_path.write_text(json.dumps(result.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
                    return result
            except error.HTTPError as exc:
                body_text = exc.read().decode("utf-8", errors="replace")
                if 400 <= exc.code < 500:
                    raise CollectorHttpError(f"HTTP {exc.code} for {url}", status=exc.code, body=body_text) from exc
                last_error = exc
            except Exception as exc:  # noqa: BLE001 - keep network prototype resilient.
                last_error = exc

            if attempt < self.retries:
                time.sleep(0.75 * (2**attempt))

        raise CollectorHttpError(f"Request failed for {url}: {last_error}") from last_error

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_request_at = time.monotonic()
