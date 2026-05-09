"""Project GLEIF raw payloads into typed tables.

GLEIF level-1 schema (LEI Records) per record:
  attributes:
    lei
    entity:
      legalName.name
      legalAddress.{country,region,city,postalCode,addressLines[]}
      headquartersAddress.{...}
      legalForm.id
      status
      registeredAt.id  (BIC/local registry)
"""
from __future__ import annotations

from typing import Any

from .base import BaseNormalizer
from .text import normalize_country, normalize_name


def _street(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    lines = addr.get("addressLines") or []
    if isinstance(lines, list):
        return ", ".join(str(x) for x in lines if x) or None
    return str(lines) or None


class GleifNormalizer(BaseNormalizer):
    source = "gleif"

    def project(self, cur, entity_id: int, raw: dict[str, Any]) -> None:
        attrs = raw.get("attributes") or {}
        ent = attrs.get("entity") or {}
        lei = attrs.get("lei")

        legal_name = (ent.get("legalName") or {}).get("name")
        legal_form = (ent.get("legalForm") or {}).get("id")
        status = ent.get("status")
        legal_addr = ent.get("legalAddress") or {}
        hq_addr = ent.get("headquartersAddress") or {}
        country = normalize_country(legal_addr.get("country") or hq_addr.get("country"))

        cur.execute(
            """
            UPDATE entities
               SET canonical_name = COALESCE(%s, canonical_name),
                   name_norm      = COALESCE(%s, name_norm),
                   country        = COALESCE(%s, country),
                   legal_form     = COALESCE(%s, legal_form),
                   status         = COALESCE(%s, status),
                   updated_at     = now()
             WHERE id = %s
            """,
            (legal_name, normalize_name(legal_name) or None, country, legal_form,
             (status or "").lower() or None, entity_id),
        )

        if lei:
            cur.execute(
                "INSERT INTO entity_identifiers(entity_id, scheme, value, source) "
                "VALUES (%s,'LEI',%s,%s) ON CONFLICT (scheme,value) DO NOTHING",
                (entity_id, lei, self.source),
            )

        # Wipe and re-insert addresses for this source so re-runs are idempotent.
        cur.execute(
            "DELETE FROM entity_addresses WHERE entity_id = %s AND source = %s",
            (entity_id, self.source),
        )
        for kind, a in (("legal", legal_addr), ("hq", hq_addr)):
            if not a:
                continue
            cur.execute(
                """
                INSERT INTO entity_addresses
                  (entity_id, kind, country, region, city, postal_code, street, raw, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    entity_id, kind,
                    normalize_country(a.get("country")),
                    a.get("region"), a.get("city"), a.get("postalCode"),
                    _street(a), None, self.source,
                ),
            )
