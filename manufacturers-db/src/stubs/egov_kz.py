"""egov.kz / stat.gov.kz (KZ) — STUB.

Sources:
  https://stat.gov.kz/ru/api/  — registry of business entities (BIN, name, OKED)
  https://data.egov.kz/        — open data portal, plenty of CSV/JSON datasets

Provides: БИН/ИИН, наименование, ОКЭД, юр. адрес, статус.
Bulk CSV downloads are usually the right entry point.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..connectors.base import BaseConnector


class EgovKzConnector(BaseConnector):
    source = "egov_kz"

    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        raise NotImplementedError("egov.kz connector — implement in next sprint")
