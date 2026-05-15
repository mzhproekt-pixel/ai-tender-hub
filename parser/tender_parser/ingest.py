"""Запись tender + lot в SQLite из любого источника."""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select

from .db import Lot, Tender, make_session
from .sources.goszakup import FetchedLot

log = logging.getLogger(__name__)


def save_lots(items: Iterable[FetchedLot], engine=None, batch_size: int = 500) -> tuple[int, int]:
    """Возвращает (tenders_upserted, lots_upserted)."""
    Session = make_session(engine)
    tn = 0
    ln = 0
    with Session() as session:
        cache: dict[tuple[str, str], int] = {}
        for i, it in enumerate(items, 1):
            tkey = (it.tender["source"], it.tender["external_id"])
            tid = cache.get(tkey)
            if tid is None:
                existing = session.execute(
                    select(Tender).where(
                        Tender.source == tkey[0],
                        Tender.external_id == tkey[1],
                    )
                ).scalar_one_or_none()
                if existing:
                    for k, v in it.tender.items():
                        if v is not None:
                            setattr(existing, k, v)
                    tid = existing.id
                else:
                    t = Tender(**it.tender)
                    session.add(t)
                    session.flush()
                    tid = t.id
                    tn += 1
                cache[tkey] = tid

            lot_payload = dict(it.lot)
            lot_payload["tender_id"] = tid
            existing_lot = session.execute(
                select(Lot).where(
                    Lot.tender_id == tid,
                    Lot.external_id == lot_payload["external_id"],
                )
            ).scalar_one_or_none()
            if existing_lot:
                for k, v in lot_payload.items():
                    if v is not None:
                        setattr(existing_lot, k, v)
            else:
                session.add(Lot(**lot_payload))
                ln += 1

            if i % batch_size == 0:
                session.commit()
                log.info("committed %d items (tenders=%d, lots=%d)", i, tn, ln)
        session.commit()
    return tn, ln
