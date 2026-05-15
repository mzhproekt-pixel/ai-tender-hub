"""Парсер zakup.sk.kz (Самрук-Казына).

Портал публикует открытые данные через REST. Используется
endpoint объявлений `/api/v1/announce/announces/search` (POST).
Формат ответа может меняться — поля защищены `.get()` с None.

Если структура API изменилась — поправьте `_map_announce` и
`_map_lot` ниже.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterator

from dateutil.parser import isoparse

from ..config import settings
from ..http_client import make_client, post_json
from .goszakup import FetchedLot

log = logging.getLogger(__name__)


class SamrukClient:
    def __init__(self):
        self.client = make_client(base_url=settings.samruk_base)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "SamrukClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_lots(
        self,
        date_from: str,
        date_to: str,
        page_size: int = 100,
    ) -> Iterator[FetchedLot]:
        offset = 0
        while True:
            payload = {
                "filter": {
                    "publishDateFrom": date_from,
                    "publishDateTo": date_to,
                },
                "size": page_size,
                "from": offset,
            }
            try:
                data = post_json(
                    self.client,
                    "/api/v1/announce/announces/search",
                    payload,
                )
            except Exception as e:
                log.error("samruk fetch failed at offset=%d: %s", offset, e)
                return
            items = (data.get("content") or data.get("items") or data.get("hits") or [])
            if not items:
                return
            for ann in items:
                tender = _map_announce(ann)
                for lot in ann.get("lots") or ann.get("lotList") or []:
                    yield FetchedLot(tender=tender, lot=_map_lot(lot))
            offset += len(items)
            if len(items) < page_size:
                return


def _map_announce(a: dict) -> dict:
    return {
        "source": "samruk",
        "external_id": str(a.get("id") or a.get("announceId") or ""),
        "number_anno": a.get("number") or a.get("numberAnno"),
        "name": a.get("nameRu") or a.get("name"),
        "customer_bin": a.get("customerBin") or a.get("organizerBin"),
        "customer_name": a.get("customerNameRu") or a.get("organizerNameRu"),
        "method": a.get("methodNameRu") or a.get("methodName"),
        "status": a.get("statusNameRu") or a.get("statusName"),
        "total_sum": a.get("totalSum"),
        "publish_date": _parse_dt(a.get("publishDate")),
        "end_date": _parse_dt(a.get("endDate")),
        "raw_url": _ann_url(a.get("id")),
    }


def _map_lot(l: dict) -> dict:
    return {
        "external_id": str(l.get("id") or l.get("lotId") or ""),
        "number": l.get("number") or l.get("lotNumber"),
        "name": l.get("nameRu") or l.get("name"),
        "description": l.get("descriptionRu") or l.get("description"),
        "ktru_code": l.get("ktruCode") or l.get("kruCode"),
        "quantity": l.get("count") or l.get("quantity"),
        "unit": l.get("unitNameRu") or l.get("unit"),
        "price_per_unit": l.get("price") or l.get("unitPrice"),
        "total_sum": l.get("sum") or l.get("totalSum"),
        "country_origin": l.get("countryOrigin"),
        "status": l.get("statusNameRu") or l.get("status"),
        "winner_bin": l.get("winnerBin") or (l.get("winner") or {}).get("bin"),
        "winner_name": l.get("winnerNameRu") or (l.get("winner") or {}).get("name"),
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return isoparse(value)
    except (ValueError, TypeError):
        return None


def _ann_url(ann_id) -> str | None:
    if not ann_id:
        return None
    return f"https://zakup.sk.kz/#/ext/announce/{ann_id}"
