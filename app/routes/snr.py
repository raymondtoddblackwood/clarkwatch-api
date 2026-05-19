"""Phase 1 — Signal:Noise gauge endpoint.

Per spec §8.1: per-day class counts for last N days, with current-week
noise percentage and per-day alarm flag.

We pull rows from clark_watch_details, classify each in Python via
canonical.classify_event, bucket by ET calendar date, and emit one row per
day. Done in app rather than SQL because PostgREST CASE expressions don't
compose well across that many event types.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from zoneinfo import ZoneInfo

from ..auth import require_token
from ..canonical import SIGNAL_EVENT_TYPES, classify_event
from ..clients.supabase import get_supabase_client

router = APIRouter()

ET = ZoneInfo("America/New_York")
ALARM_THRESHOLD_PCT = 50.0


def _to_et_date(event_at_iso: str) -> str:
    """Parse a Supabase ISO timestamp and return YYYY-MM-DD in ET."""
    dt = datetime.fromisoformat(event_at_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().isoformat()


@router.get("/daily", dependencies=[Depends(require_token)])
async def snr_daily(days: int = Query(default=30, ge=1, le=180)) -> dict[str, Any]:
    sb = get_supabase_client()

    now_utc = datetime.now(timezone.utc)
    since_iso = (now_utc - timedelta(days=days + 1)).isoformat().replace("+00:00", "Z")

    base_query = (
        "select=event_at,event_type"
        f"&event_at=gte.{since_iso}"
        "&order=event_at.desc"
    )
    cache_key = f"snr:daily:{days}:{since_iso[:13]}"

    try:
        rows = await sb.select_paginated("clark_watch_details", base_query, cache_key=cache_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    today_et = datetime.now(ET).date()
    start_et = today_et - timedelta(days=days - 1)

    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"signal": 0, "noise": 0, "error": 0, "other": 0})

    for row in rows:
        event_at = row.get("event_at")
        if not event_at:
            continue
        day = _to_et_date(event_at)
        cls = classify_event(row.get("event_type"))
        by_day[day][cls] += 1

    days_out: list[dict[str, Any]] = []
    cursor = start_et
    while cursor <= today_et:
        key = cursor.isoformat()
        counts = by_day.get(key, {"signal": 0, "noise": 0, "error": 0, "other": 0})
        total = counts["signal"] + counts["noise"] + counts["error"] + counts["other"]
        noise_pct = round(100.0 * counts["noise"] / total, 1) if total > 0 else 0.0
        days_out.append({
            "date": key,
            "signal": counts["signal"],
            "noise": counts["noise"],
            "error": counts["error"],
            "other": counts["other"],
            "total": total,
            "noise_pct": noise_pct,
            "alarm": noise_pct > ALARM_THRESHOLD_PCT,
        })
        cursor += timedelta(days=1)

    week_start = today_et - timedelta(days=6)
    week_signal = 0
    week_noise = 0
    week_error = 0
    week_other = 0
    for d in days_out:
        if d["date"] >= week_start.isoformat():
            week_signal += d["signal"]
            week_noise += d["noise"]
            week_error += d["error"]
            week_other += d["other"]
    week_total = week_signal + week_noise + week_error + week_other
    week_noise_pct = round(100.0 * week_noise / week_total, 1) if week_total > 0 else 0.0

    return {
        "days": days_out,
        "alarm_threshold_pct": ALARM_THRESHOLD_PCT,
        "current_week_noise_pct": week_noise_pct,
    }


@router.get("/daily/{date}/events", dependencies=[Depends(require_token)])
async def snr_daily_events(date: str, limit: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    """Top N signal events for a given ET date — drives the click-modal."""
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
    query = (
        "select=event_at,event_type,surface,summary"
        f"&event_at=gte.{start_iso}"
        f"&event_at=lt.{end_iso}"
        f"&event_type=in.({signal_list})"
        "&order=event_at.desc"
        f"&limit={limit}"
    )
    cache_key = f"snr:daily-events:{date}:{limit}"
    try:
        rows = await sb.select("clark_watch_details", query, cache_key=cache_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    signal_events = [r for r in rows if classify_event(r.get("event_type")) == "signal"]

    return {
        "date": date,
        "events": [
            {
                "event_at": r.get("event_at"),
                "event_type": r.get("event_type"),
                "surface": r.get("surface"),
                "summary": (r.get("summary") or "")[:400],
            }
            for r in signal_events
        ],
    }
