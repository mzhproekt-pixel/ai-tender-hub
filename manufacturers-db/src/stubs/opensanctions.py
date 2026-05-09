"""OpenSanctions — STUB.

Bulk data: https://www.opensanctions.org/datasets/default/
Daily JSON / FtM dumps of sanctioned entities, PEPs, debarred suppliers.

Use case: flag entities in our DB against sanctions / debarment lists.
Usually we ingest the whole `default` dataset and join via LEI / name+country.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..connectors.base import BaseConnector


class OpenSanctionsConnector(BaseConnector):
    source = "opensanctions"

    def fetch(self, **params: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        raise NotImplementedError("OpenSanctions connector — implement in next sprint")
