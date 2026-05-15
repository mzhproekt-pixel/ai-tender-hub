"""Парсер goszakup.gov.kz (госзакупки РК).

Использует публичный GraphQL endpoint v3 (ows.goszakup.gov.kz/v3/graphql).
Для большинства корневых типов (TrdBuy, Lots, Contract) нужен Bearer-токен,
который выдаётся бесплатно после регистрации в кабинете поставщика.
Токен берётся из env GOSZAKUP_TOKEN.

Документация API: https://goszakup.gov.kz/ru/egzopendata/index
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from dateutil.parser import isoparse

from ..config import settings
from ..http_client import make_client, post_json

log = logging.getLogger(__name__)

# Постранично выгружаем лоты с раскрытием объявления.
# `after` — курсор последнего полученного `id` (пагинация cursor-based).
LOTS_QUERY = """
query Lots($from: String, $to: String, $after: Int, $limit: Int) {
  Lots(
    filter: { lastUpdateDate: { from: $from, to: $to } }
    after: $after
    limit: $limit
  ) {
    id
    lotNumber
    nameRu
    descriptionRu
    count
    amount
    refTradeMethodsId
    refLotsStatusId
    customerBin
    customerNameRu
    trdBuyId
    refCountriesIso
    ktruCode
    TrdBuy {
      id
      numberAnno
      nameRu
      orgBin
      orgNameRu
      totalSum
      publishDate
      endDate
      refTradeMethodsId
      refBuyStatusId
    }
    Contract {
      contractSumWnds
      supplierBiin
      supplierNameRu
    }
  }
}
"""


@dataclass(slots=True)
class FetchedLot:
    tender: dict
    lot: dict


class GoszakupClient:
    def __init__(self, token: str | None = None):
        self.token = token or settings.goszakup_token
        if not self.token:
            log.warning(
                "GOSZAKUP_TOKEN не задан — GraphQL вернёт ошибку. "
                "Получите токен в кабинете поставщика goszakup.gov.kz."
            )
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client = make_client(headers=headers)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "GoszakupClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_lots(
        self,
        date_from: str,
        date_to: str,
        page_size: int = 200,
    ) -> Iterator[FetchedLot]:
        """Итерирует все лоты в диапазоне дат (ISO yyyy-mm-dd)."""
        after: int | None = None
        while True:
            data = post_json(
                self.client,
                settings.goszakup_graphql,
                {
                    "query": LOTS_QUERY,
                    "variables": {
                        "from": date_from,
                        "to": date_to,
                        "after": after,
                        "limit": page_size,
                    },
                },
            )
            if "errors" in data:
                raise RuntimeError(f"goszakup graphql errors: {data['errors']}")
            lots = data.get("data", {}).get("Lots") or []
            if not lots:
                return
            for lot in lots:
                trd = lot.get("TrdBuy") or {}
                contract = lot.get("Contract") or {}
                yield FetchedLot(
                    tender={
                        "source": "goszakup",
                        "external_id": str(trd.get("id") or lot.get("trdBuyId") or ""),
                        "number_anno": trd.get("numberAnno"),
                        "name": trd.get("nameRu"),
                        "customer_bin": trd.get("orgBin") or lot.get("customerBin"),
                        "customer_name": trd.get("orgNameRu") or lot.get("customerNameRu"),
                        "method": str(trd.get("refTradeMethodsId") or ""),
                        "status": str(trd.get("refBuyStatusId") or ""),
                        "total_sum": trd.get("totalSum"),
                        "publish_date": _parse_dt(trd.get("publishDate")),
                        "end_date": _parse_dt(trd.get("endDate")),
                        "raw_url": _trd_url(trd.get("id") or lot.get("trdBuyId")),
                    },
                    lot={
                        "external_id": str(lot.get("id")),
                        "number": lot.get("lotNumber"),
                        "name": lot.get("nameRu"),
                        "description": lot.get("descriptionRu"),
                        "ktru_code": lot.get("ktruCode"),
                        "quantity": lot.get("count"),
                        "total_sum": lot.get("amount"),
                        "country_origin": lot.get("refCountriesIso"),
                        "status": str(lot.get("refLotsStatusId") or ""),
                        "winner_bin": contract.get("supplierBiin"),
                        "winner_name": contract.get("supplierNameRu"),
                    },
                )
            after = lots[-1].get("id")
            if not after:
                return


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return isoparse(value)
    except (ValueError, TypeError):
        return None


def _trd_url(trd_id: int | str | None) -> str | None:
    if not trd_id:
        return None
    return f"https://goszakup.gov.kz/ru/announce/index/{trd_id}"
