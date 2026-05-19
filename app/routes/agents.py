"""Phase 3 — Agent Liveness Matrix.

Per spec section 8.2: a matrix of signal-event counts per (canonical_agent,
ET-date) over the last N days. Drives a heat-map widget that answers
"which agents are alive, which have gone silent, and when did the voice
shift?"

The matrix is dense (10 agents x ~90 days) so even on a 4500-row signal
sample the response stays under 30 KB.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from zoneinfo import ZoneInfo

from ..auth import require_token
from ..canonical import (
    CANONICAL_AGENTS,
    SIGNAL_EVENT_TYPES,
    classify_event,
    normalize_surface,
)
from ..clients.supabase import get_supabase_client

router = APIRouter()
ET = ZoneInfo("America/New_York")


def _to_et_date(event_at_iso: str) -> str:
    dt = datetime.fromisoformat(event_at_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().isoformat()


@router.get("/liveness", dependencies=[Depends(require_token)])
async def agents_liveness(days: int = Query(default=90, ge=7, le=365)) -> dict[str, Any]:
    sb = get_supabase_client()

    now_utc = datetime.now(timezone.utc)
    since_iso = (now_utc - timedelta(days=days + 1)).isoformat().replace("+00:00", "Z")

    signal_list = ",".join(sorted(SIGNAL_EVENT_TYPES))
    base_query = (
        "select=event_at,event_type,surface"
        f"&event_at=gte.{since_iso}"
        f"&event_type=in.({signal_list})"
        "&order=event_at.desc"
    )
    cache_key = f"agents:liveness:{days}:{since_iso[:13]}"

    try:
        rows = await sb.select_paginated(
            "clark_watch_details", base_query, cache_key=cache_key
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    today_et = datetime.now(ET).date()
    start_et = today_et - timedelta(days=days - 1)
    day_list: list[str] = [
        (start_et + timedelta(days=i)).isoformat() for i in range(days)
    ]
    day_index = {d: i for i, d in enumerate(day_list)}

    matrix: dict[str, list[int]] = {a: [0] * days for a in CANONICAL_AGENTS}
    last_signal: dict[str, str | None] = {a: None for a in CANONICAL_AGENTS}
    silent_other_count = 0

    for row in rows:
        if classify_event(row.get("event_type")) != "signal":
            continue
        agent = normalize_surface(row.get("surface"))
        if agent == "other":
            silent_other_count += 1
            continue
        if agent == "heartbeat":
            # Heartbeat is operationally a noise channel even if signal-typed
            # events appear on it — keep it in CANONICAL_AGENTS for display but
            # do not include in matrix counts. Per spec section 1.2 it is
            # "treated separately, not narrative."
            continue
        day = _to_et_date(row.get("event_at") or "")
        idx = day_index.get(day)
        if idx is None:
            continue
        matrix[agent][idx] += 1
        if last_signal[agent] is None or day > last_signal[agent]:
            last_signal[agent] = day

    # Per-agent days-since-last-signal (relative to today_et)
    silent_streak: dict[str, int | None] = {}
    for agent in CANONICAL_AGENTS:
        last = last_signal.get(agent)
        if not last:
            silent_streak[agent] = None  # never spoke in window
            continue
        last_d = datetime.strptime(last, "%Y-%m-%d").date()
        silent_streak[agent] = (today_et - last_d).days

    # Per-agent total signal events in window
    totals = {a: sum(matrix[a]) for a in CANONICAL_AGENTS}

    return {
        "agents": CANONICAL_AGENTS,
        "days": day_list,
        "matrix": matrix,
        "totals": totals,
        "last_signal": last_signal,
        "silent_days": silent_streak,
        "buckets": {
            "silent": [0, 0],
            "light": [1, 2],
            "moderate": [3, 7],
            "active": [8, 20],
            "heavy": [21, None],
        },
        "window": {
            "days": days,
            "start": start_et.isoformat(),
            "end": today_et.isoformat(),
        },
        "unmapped_signal_events": silent_other_count,
    }


@router.get("/liveness/{agent}/{date}/events", dependencies=[Depends(require_token)])
async def agents_liveness_events(
    agent: str, date: str, limit: int = Query(default=10, ge=1, le=50)
) -> dict[str, Any]:
    """Signal events for a given (canonical agent, ET date) — drives click-cell modal."""
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid date: {e}") from e

    start_et = datetime(target.year, target.month, target.day, 0, 0, tzinfo=ET)
    end_et = start_et + timedelta(days=1)
    start_iso = start_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = end_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    sb = get_supabase_client()
    signal_list = ",".join(sorted(SIGNAL_EVENT_TYPES))
    # Fetch all signal rows in the day window; filter agent in Python since the
    # canonical map covers ~16 raw surface variants and we want all of them.
    query = (
        "select=event_at,event_type,surface,summary"
        f"&event_at=gte.{start_iso}"
        f"&event_at=lt.{end_iso}"
        f"&event_type=in.({signal_list})"
        "&order=event_at.desc"
    )
    cache_key = f"agents:liveness-events:{agent}:{date}"
    try:
        rows = await sb.select_paginated(
            "clark_watch_details", query, cache_key=cache_key, max_pages=10
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    matched = [r for r in rows if normalize_surface(r.get("surface")) == agent][:limit]

    return {
        "agent": agent,
        "date": date,
        "events": [
            {
                "event_at": r.get("event_at"),
                "event_type": r.get("event_type"),
                "surface": r.get("surface"),
                "summary": (r.get("summary") or "")[:400],
            }
            for r in matched
        ],
    }
