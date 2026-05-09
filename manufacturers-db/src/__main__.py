"""mdb — Manufacturers DB CLI.

Subcommands:
  init-db                Apply canonical schema (idempotent)
  ingest <source>        Pull raw payloads from a source into entity_sources
  normalize <source>     Project raw payloads into typed tables
  trade ...              Pull aggregate trade flows from UN Comtrade
  export <name>          Run a SQL view in sql/exports/ to CSV
  export-list            List available exports
"""
from __future__ import annotations

import logging

import click

from .db import init_db as _init_db
from .export.csv import export_to_csv, list_exports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@click.group()
def cli() -> None:
    """Manufacturers DB CLI."""


@cli.command("init-db")
def init_db_cmd() -> None:
    """Create / migrate schema."""
    _init_db()
    click.echo("schema applied")


@cli.command()
@click.argument("source", type=click.Choice(["gleif", "sec_edgar"]))
@click.option("--country", default=None, help="ISO 3166-1 alpha-2 (GLEIF only)")
@click.option("--limit", type=int, default=1000, show_default=True)
def ingest(source: str, country: str | None, limit: int) -> None:
    """Pull raw payloads from a source."""
    if source == "gleif":
        from .connectors.gleif import GleifConnector
        c = GleifConnector()
        try:
            stats = c.run(country=country, limit=limit)
        finally:
            c.close()
    else:
        from .connectors.sec_edgar import SecEdgarConnector
        c = SecEdgarConnector()
        try:
            stats = c.run(limit=limit)
        finally:
            c.close()
    click.echo(stats)


@cli.command()
@click.argument("source", type=click.Choice(["gleif", "sec_edgar"]))
def normalize(source: str) -> None:
    """Project raw payloads into typed tables."""
    if source == "gleif":
        from .normalize.gleif import GleifNormalizer
        n = GleifNormalizer()
    else:
        from .normalize.sec_edgar import SecEdgarNormalizer
        n = SecEdgarNormalizer()
    n_rows = n.run()
    click.echo(f"normalised {n_rows} rows from {source}")


@cli.command()
@click.option("--reporter", default="all")
@click.option("--partner", default="0")
@click.option("--period", type=int, default=2023, show_default=True)
@click.option("--flow", type=click.Choice(["M", "X"]), default="M", show_default=True)
@click.option("--hs", default="TOTAL", show_default=True)
@click.option("--limit", type=int, default=None)
def trade(reporter: str, partner: str, period: int, flow: str, hs: str, limit: int | None) -> None:
    """Pull aggregate trade flows from UN Comtrade."""
    from .connectors.un_comtrade import UnComtradeConnector
    c = UnComtradeConnector()
    try:
        stats = c.run(reporter=reporter, partner=partner, period=period, flow=flow, hs=hs, limit=limit)
    finally:
        c.close()
    click.echo(stats)


@cli.command("export-list")
def export_list_cmd() -> None:
    """Show available SQL exports."""
    for name in list_exports():
        click.echo(name)


@cli.command()
@click.argument("name")
def export(name: str) -> None:
    """Run a SQL export and write CSV to EXPORT_DIR."""
    out = export_to_csv(name)
    click.echo(f"wrote {out}")


if __name__ == "__main__":
    cli()
