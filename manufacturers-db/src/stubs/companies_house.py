"""Companies House (UK) — STUB.

API: https://api.company-information.service.gov.uk/
Auth: HTTP Basic with API key (free, register at developer.company-information.service.gov.uk).
Useful endpoints:
  GET /search/companies?q={name}
  GET /company/{company_number}
  GET /company/{company_number}/officers

Provides: company number (CRN), name, address, status, SIC codes, officers.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..connectors.base import BaseConnector


class CompaniesHouseConnector(BaseConnector):
    source = "companies_house"

    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        raise NotImplementedError("Companies House connector — implement in next sprint")
