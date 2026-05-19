"""Supabase PostgREST read client with TTL cache.

Service-role for reads — bypasses RLS, cleaner than anon for an internal service.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from cachetools import TTLCache

from ..config import get_settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 300


class SupabaseClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Accept": "application/json",
        }
        self._base = settings.supabase_url.rstrip("/")
        self._cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=64, ttl=_TTL_SECONDS)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=4.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def select(self, table: str, query: str, cache_key: str | None = None) -> list[dict[str, Any]]:
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]
        url = f"{self._base}/rest/v1/{table}?{query}"
        resp = await self._client.get(url, headers=self._headers)
        resp.raise_for_status()
        rows = resp.json()
        if cache_key:
            self._cache[cache_key] = rows
        return rows

    async def select_paginated(
        self,
        table: str,
        base_query: str,
        page_size: int = 1000,
        max_pages: int = 60,
        cache_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate via offset to bypass PostgREST's default 1000-row cap.

        max_pages * page_size is the upper bound (60000 rows by default), which
        comfortably covers a 30-day window of clark_watch_details traffic.
        """
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]
        all_rows: list[dict[str, Any]] = []
        for page in range(max_pages):
            offset = page * page_size
            query = f"{base_query}&limit={page_size}&offset={offset}"
            url = f"{self._base}/rest/v1/{table}?{query}"
            resp = await self._client.get(url, headers=self._headers)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
        if cache_key:
            self._cache[cache_key] = all_rows
        return all_rows


_singleton: SupabaseClient | None = None


def get_supabase_client() -> SupabaseClient:
    global _singleton
    if _singleton is None:
        _singleton = SupabaseClient()
    return _singleton
