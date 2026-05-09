"""Project SEC EDGAR submissions JSON into typed tables.

The SEC submissions endpoint returns:
  cik, name, sic, sicDescription, ein, exchanges[], tickers[],
  addresses: { mailing: {...}, business: {...} }
The address.stateOrCountry field is mostly US state codes (NY, CA, ...) — we
keep country='US' when the code is a 2-letter US state, otherwise treat it as
ISO country.
"""
from __future__ import annotations

from typing import Any

from .base import BaseNormalizer
from .text import normalize_country, normalize_name

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","GU","VI","AS","MP",
}


def _addr_country(state_or_country: str | None) -> tuple[str | None, str | None]:
    """Return (country_iso2, region)."""
    if not state_or_country:
        return None, None
    code = state_or_country.strip().upper()
    if code in US_STATES:
        return "US", code
    return normalize_country(code), None


class SecEdgarNormalizer(BaseNormalizer):
    source = "sec_edgar"

    def project(self, cur, entity_id: int, raw: dict[str, Any]) -> None:
        name = raw.get("name")
        cik = raw.get("cik")
        ein = raw.get("ein")
        addresses = raw.get("addresses") or {}
        biz = addresses.get("business") or {}
        country, region = _addr_country(biz.get("stateOrCountry"))

        cur.execute(
            """
            UPDATE entities
               SET canonical_name = COALESCE(%s, canonical_name),
                   name_norm      = COALESCE(%s, name_norm),
                   country        = COALESCE(%s, country),
                   updated_at     = now()
             WHERE id = %s
            """,
            (name, normalize_name(name) or None, country, entity_id),
        )

        if cik:
            cur.execute(
                "INSERT INTO entity_identifiers(entity_id, scheme, value, source) "
                "VALUES (%s,'CIK',%s,%s) ON CONFLICT (scheme,value) DO NOTHING",
                (entity_id, str(cik).zfill(10), self.source),
            )
        if ein:
            cur.execute(
                "INSERT INTO entity_identifiers(entity_id, scheme, value, source) "
                "VALUES (%s,'EIN',%s,%s) ON CONFLICT (scheme,value) DO NOTHING",
                (entity_id, str(ein), self.source),
            )

        cur.execute(
            "DELETE FROM entity_addresses WHERE entity_id = %s AND source = %s",
            (entity_id, self.source),
        )
        for kind_key, kind in (("business", "hq"), ("mailing", "mailing")):
            a = addresses.get(kind_key) or {}
            if not a:
                continue
            ac, ar = _addr_country(a.get("stateOrCountry"))
            cur.execute(
                """
                INSERT INTO entity_addresses
                  (entity_id, kind, country, region, city, postal_code, street, raw, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (entity_id, kind, ac, ar, a.get("city"), a.get("zipCode"),
                 a.get("street1") or a.get("street"),
                 None, self.source),
            )
