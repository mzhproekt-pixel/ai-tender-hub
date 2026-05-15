"""КТРУ-классификатор + сверка с реестром индустриальных сертификатов СТ-KZ.

Логика «импортный = кандидат на локализацию»:
  1. У лота должен быть код КТРУ (товар, не услуга).
  2. По этому коду КТРУ НЕТ действующего сертификата СТ-KZ
     в реестре qaztrade.org.kz (т.е. казахстанского производителя нет).
  3. Дополнительно используется поле `country_origin` лота: если страна
     указана и она != KZ, лот гарантированно импортный.

Реестр СТ-KZ загружается одним батчем (CSV/JSON) и кладётся в таблицу
`st_kz_certificates`. Источник реестра — open data qaztrade.org.kz;
если эндпоинт сменился, переопределите `ST_KZ_REGISTRY` через env.
"""

from __future__ import annotations

import logging
from datetime import datetime

from dateutil.parser import isoparse
from sqlalchemy import select

from .config import settings
from .db import KtruItem, Lot, StKzCertificate, make_session
from .http_client import get_json, make_client

log = logging.getLogger(__name__)


def load_st_kz_registry(engine=None) -> int:
    """Скачать реестр СТ-KZ и положить в БД.

    Ожидается JSON-массив с полями certificate_no, producer_bin, producer_name,
    ktru_code, product_name, valid_from, valid_to, local_content_pct.
    """
    with make_client() as client:
        data = get_json(client, settings.st_kz_registry_url)
    items = data if isinstance(data, list) else data.get("items") or data.get("data") or []

    Session = make_session(engine)
    n = 0
    with Session() as session:
        for it in items:
            cert_no = str(it.get("certificate_no") or it.get("number") or "").strip()
            if not cert_no:
                continue
            existing = session.execute(
                select(StKzCertificate).where(StKzCertificate.certificate_no == cert_no)
            ).scalar_one_or_none()
            payload = dict(
                certificate_no=cert_no,
                producer_bin=str(it.get("producer_bin") or it.get("bin") or ""),
                producer_name=it.get("producer_name") or it.get("name"),
                ktru_code=it.get("ktru_code") or it.get("ktru"),
                product_name=it.get("product_name") or it.get("product"),
                valid_from=_dt(it.get("valid_from")),
                valid_to=_dt(it.get("valid_to")),
                local_content_pct=_to_float(it.get("local_content_pct") or it.get("local_content")),
            )
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                session.add(StKzCertificate(**payload))
            n += 1
        session.commit()
    log.info("loaded %d ST-KZ certificates", n)
    return n


def mark_localization_candidates(engine=None, as_of: datetime | None = None) -> int:
    """Проставить Lot.is_st_kz_available для всех лотов с известным ktru_code."""
    as_of = as_of or datetime.utcnow()
    Session = make_session(engine)
    updated = 0
    with Session() as session:
        # Все коды КТРУ, по которым есть хотя бы один действующий сертификат
        active_codes = set(
            session.execute(
                select(StKzCertificate.ktru_code).where(
                    StKzCertificate.ktru_code.is_not(None),
                    (StKzCertificate.valid_to.is_(None)) | (StKzCertificate.valid_to >= as_of),
                )
            ).scalars()
        )
        lots = session.execute(select(Lot).where(Lot.ktru_code.is_not(None))).scalars().all()
        for lot in lots:
            lot.is_st_kz_available = lot.ktru_code in active_codes
            updated += 1
        session.commit()
    log.info("annotated %d lots with ST-KZ availability flag", updated)
    return updated


def _dt(v):
    if not v:
        return None
    try:
        return isoparse(str(v))
    except (ValueError, TypeError):
        return None


def _to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
