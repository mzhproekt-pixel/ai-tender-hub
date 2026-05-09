"""Database helpers: connection, schema bootstrap, upsert primitives."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Json

from .settings import settings

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


@contextmanager
def connect():
    with psycopg.connect(settings.dsn) as conn:
        yield conn


def init_db() -> None:
    """Apply the canonical schema. Idempotent."""
    schema = (SQL_DIR / "001_schema.sql").read_text(encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(schema)
        conn.commit()


def start_run(source: str, params: dict[str, Any] | None = None) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_runs(source, params) VALUES (%s, %s) RETURNING id",
            (source, Json(params or {})),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
        return run_id


def finish_run(run_id: int, *, status: str, rows_in: int, rows_upserted: int, error: str | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_runs
               SET finished_at = now(),
                   status      = %s,
                   rows_in     = %s,
                   rows_upserted = %s,
                   error       = %s
             WHERE id = %s
            """,
            (status, rows_in, rows_upserted, error, run_id),
        )
        conn.commit()


def upsert_source_record(
    cur,
    *,
    source: str,
    source_ref: str,
    raw: dict[str, Any],
    run_id: int | None,
) -> int:
    """Insert/update entity_sources row, return entity_id (creating an empty entity if needed)."""
    cur.execute(
        "SELECT entity_id FROM entity_sources WHERE source = %s AND source_ref = %s",
        (source, source_ref),
    )
    row = cur.fetchone()
    if row:
        entity_id = row[0]
        cur.execute(
            "UPDATE entity_sources SET raw = %s, fetched_at = now(), run_id = %s "
            "WHERE source = %s AND source_ref = %s",
            (Json(raw), run_id, source, source_ref),
        )
        return entity_id

    cur.execute("INSERT INTO entities DEFAULT VALUES RETURNING id")
    entity_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO entity_sources(entity_id, source, source_ref, raw, run_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (entity_id, source, source_ref, Json(raw), run_id),
    )
    return entity_id


def upsert_identifier(cur, entity_id: int, scheme: str, value: str, source: str) -> None:
    cur.execute(
        """
        INSERT INTO entity_identifiers(entity_id, scheme, value, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (scheme, value) DO NOTHING
        """,
        (entity_id, scheme, value, source),
    )
