"""ЕГРЮЛ (RU) — STUB.

The Russian Federal Tax Service publishes daily ZIP archives of XML extracts
of the unified state register of legal entities (ЕГРЮЛ) at:
  https://egrul.itsoft.ru/   (mirror)
  https://www.nalog.gov.ru/opendata/  (official)

Provides: ОГРН, ИНН, КПП, наименование, адрес, виды деятельности, учредители.
Implementation needs: bulk download + XML stream parser (lxml.iterparse) +
incremental processing of daily diffs.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..connectors.base import BaseConnector


class EgrulConnector(BaseConnector):
    source = "egrul_ru"

    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        raise NotImplementedError("ЕГРЮЛ connector — implement in next sprint")
