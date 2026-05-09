# manufacturers-db

Aggregator of open manufacturer registries with a canonical PostgreSQL schema,
provenance tracking, and CSV export. Built to run on $0/mo from a single
machine and grow into a global manufacturer index.

## Stack

- PostgreSQL 16 (docker-compose) + Adminer
- Python 3.11, `httpx`, `psycopg`, `click`
- Schema in `sql/001_schema.sql`, exports in `sql/exports/*.sql`

## What's working

| Source        | Records              | Status      |
|---------------|----------------------|-------------|
| GLEIF         | ~2.5M global LEIs    | end-to-end  |
| SEC EDGAR     | ~10k US public filers| end-to-end  |
| UN Comtrade   | aggregate trade flows| end-to-end  |
| Companies House (UK)   | —          | stub        |
| OpenCorporates         | —          | stub        |
| ЕГРЮЛ (RU)             | —          | stub        |
| egov.kz / stat.gov.kz  | —          | stub        |
| Wikidata               | —          | stub        |
| OpenSanctions          | —          | stub        |

## Quick start

```bash
cd manufacturers-db
cp .env.example .env                       # edit HTTP_USER_AGENT — put your email
docker compose up -d                       # postgres + adminer (http://localhost:8080)

pip install -r requirements.txt

python -m src init-db                      # apply schema
python -m src ingest gleif --country KZ --limit 1000
python -m src normalize gleif
python -m src export-list
python -m src export manufacturers_basic   # → ./exports/manufacturers_basic.csv
```

## CLI

```
mdb init-db                                Create / migrate schema
mdb ingest <gleif|sec_edgar> [--country XX] [--limit N]
mdb normalize <gleif|sec_edgar>
mdb trade [--reporter all] [--partner 0] [--period YYYY] [--flow M|X] [--hs CODE]
mdb export <view-name>                     Run sql/exports/<view-name>.sql to CSV
mdb export-list                            List available exports
```

## Schema

11 tables, all FK to `entities`:

- `entities` — canonical entity (legal person)
- `entity_sources` — raw API payload (JSONB) per (entity, source); join key is `(source, source_ref)`
- `entity_identifiers` — LEI / CIK / EIN / INN / OGRN / BIN ...
- `entity_addresses`, `entity_contacts`, `entity_officers`, `entity_financials`, `entity_products`
- `trade_flows` — aggregate import/export by HS code (UN Comtrade)
- `entity_matches` — cross-source candidate links with score and decision
- `ingestion_runs` — every fetch tracked (source, params, rows, status, error)

## Layout

```
manufacturers-db/
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── pyproject.toml
├── sql/
│   ├── 001_schema.sql
│   └── exports/
│       ├── manufacturers_basic.sql
│       ├── manufacturers_with_contacts.sql
│       ├── manufacturers_with_financials.sql
│       └── trade_flows_by_hs.sql
├── src/
│   ├── __main__.py             # CLI
│   ├── settings.py
│   ├── db.py
│   ├── connectors/
│   │   ├── base.py
│   │   ├── gleif.py
│   │   ├── sec_edgar.py
│   │   └── un_comtrade.py
│   ├── normalize/
│   │   ├── base.py
│   │   ├── text.py
│   │   ├── gleif.py
│   │   └── sec_edgar.py
│   ├── export/csv.py
│   └── stubs/                  # connector skeletons for next sprint
└── ops/crontab.example
```

## Tests

```bash
pip install pytest
python -m pytest                # 10 tests, no DB / no network needed
```

## Roadmap (next sprint)

1. Implement the 6 stub connectors (Companies House, OpenCorporates, ЕГРЮЛ, egov.kz, Wikidata, OpenSanctions) — base infra is done.
2. Cross-source dedup with [Splink](https://moj-analytical-services.github.io/splink/) — `entity_matches` already has the right columns.
3. `entity_products` enrichment from corporate websites (HS code prediction).
4. Streamlit / FastAPI search UI on top of `manufacturers_basic`.
