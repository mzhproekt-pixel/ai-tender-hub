"""Аналитика: топ импорта и кандидаты на локализацию.

Импортным считается лот, у которого:
  - либо `country_origin` указан и != 'KZ',
  - либо по `ktru_code` НЕТ действующего сертификата СТ-KZ
    (`is_st_kz_available = false`).

Кандидат на локализацию — агрегат по КТРУ-коду:
суммарный объём закупок (KZT), число тендеров, число уникальных
заказчиков. Чем выше сумма и шире спрос — тем привлекательнее
для постройки/привлечения завода в Казахстане.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from .db import get_engine

log = logging.getLogger(__name__)

TOP_IMPORTS_SQL = """
WITH imp AS (
  SELECT
    l.ktru_code,
    l.name AS lot_name,
    l.country_origin,
    l.total_sum,
    l.is_st_kz_available,
    t.customer_bin,
    t.publish_date,
    t.source
  FROM lots l
  JOIN tenders t ON t.id = l.tender_id
  WHERE l.ktru_code IS NOT NULL
    AND l.total_sum IS NOT NULL
    AND (
      (l.country_origin IS NOT NULL AND UPPER(l.country_origin) != 'KZ')
      OR l.is_st_kz_available = 0
    )
    AND (:date_from IS NULL OR t.publish_date >= :date_from)
    AND (:date_to   IS NULL OR t.publish_date <= :date_to)
)
SELECT
  ktru_code,
  MIN(lot_name)                                  AS sample_name,
  COUNT(*)                                       AS lots_count,
  COUNT(DISTINCT customer_bin)                   AS customers_count,
  ROUND(SUM(total_sum), 2)                       AS total_kzt,
  ROUND(AVG(total_sum), 2)                       AS avg_lot_kzt,
  SUM(CASE WHEN is_st_kz_available = 0 THEN 1 ELSE 0 END) AS lots_no_st_kz,
  GROUP_CONCAT(DISTINCT country_origin)          AS origin_countries,
  GROUP_CONCAT(DISTINCT source)                  AS sources
FROM imp
GROUP BY ktru_code
ORDER BY total_kzt DESC
LIMIT :limit
"""


def top_imports(
    limit: int = 100,
    date_from: str | None = None,
    date_to: str | None = None,
    engine=None,
) -> pd.DataFrame:
    engine = engine or get_engine()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(TOP_IMPORTS_SQL),
            conn,
            params={"limit": limit, "date_from": date_from, "date_to": date_to},
        )
    return df


LOCALIZATION_CANDIDATES_SQL = """
WITH agg AS (
  SELECT
    l.ktru_code,
    MIN(l.name)                          AS sample_name,
    COUNT(DISTINCT t.id)                 AS tenders_count,
    COUNT(DISTINCT t.customer_bin)       AS customers_count,
    SUM(l.total_sum)                     AS total_kzt,
    SUM(CASE WHEN UPPER(COALESCE(l.country_origin,'')) != 'KZ'
             AND l.country_origin IS NOT NULL THEN l.total_sum ELSE 0 END) AS import_kzt,
    SUM(CASE WHEN l.is_st_kz_available = 0 THEN l.total_sum ELSE 0 END)    AS no_st_kz_kzt
  FROM lots l
  JOIN tenders t ON t.id = l.tender_id
  WHERE l.ktru_code IS NOT NULL
    AND (:date_from IS NULL OR t.publish_date >= :date_from)
    AND (:date_to   IS NULL OR t.publish_date <= :date_to)
  GROUP BY l.ktru_code
)
SELECT
  ktru_code,
  sample_name,
  tenders_count,
  customers_count,
  ROUND(total_kzt,  2)     AS total_kzt,
  ROUND(import_kzt, 2)     AS import_kzt,
  ROUND(no_st_kz_kzt, 2)   AS no_st_kz_kzt,
  CASE WHEN total_kzt > 0
       THEN ROUND(100.0 * import_kzt / total_kzt, 1) END AS import_share_pct,
  CASE WHEN total_kzt > 0
       THEN ROUND(100.0 * no_st_kz_kzt / total_kzt, 1) END AS no_st_kz_share_pct
FROM agg
WHERE total_kzt >= :min_kzt
  AND (import_kzt > 0 OR no_st_kz_kzt > 0)
ORDER BY import_kzt DESC, no_st_kz_kzt DESC
LIMIT :limit
"""


def localization_candidates(
    limit: int = 50,
    min_kzt: float = 100_000_000,  # 100 млн тенге — фильтр шума
    date_from: str | None = None,
    date_to: str | None = None,
    engine=None,
) -> pd.DataFrame:
    """Топ КТРУ-кодов, по которым в РК нет производства, а закупки большие."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(LOCALIZATION_CANDIDATES_SQL),
            conn,
            params={
                "limit": limit,
                "min_kzt": min_kzt,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
    return df


def export_csv(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
