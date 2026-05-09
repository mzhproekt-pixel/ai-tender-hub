"""Base class for ingestion connectors.

Each connector pulls records from one source, persists raw payloads to
entity_sources, and tracks the run in ingestion_runs. Per-source projection to
typed tables is the normaliser's job (run separately).
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Iterator

import httpx

from ..db import connect, finish_run, start_run, upsert_source_record
from ..settings import settings

log = logging.getLogger(__name__)


class BaseConnector(ABC):
    source: str  # subclass sets this

    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": settings.http_user_agent, "Accept": "application/json"},
            timeout=settings.http_timeout,
            follow_redirects=True,
        )

    # ---- subclass hooks --------------------------------------------------

    @abstractmethod
    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        """Yield (source_ref, raw_payload) tuples."""

    # ---- shared helpers --------------------------------------------------

    def get_json(self, url: str, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(settings.http_retries + 1):
            try:
                resp = self.client.get(url, **kwargs)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "2"))
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt >= settings.http_retries:
                    break
                time.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc

    # ---- run loop --------------------------------------------------------

    def run(self, **params: Any) -> dict[str, int]:
        run_id = start_run(self.source, params)
        rows_in = rows_up = 0
        try:
            with connect() as conn, conn.cursor() as cur:
                for source_ref, raw in self.fetch(**params):
                    rows_in += 1
                    upsert_source_record(
                        cur,
                        source=self.source,
                        source_ref=source_ref,
                        raw=raw,
                        run_id=run_id,
                    )
                    rows_up += 1
                    if rows_up % 200 == 0:
                        conn.commit()
                conn.commit()
            finish_run(run_id, status="ok", rows_in=rows_in, rows_upserted=rows_up)
        except Exception as exc:  # noqa: BLE001 — record any failure, then re-raise
            finish_run(run_id, status="error", rows_in=rows_in, rows_upserted=rows_up, error=str(exc)[:1000])
            raise
        return {"run_id": run_id, "rows_in": rows_in, "rows_upserted": rows_up}

    def close(self) -> None:
        self.client.close()
