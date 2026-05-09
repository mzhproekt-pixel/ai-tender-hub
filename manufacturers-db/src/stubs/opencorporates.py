"""OpenCorporates — STUB.

API: https://api.opencorporates.com/
Auth: API token (free tier limited to ~500 calls/mo; paid tiers higher).
Useful endpoints:
  GET /companies/search?q={name}&jurisdiction_code={code}
  GET /companies/{jurisdiction_code}/{company_number}

Provides: 200M+ company records across ~140 jurisdictions, with cross-links.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..connectors.base import BaseConnector


class OpenCorporatesConnector(BaseConnector):
    source = "opencorporates"

    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        raise NotImplementedError("OpenCorporates connector — implement in next sprint")
