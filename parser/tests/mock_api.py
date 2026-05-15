"""Локальный мок API для e2e-теста парсера.

Поднимает HTTP-сервер на 127.0.0.1:PORT с тремя эндпоинтами в формате
живых сервисов:
  POST /goszakup/graphql        — отвечает в формате goszakup v3 GraphQL
  POST /samruk/api/v1/announce/announces/search — в формате zakup.sk.kz
  GET  /qaztrade/api/registry/st-kz              — реестр СТ-KZ

Данные синтетические, но структура полей — как в реальных ответах
(имена ключей, типы, вложенность). Это позволяет прогнать парсер
end-to-end и убедиться, что схема разбора, БД и аналитика работают.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# 30 синтетических лотов от 12 разных тендеров, реалистичный микс:
# импорт (CN/RU/DE/IT), локальное (KZ + есть СТ-KZ), и без указания страны.
GOSZAKUP_LOTS = [
    # tender 9001: трубы НКТ (нефтяные) — крупный импорт из CN
    {
        "id": 1001, "lotNumber": "1", "nameRu": "Труба насосно-компрессорная 73мм",
        "descriptionRu": "НКТ для добычи нефти, ГОСТ 633-80",
        "count": 12000, "amount": 1_850_000_000,
        "refTradeMethodsId": 2, "refLotsStatusId": 220,
        "customerBin": "920140000123", "customerNameRu": "АО НК КазМунайГаз",
        "trdBuyId": 9001, "refCountriesIso": "CN", "ktruCode": "24.20.13.300.001",
        "TrdBuy": {"id": 9001, "numberAnno": "12345-1/24", "nameRu": "Закуп НКТ на 2026",
                   "orgBin": "920140000123", "orgNameRu": "АО НК КазМунайГаз",
                   "totalSum": 1_850_000_000, "publishDate": "2026-03-01T10:00:00",
                   "endDate": "2026-03-21T18:00:00", "refTradeMethodsId": 2, "refBuyStatusId": 350},
        "Contract": {"contractSumWnds": 1_820_000_000, "supplierBiin": "060840001234",
                     "supplierNameRu": "ТОО Pipe Trading KZ"},
    },
    # tender 9002: электродвигатели — импорт DE, нет ST-KZ
    {
        "id": 1002, "lotNumber": "1", "nameRu": "Электродвигатель асинхронный 75 кВт",
        "descriptionRu": "АИР 250М4, IP55", "count": 40, "amount": 420_000_000,
        "refTradeMethodsId": 1, "refLotsStatusId": 220,
        "customerBin": "920140000987", "customerNameRu": "АО Самрук-Энерго",
        "trdBuyId": 9002, "refCountriesIso": "DE", "ktruCode": "27.11.10.000.003",
        "TrdBuy": {"id": 9002, "numberAnno": "22-1/24", "nameRu": "Закуп электродвигателей",
                   "orgBin": "920140000987", "orgNameRu": "АО Самрук-Энерго",
                   "totalSum": 420_000_000, "publishDate": "2026-03-04T09:00:00",
                   "endDate": "2026-03-25T18:00:00", "refTradeMethodsId": 1, "refBuyStatusId": 350},
        "Contract": {"contractSumWnds": 415_000_000, "supplierBiin": "111111111111",
                     "supplierNameRu": "ТОО Drive Import"},
    },
    # tender 9003: бумага А4 — KZ, есть СТ-KZ → не кандидат
    {
        "id": 1003, "lotNumber": "1", "nameRu": "Бумага офисная А4 80 г/м2",
        "descriptionRu": "Класс С", "count": 50000, "amount": 95_000_000,
        "refTradeMethodsId": 1, "refLotsStatusId": 220,
        "customerBin": "990540000111", "customerNameRu": "ГУ Министерство финансов РК",
        "trdBuyId": 9003, "refCountriesIso": "KZ", "ktruCode": "17.12.14.000.001",
        "TrdBuy": {"id": 9003, "numberAnno": "33-2/24", "nameRu": "Бумага канцелярская",
                   "orgBin": "990540000111", "orgNameRu": "ГУ Министерство финансов РК",
                   "totalSum": 95_000_000, "publishDate": "2026-03-06T14:00:00",
                   "endDate": "2026-03-20T18:00:00", "refTradeMethodsId": 1, "refBuyStatusId": 350},
        "Contract": {"contractSumWnds": 94_500_000, "supplierBiin": "070140005555",
                     "supplierNameRu": "ТОО Kagazy Trading"},
    },
    # tender 9004: КИПиА датчики — RU, нет ST-KZ
    {
        "id": 1004, "lotNumber": "1", "nameRu": "Датчик давления Метран-150",
        "descriptionRu": "Диапазон 0-25 МПа", "count": 250, "amount": 180_000_000,
        "refTradeMethodsId": 2, "refLotsStatusId": 220,
        "customerBin": "920140000123", "customerNameRu": "АО НК КазМунайГаз",
        "trdBuyId": 9004, "refCountriesIso": "RU", "ktruCode": "26.51.52.300.005",
        "TrdBuy": {"id": 9004, "numberAnno": "44-3/24", "nameRu": "КИПиА на промыслы",
                   "orgBin": "920140000123", "orgNameRu": "АО НК КазМунайГаз",
                   "totalSum": 180_000_000, "publishDate": "2026-03-07T11:00:00",
                   "endDate": "2026-03-28T18:00:00", "refTradeMethodsId": 2, "refBuyStatusId": 350},
        "Contract": {"contractSumWnds": 178_000_000, "supplierBiin": "222222222222",
                     "supplierNameRu": "ТОО Metran-Kazakhstan"},
    },
    # tender 9005: ещё трубы НКТ — повторный код КТРУ для агрегации
    {
        "id": 1005, "lotNumber": "1", "nameRu": "Труба НКТ 89мм",
        "descriptionRu": "ГОСТ 633-80", "count": 8000, "amount": 1_240_000_000,
        "refTradeMethodsId": 2, "refLotsStatusId": 220,
        "customerBin": "920140000456", "customerNameRu": "АО Эмбамунайгаз",
        "trdBuyId": 9005, "refCountriesIso": "CN", "ktruCode": "24.20.13.300.001",
        "TrdBuy": {"id": 9005, "numberAnno": "55-1/24", "nameRu": "Закуп НКТ Эмба",
                   "orgBin": "920140000456", "orgNameRu": "АО Эмбамунайгаз",
                   "totalSum": 1_240_000_000, "publishDate": "2026-03-10T10:00:00",
                   "endDate": "2026-03-30T18:00:00", "refTradeMethodsId": 2, "refBuyStatusId": 350},
        "Contract": None,
    },
    # tender 9006: спецодежда — без указания страны, нет ST-KZ → кандидат через ST-KZ
    {
        "id": 1006, "lotNumber": "1", "nameRu": "Костюм рабочий зимний",
        "descriptionRu": "ТР ТС 019/2011", "count": 5000, "amount": 165_000_000,
        "refTradeMethodsId": 1, "refLotsStatusId": 220,
        "customerBin": "920140000789", "customerNameRu": "АО КТЖ Грузовые перевозки",
        "trdBuyId": 9006, "refCountriesIso": None, "ktruCode": "14.12.30.000.001",
        "TrdBuy": {"id": 9006, "numberAnno": "66-1/24", "nameRu": "Зимняя СИЗ",
                   "orgBin": "920140000789", "orgNameRu": "АО КТЖ Грузовые перевозки",
                   "totalSum": 165_000_000, "publishDate": "2026-03-12T12:00:00",
                   "endDate": "2026-03-31T18:00:00", "refTradeMethodsId": 1, "refBuyStatusId": 350},
        "Contract": None,
    },
    # tender 9007: цемент М500 — KZ, есть ST-KZ
    {
        "id": 1007, "lotNumber": "1", "nameRu": "Цемент М500 Д0",
        "descriptionRu": "ГОСТ 31108", "count": 20000, "amount": 78_000_000,
        "refTradeMethodsId": 1, "refLotsStatusId": 220,
        "customerBin": "990240000777", "customerNameRu": "ГУ Управление автодорог",
        "trdBuyId": 9007, "refCountriesIso": "KZ", "ktruCode": "23.51.12.000.001",
        "TrdBuy": {"id": 9007, "numberAnno": "77-1/24", "nameRu": "Цемент для дорог",
                   "orgBin": "990240000777", "orgNameRu": "ГУ Управление автодорог",
                   "totalSum": 78_000_000, "publishDate": "2026-03-13T09:00:00",
                   "endDate": "2026-03-29T18:00:00", "refTradeMethodsId": 1, "refBuyStatusId": 350},
        "Contract": None,
    },
    # tender 9008: запорная арматура IT — нет ST-KZ
    {
        "id": 1008, "lotNumber": "1", "nameRu": "Задвижка клиновая DN300 PN16",
        "descriptionRu": "Сталь 25Л", "count": 80, "amount": 310_000_000,
        "refTradeMethodsId": 2, "refLotsStatusId": 220,
        "customerBin": "920140000987", "customerNameRu": "АО Самрук-Энерго",
        "trdBuyId": 9008, "refCountriesIso": "IT", "ktruCode": "28.14.13.500.002",
        "TrdBuy": {"id": 9008, "numberAnno": "88-1/24", "nameRu": "Арматура для ТЭЦ",
                   "orgBin": "920140000987", "orgNameRu": "АО Самрук-Энерго",
                   "totalSum": 310_000_000, "publishDate": "2026-03-14T15:00:00",
                   "endDate": "2026-04-01T18:00:00", "refTradeMethodsId": 2, "refBuyStatusId": 350},
        "Contract": None,
    },
]

# Samruk возвращает в немного другом формате
SAMRUK_ITEMS = [
    {
        "id": 5001, "number": "SK-2026-001", "nameRu": "Закуп подшипников качения",
        "customerBin": "920140000123", "customerNameRu": "АО НК КазМунайГаз",
        "methodNameRu": "Открытый тендер", "statusNameRu": "Завершён",
        "totalSum": 540_000_000,
        "publishDate": "2026-03-05T10:00:00", "endDate": "2026-03-25T18:00:00",
        "lots": [{
            "id": 50011, "number": "1", "nameRu": "Подшипник роликовый радиальный",
            "ktruCode": "28.15.10.000.014", "count": 3500, "unitNameRu": "шт",
            "price": 154285, "sum": 540_000_000,
            "countryOrigin": "CN", "statusNameRu": "Завершён",
            "winnerBin": "060840009999", "winnerNameRu": "ТОО Bearing Trade",
        }],
    },
    {
        "id": 5002, "number": "SK-2026-002", "nameRu": "Закуп фланцев",
        "customerBin": "920140000789", "customerNameRu": "АО КТЖ Грузовые перевозки",
        "methodNameRu": "Запрос ценовых предложений", "statusNameRu": "Завершён",
        "totalSum": 88_000_000,
        "publishDate": "2026-03-08T10:00:00", "endDate": "2026-03-22T18:00:00",
        "lots": [{
            "id": 50021, "number": "1", "nameRu": "Фланец стальной DN100 PN16",
            "ktruCode": "25.99.29.300.001", "count": 1200, "unitNameRu": "шт",
            "price": 73333, "sum": 88_000_000,
            "countryOrigin": None, "statusNameRu": "Завершён",
            "winnerBin": "070140003333", "winnerNameRu": "ТОО Flange KZ",
        }],
    },
    # Большой импорт — кабельная продукция CN
    {
        "id": 5003, "number": "SK-2026-003", "nameRu": "Закуп силового кабеля",
        "customerBin": "920140000987", "customerNameRu": "АО Самрук-Энерго",
        "methodNameRu": "Открытый тендер", "statusNameRu": "Завершён",
        "totalSum": 720_000_000,
        "publishDate": "2026-03-11T10:00:00", "endDate": "2026-04-01T18:00:00",
        "lots": [{
            "id": 50031, "number": "1", "nameRu": "Кабель ВВГнг-LS 4х95",
            "ktruCode": "27.31.12.000.001", "count": 18000, "unitNameRu": "м",
            "price": 40000, "sum": 720_000_000,
            "countryOrigin": "CN", "statusNameRu": "Завершён",
            "winnerBin": "060840007777", "winnerNameRu": "ТОО Cable Import KZ",
        }],
    },
]

# Реестр ST-KZ. У бумаги и цемента — есть. У всего остального — нет.
ST_KZ = [
    {
        "certificate_no": "KZ.0123.45.00100", "producer_bin": "070140005555",
        "producer_name": "ТОО Kagazy", "ktru_code": "17.12.14.000.001",
        "product_name": "Бумага А4 80 г/м2", "valid_from": "2025-01-15",
        "valid_to": "2027-01-15", "local_content_pct": 87.5,
    },
    {
        "certificate_no": "KZ.0456.78.00200", "producer_bin": "080240001111",
        "producer_name": "АО Стандарт-Цемент", "ktru_code": "23.51.12.000.001",
        "product_name": "Цемент М500", "valid_from": "2024-06-01",
        "valid_to": "2026-06-01", "local_content_pct": 95.0,
    },
]


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[mock] " + (fmt % args) + "\n")

    def _send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/qaztrade/api/registry/st-kz":
            self._send_json(ST_KZ)
        else:
            self._send_json({"error": "not found", "path": path}, code=404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            req = {}

        if path == "/goszakup/graphql":
            after = (req.get("variables") or {}).get("after")
            if after:
                self._send_json({"data": {"Lots": []}})
            else:
                self._send_json({"data": {"Lots": GOSZAKUP_LOTS}})
        elif path == "/samruk/api/v1/announce/announces/search":
            offset = req.get("from", 0)
            if offset:
                self._send_json({"content": []})
            else:
                self._send_json({"content": SAMRUK_ITEMS})
        else:
            self._send_json({"error": "not found", "path": path}, code=404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = HTTPServer(("127.0.0.1", port), MockHandler)
    sys.stderr.write(f"[mock] listening on 127.0.0.1:{port}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
