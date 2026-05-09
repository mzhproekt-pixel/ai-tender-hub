"""Runtime configuration loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val if val not in (None, "") else None


@dataclass(frozen=True)
class Settings:
    pg_host: str = _env("POSTGRES_HOST", "localhost")
    pg_port: int = int(_env("POSTGRES_PORT", "5432"))
    pg_db: str = _env("POSTGRES_DB", "manufacturers")
    pg_user: str = _env("POSTGRES_USER", "mdb")
    pg_password: str = _env("POSTGRES_PASSWORD", "mdb")

    http_user_agent: str = _env(
        "HTTP_USER_AGENT",
        "manufacturers-db/0.1 (set HTTP_USER_AGENT env)",
    )
    http_timeout: int = int(_env("HTTP_TIMEOUT", "30"))
    http_retries: int = int(_env("HTTP_RETRIES", "3"))

    export_dir: Path = Path(_env("EXPORT_DIR", "./exports")).resolve()

    companies_house_api_key: str | None = _env("COMPANIES_HOUSE_API_KEY")
    opencorporates_api_key: str | None = _env("OPENCORPORATES_API_KEY")
    un_comtrade_key: str | None = _env("UN_COMTRADE_KEY")

    @property
    def dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


settings = Settings()
