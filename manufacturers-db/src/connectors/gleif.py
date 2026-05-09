"""GLEIF level-1 LEI Records.

API: https://api.gleif.org/api/v1/lei-records
Anonymous, JSON:API style, ~50 records/page, no key required.
"""
from __future__ import annotations

from typing import Any, Iterator

from .base import BaseConnector

API = "https://api.gleif.org/api/v1/lei-records"


class GleifConnector(BaseConnector):
    source = "gleif"

    def fetch(
        self,
        *,
        country: str | None = None,
        legal_form: str | None = None,
        limit: int | None = 1000,
        page_size: int = 200,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        params: dict[str, Any] = {"page[size]": page_size, "page[number]": 1}
        if country:
            params["filter[entity.legalAddress.country]"] = country.upper()
        if legal_form:
            params["filter[entity.legalForm]"] = legal_form

        seen = 0
        while True:
            data = self.get_json(API, params=params)
            records = data.get("data", []) or []
            if not records:
                return
            for rec in records:
                lei = (rec.get("attributes") or {}).get("lei")
                if not lei:
                    continue
                yield lei, rec
                seen += 1
                if limit and seen >= limit:
                    return
            next_link = (data.get("links") or {}).get("next")
            if not next_link:
                return
            params["page[number]"] += 1
