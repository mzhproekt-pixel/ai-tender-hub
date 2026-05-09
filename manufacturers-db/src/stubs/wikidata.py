"""Wikidata — STUB.

SPARQL endpoint: https://query.wikidata.org/sparql
Use SPARQL queries with `?company wdt:P31/wdt:P279* wd:Q4830453` (business)
plus filters by P17 (country), P452 (industry), P1448 (official name).

Provides: cross-links between LEI / ticker / VAT / Wikipedia / official site,
plus founders, CEO, headcount where available.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..connectors.base import BaseConnector


class WikidataConnector(BaseConnector):
    source = "wikidata"

    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        raise NotImplementedError("Wikidata connector — implement in next sprint")
