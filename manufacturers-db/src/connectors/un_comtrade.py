"""UN Comtrade aggregate trade flows.

Public preview API: https://comtradeapi.un.org/public/v1/preview/{type}/{freq}/{cls}
  type: C (commodities) or S (services)
  freq: A (annual) or M (monthly)
  cls : HS (Harmonised System), SITC, BEC, etc.

We write rows directly to `trade_flows` (this is aggregate data, not entities).
"""
from __future__ import annotations

from typing import Any, Iterator

from ..db import connect, finish_run, start_run
from .base import BaseConnector

API = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"


class UnComtradeConnector(BaseConnector):
    source = "un_comtrade"

    def fetch(
        self,
        *,
        reporter: str = "all",
        partner: str = "0",      # 0 = world
        period: int = 2023,
        flow: str = "M",         # M = import, X = export
        hs: str = "TOTAL",
        limit: int | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        params = {
            "reporterCode": reporter,
            "partnerCode": partner,
            "period": period,
            "flowCode": flow,
            "cmdCode": hs,
        }
        data = self.get_json(API, params=params)
        rows = data.get("data", []) or []
        for i, row in enumerate(rows):
            ref = f"{row.get('refYear')}-{row.get('flowCode')}-{row.get('reporterCode')}-{row.get('partnerCode')}-{row.get('cmdCode')}"
            yield ref, row
            if limit and i + 1 >= limit:
                return

    # Override run() so that records land in `trade_flows`, not entity_sources.
    def run(self, **params: Any) -> dict[str, int]:
        run_id = start_run(self.source, params)
        rows_in = rows_up = 0
        try:
            with connect() as conn, conn.cursor() as cur:
                for _ref, row in self.fetch(**params):
                    rows_in += 1
                    cur.execute(
                        """
                        INSERT INTO trade_flows
                          (period, flow, reporter_iso, partner_iso, hs_code,
                           trade_value_usd, net_weight_kg, qty, qty_unit, source)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source, period, flow, reporter_iso, partner_iso, hs_code)
                        DO UPDATE SET
                            trade_value_usd = EXCLUDED.trade_value_usd,
                            net_weight_kg   = EXCLUDED.net_weight_kg,
                            qty             = EXCLUDED.qty,
                            qty_unit        = EXCLUDED.qty_unit
                        """,
                        (
                            row.get("refYear") or row.get("period"),
                            (row.get("flowCode") or "").lower() or "import",
                            row.get("reporterISO") or row.get("reporterCode"),
                            row.get("partnerISO") or row.get("partnerCode"),
                            str(row.get("cmdCode") or "TOTAL"),
                            row.get("primaryValue") or row.get("TradeValue"),
                            row.get("netWgt"),
                            row.get("qty"),
                            row.get("qtyUnitAbbr"),
                            self.source,
                        ),
                    )
                    rows_up += 1
                conn.commit()
            finish_run(run_id, status="ok", rows_in=rows_in, rows_upserted=rows_up)
        except Exception as exc:
            finish_run(run_id, status="error", rows_in=rows_in, rows_upserted=rows_up, error=str(exc)[:1000])
            raise
        return {"run_id": run_id, "rows_in": rows_in, "rows_upserted": rows_up}
