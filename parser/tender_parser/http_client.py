from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import settings

log = logging.getLogger(__name__)

_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


def make_client(base_url: str = "", headers: dict[str, str] | None = None) -> httpx.Client:
    hdrs = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    return httpx.Client(
        base_url=base_url,
        headers=hdrs,
        timeout=settings.http_timeout,
        follow_redirects=True,
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=16),
    retry=retry_if_exception_type(_RETRYABLE),
)
def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> dict:
    r = client.get(url, params=params)
    if r.status_code == 429:
        raise httpx.NetworkError("rate limited")
    r.raise_for_status()
    return r.json()


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=16),
    retry=retry_if_exception_type(_RETRYABLE),
)
def post_json(client: httpx.Client, url: str, payload: dict[str, Any]) -> dict:
    r = client.post(url, json=payload)
    if r.status_code == 429:
        raise httpx.NetworkError("rate limited")
    r.raise_for_status()
    return r.json()
