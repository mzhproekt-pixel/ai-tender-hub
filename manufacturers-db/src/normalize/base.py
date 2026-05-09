"""Base class for per-source normalisers.

A normaliser walks entity_sources rows for one source and projects facets
(name, country, addresses, identifiers, contacts...) into the typed tables.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..db import connect


class BaseNormalizer(ABC):
    source: str  # subclass sets this

    @abstractmethod
    def project(self, cur, entity_id: int, raw: dict[str, Any]) -> None:
        """Write facets derived from `raw` into typed tables for `entity_id`."""

    def run(self, *, batch: int = 1000) -> int:
        """Iterate all source rows for this source and project them. Returns count."""
        seen = 0
        with connect() as conn, conn.cursor(name=f"norm_{self.source}") as cur:
            cur.itersize = batch
            cur.execute(
                "SELECT entity_id, raw FROM entity_sources WHERE source = %s",
                (self.source,),
            )
            with conn.cursor() as wcur:
                for entity_id, raw in cur:
                    self.project(wcur, entity_id, raw)
                    seen += 1
                    if seen % batch == 0:
                        conn.commit()
                conn.commit()
        return seen
