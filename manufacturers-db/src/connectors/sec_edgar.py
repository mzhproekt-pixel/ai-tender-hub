"""SEC EDGAR submissions.

Strategy:
  1. Pull the master CIK lookup at https://www.sec.gov/files/company_tickers.json
     (every public-filer CIK + ticker + name, ~10K rows).
  2. For each CIK, fetch
     https://data.sec.gov/submissions/CIK{cik:010d}.json
     which carries name, addresses, SIC, EIN, etc.

SEC requires a contact email in the User-Agent (set HTTP_USER_AGENT).
Rate limit: 10 req/s — we throttle conservatively.
"""
from __future__ import annotations

import time
from typing import Any, Iterator

from .base import BaseConnector

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class SecEdgarConnector(BaseConnector):
    source = "sec_edgar"

    def fetch(
        self,
        *,
        limit: int | None = 100,
        sleep_s: float = 0.12,    # ~8 rps, safely under SEC's 10 rps limit
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        tickers = self.get_json(TICKERS_URL)
        # company_tickers.json is a dict keyed by string indices, values are
        # {cik_str, ticker, title}.
        items = list(tickers.values()) if isinstance(tickers, dict) else tickers
        seen = 0
        for item in items:
            cik = str(item.get("cik_str") or item.get("cik") or "").strip()
            if not cik:
                continue
            cik_padded = cik.zfill(10)
            try:
                payload = self.get_json(SUBMISSIONS_URL.format(cik=cik_padded))
            except Exception:
                continue
            yield cik_padded, payload
            seen += 1
            if limit and seen >= limit:
                return
            time.sleep(sleep_s)
