from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    goszakup_token: str | None
    goszakup_rest_base: str
    goszakup_graphql: str
    samruk_base: str
    st_kz_registry_url: str
    http_timeout: float
    user_agent: str

    @classmethod
    def from_env(cls) -> "Settings":
        # Якоримся на корень пакета (parser/), чтобы БД жила в одном месте
        # независимо от cwd запуска.
        pkg_root = Path(__file__).resolve().parent.parent
        root = Path(os.getenv("TENDER_PARSER_HOME", pkg_root)).resolve()
        return cls(
            db_path=Path(os.getenv("TENDER_PARSER_DB", root / "data" / "tenders.sqlite")),
            goszakup_token=os.getenv("GOSZAKUP_TOKEN"),
            goszakup_rest_base=os.getenv("GOSZAKUP_REST", "https://ows.goszakup.gov.kz/v3"),
            goszakup_graphql=os.getenv("GOSZAKUP_GRAPHQL", "https://ows.goszakup.gov.kz/v3/graphql"),
            samruk_base=os.getenv("SAMRUK_BASE", "https://zakup.sk.kz"),
            st_kz_registry_url=os.getenv(
                "ST_KZ_REGISTRY",
                "https://www.qaztrade.org.kz/api/registry/st-kz",
            ),
            http_timeout=float(os.getenv("HTTP_TIMEOUT", "30")),
            user_agent=os.getenv(
                "HTTP_USER_AGENT",
                "ai-tender-hub-parser/0.1 (+research)",
            ),
        )


settings = Settings.from_env()
