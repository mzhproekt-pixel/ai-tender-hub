"""CSV exports backed by SQL files in sql/exports/."""
from __future__ import annotations

from pathlib import Path

from ..db import connect
from ..settings import settings

EXPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "sql" / "exports"


def list_exports() -> list[str]:
    return sorted(p.stem for p in EXPORTS_DIR.glob("*.sql"))


def export_to_csv(name: str) -> Path:
    sql_path = EXPORTS_DIR / f"{name}.sql"
    if not sql_path.exists():
        raise FileNotFoundError(f"unknown export: {name} (looked at {sql_path})")
    sql = sql_path.read_text(encoding="utf-8")

    settings.export_dir.mkdir(parents=True, exist_ok=True)
    out = settings.export_dir / f"{name}.csv"

    copy_sql = f"COPY ({sql.rstrip().rstrip(';')}) TO STDOUT WITH (FORMAT csv, HEADER true)"
    with connect() as conn, conn.cursor() as cur, out.open("wb") as f:
        with cur.copy(copy_sql) as copy:
            for chunk in copy:
                f.write(chunk)
    return out
