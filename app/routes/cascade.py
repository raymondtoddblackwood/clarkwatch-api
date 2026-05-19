"""Phase 2 — Cascade Waterfall endpoint.

Per spec section 8.4: walk every Monday in the requested range and report what
exists at each summary grain (day/week/month/quarter) plus whether raw details
exist at all. Surfaces the gap that prompted this entire build — the missing
2026-04-27 weekly summary that hid for 22 days.

We fetch every clark_watch_summaries row in the window in one paginated read
and bucket them in app code. Quarterly is included for forward compatibility
even though no quarter summaries exist yet.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_token
from ..clients.supabase import get_supabase_client

router = APIRouter()


def _previous_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@router.get("/health", dependencies=[Depends(require_token)])
async def cascade_health(
    start: str = Query(default="", description="YYYY-MM-DD; defaults to 8 weeks ago"),
    end: str = Query(default="", description="YYYY-MM-DD; defaults to today"),
) -> dict[str, Any]:
    today = datetime.now().date()
    try:
        end_d = _parse_iso_date(end) if end else today
        start_d = _parse_iso_date(start) if start else (today - timedelta(weeks=8))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad date: {e}") from e

    if start_d > end_d:
        raise HTTPException(status_code=400, detail="start must be <= end")

    week_start = _previous_monday(start_d)
    weeks: list[date] = []
    while week_start <= end_d:
        weeks.append(week_start)
        week_start += timedelta(days=7)

    sb = get_supabase_client()

    # Overlap filter — a summary "covers" the range if its window touches the
    # requested window at all. Filtering by period_start>=range_start would
    # silently drop month/quarter summaries that start before the range.
    range_start_iso = weeks[0].isoformat()
    range_end_iso = (weeks[-1] + timedelta(days=6)).isoformat()
    summaries_query = (
        "select=period_type,period_start,period_end"
        f"&period_end=gte.{range_start_iso}"
        f"&period_start=lte.{range_end_iso}"
        "&order=period_start.desc"
    )
    try:
        summaries = await sb.select_paginated(
            "clark_watch_summaries",
            summaries_query,
            cache_key=f"cascade:summaries:{weeks[0]}:{weeks[-1]}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase summaries fetch failed: {e}") from e

    # Index by (type, start)
    by_type_start: dict[tuple[str, str], dict[str, Any]] = {}
    for s in summaries:
        by_type_start[(s["period_type"], s["period_start"])] = s

    # Quick "any details" check — single 1-row probe at the start of the
    # earliest week. Cheaper than 8 separate per-week probes; if events exist
    # at the earliest week start they exist later too. Good enough for v1.
    earliest_iso = f"{weeks[0].isoformat()}T00:00:00Z"
    try:
        probe = await sb.select(
            "clark_watch_details",
            f"select=event_at&event_at=gte.{earliest_iso}&limit=1",
            cache_key=f"cascade:probe:{weeks[0]}",
        )
        any_details = len(probe) > 0
    except Exception:
        any_details = True  # don't block the widget on a probe failure

    def covers(period: dict[str, Any], week_start: date) -> bool:
        ps = _parse_iso_date(period["period_start"])
        pe = _parse_iso_date(period["period_end"])
        week_end = week_start + timedelta(days=6)
        return ps <= week_end and pe >= week_start

    weeks_out: list[dict[str, Any]] = []
    alarms: list[dict[str, Any]] = []

    for w in weeks:
        w_iso = w.isoformat()
        daily_count = sum(
            1
            for s in summaries
            if s["period_type"] == "day"
            and _parse_iso_date(s["period_start"]) >= w
            and _parse_iso_date(s["period_start"]) <= w + timedelta(days=6)
        )
        has_weekly = ("week", w_iso) in by_type_start
        has_monthly = any(s for s in summaries if s["period_type"] == "month" and covers(s, w))
        has_quarterly = any(s for s in summaries if s["period_type"] == "quarter" and covers(s, w))

        weeks_out.append({
            "week_start": w_iso,
            "week_end": (w + timedelta(days=6)).isoformat(),
            "has_details": any_details,
            "daily_count": daily_count,
            "has_weekly": has_weekly,
            "has_monthly": has_monthly,
            "has_quarterly": has_quarterly,
        })

    # Alarms: a missing weekly inside a window where neighboring weeks have
    # weeklies is a silent gap and the entire reason this widget exists.
    for i, wk in enumerate(weeks_out):
        if not wk["has_weekly"]:
            week_start_d = _parse_iso_date(wk["week_start"])
            week_end_d = _parse_iso_date(wk["week_end"])
            if week_end_d >= today:
                continue  # current week — not yet expected
            days_overdue = (today - week_end_d).days
            has_neighbor = any(
                weeks_out[j]["has_weekly"]
                for j in (i - 1, i + 1)
                if 0 <= j < len(weeks_out)
            )
            if has_neighbor and days_overdue > 0:
                alarms.append({
                    "grain": "weekly",
                    "missing": f"{wk['week_start']} to {wk['week_end']}",
                    "days_overdue": days_overdue,
                })

    # Daily-summary gaps for completed weeks (less critical, but visible)
    for wk in weeks_out:
        week_end_d = _parse_iso_date(wk["week_end"])
        if week_end_d >= today:
            continue
        if wk["daily_count"] < 7:
            missing = 7 - wk["daily_count"]
            alarms.append({
                "grain": "daily",
                "missing": f"{wk['week_start']} to {wk['week_end']}",
                "missing_count": missing,
                "days_overdue": (today - week_end_d).days,
            })

    return {
        "weeks": weeks_out,
        "alarms": alarms,
        "today": today.isoformat(),
        "range": {"start": start_d.isoformat(), "end": end_d.isoformat()},
    }
