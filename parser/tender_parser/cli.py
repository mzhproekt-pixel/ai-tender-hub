"""CLI: fetch / refresh-stkz / analyze / export."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from . import analyze, ktru
from .config import settings
from .db import get_engine, init_db
from .ingest import save_lots
from .sources.goszakup import GoszakupClient
from .sources.samruk import SamrukClient

console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False)],
    )


def _default_dates(days: int) -> tuple[str, str]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


@click.group()
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def cli(ctx, verbose: bool) -> None:
    """AI Tender Hub — парсер тендеров РК."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    init_db()


@cli.command("fetch")
@click.option(
    "--source",
    type=click.Choice(["goszakup", "samruk", "both"]),
    default="both",
    show_default=True,
)
@click.option("--days", type=int, default=30, show_default=True, help="Глубина выгрузки.")
@click.option("--date-from", default=None, help="ISO дата (перекрывает --days).")
@click.option("--date-to", default=None)
@click.option("--page-size", type=int, default=200, show_default=True)
def fetch_cmd(source, days, date_from, date_to, page_size):
    """Скачать лоты из выбранных источников и сложить в SQLite."""
    if not date_from or not date_to:
        d_from, d_to = _default_dates(days)
        date_from = date_from or d_from
        date_to = date_to or d_to
    console.log(f"period: {date_from} .. {date_to}, source={source}")

    totals_t, totals_l = 0, 0
    if source in ("goszakup", "both"):
        with GoszakupClient() as gz:
            tn, ln = save_lots(gz.fetch_lots(date_from, date_to, page_size=page_size))
            console.log(f"[goszakup] tenders+={tn}, lots+={ln}")
            totals_t += tn
            totals_l += ln
    if source in ("samruk", "both"):
        with SamrukClient() as sk:
            tn, ln = save_lots(sk.fetch_lots(date_from, date_to, page_size=page_size))
            console.log(f"[samruk]   tenders+={tn}, lots+={ln}")
            totals_t += tn
            totals_l += ln
    console.print(f"[green]done.[/green] tenders={totals_t} lots={totals_l}")


@cli.command("refresh-stkz")
def refresh_stkz_cmd():
    """Обновить реестр СТ-KZ и проставить флаги локализации у лотов."""
    n = ktru.load_st_kz_registry()
    m = ktru.mark_localization_candidates()
    console.print(f"ST-KZ certs loaded: [bold]{n}[/bold], lots annotated: [bold]{m}[/bold]")


@cli.command("top-imports")
@click.option("--limit", type=int, default=30, show_default=True)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
def top_imports_cmd(limit, date_from, date_to):
    """Топ импортных лотов по объёму закупок."""
    df = analyze.top_imports(limit=limit, date_from=date_from, date_to=date_to)
    _render_table(df, title=f"Top {limit} imports")


@cli.command("candidates")
@click.option("--limit", type=int, default=30, show_default=True)
@click.option("--min-kzt", type=float, default=100_000_000, show_default=True)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--csv", "csv_path", type=click.Path(path_type=Path), default=None)
def candidates_cmd(limit, min_kzt, date_from, date_to, csv_path):
    """Топ КТРУ-кодов — кандидатов на локализацию в РК."""
    df = analyze.localization_candidates(
        limit=limit, min_kzt=min_kzt, date_from=date_from, date_to=date_to
    )
    _render_table(df, title=f"Localization candidates (top {limit})")
    if csv_path:
        analyze.export_csv(df, csv_path)
        console.print(f"saved: [cyan]{csv_path}[/cyan]")


@cli.command("export")
@click.option("--what", type=click.Choice(["top-imports", "candidates"]), default="candidates")
@click.option("--out", "out_path", type=click.Path(path_type=Path), required=True)
@click.option("--limit", type=int, default=500, show_default=True)
def export_cmd(what, out_path, limit):
    """Экспорт результатов в CSV."""
    if what == "top-imports":
        df = analyze.top_imports(limit=limit)
    else:
        df = analyze.localization_candidates(limit=limit)
    analyze.export_csv(df, out_path)
    console.print(f"exported {len(df)} rows to [cyan]{out_path}[/cyan]")


@cli.command("info")
def info_cmd():
    """Состояние БД."""
    engine = get_engine()
    with engine.connect() as conn:
        from sqlalchemy import text

        for q, label in [
            ("SELECT COUNT(*) FROM tenders", "tenders"),
            ("SELECT COUNT(*) FROM lots", "lots"),
            ("SELECT COUNT(*) FROM lots WHERE ktru_code IS NOT NULL", "lots with KTRU"),
            ("SELECT COUNT(*) FROM st_kz_certificates", "ST-KZ certificates"),
            (
                "SELECT COUNT(DISTINCT ktru_code) FROM lots "
                "WHERE ktru_code IS NOT NULL AND is_st_kz_available = 0",
                "KTRU codes without ST-KZ",
            ),
        ]:
            n = conn.execute(text(q)).scalar()
            console.print(f"{label:.<40} {n}")
        console.print(f"\ndb: [cyan]{settings.db_path}[/cyan]")


def _render_table(df, title: str) -> None:
    if df.empty:
        console.print("[yellow]no data — запустите `fetch` и `refresh-stkz` сначала[/yellow]")
        return
    t = Table(title=title, header_style="bold cyan")
    for col in df.columns:
        t.add_column(col)
    for _, row in df.iterrows():
        t.add_row(*[("" if v is None else str(v)) for v in row.tolist()])
    console.print(t)


if __name__ == "__main__":
    cli()
