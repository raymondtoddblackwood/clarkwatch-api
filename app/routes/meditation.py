"""Phase 5 — Contradiction Backlog Trendline.

Per spec section 8.5: pulls meditation_reports for a rolling window and
returns daily counts of contradictions found vs resolved, plus
artifacts_validated/failed and corrections_detected. The widget draws a
two-line chart with the gap between found and resolved shaded as backlog.

Alarms fire when (a) resolved is flat at zero across the entire window
while contradictions are being found (the Meditation v2 promotion gap the
audit flagged) or (b) artifact_failures exceed validations.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_token
from ..clients.supabase import get_supabase_client

router = APIRouter()


@router.get("/backlog", dependencies=[Depends(require_token)])
async def meditation_backlog(days: int = Query(default=30, ge=1, le=180)) -> dict[str, Any]:
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)

    sb = get_supabase_client()
    query = (
        "select=report_date,contradictions_found,contradictions_resolved,"
        "artifacts_validated,artifacts_failed,corrections_detected"
        f"&report_date=gte.{start.isoformat()}"
        f"&report_date=lte.{today.isoformat()}"
        "&order=report_date.asc"
    )
    cache_key = f"meditation:backlog:{days}:{start}:{today}"

    try:
        rows = await sb.select_paginated(
            "meditation_reports", query, cache_key=cache_key
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    by_date: dict[str, dict[str, int]] = {}
    for r in rows:
        d = r.get("report_date")
        if not d:
            continue
        by_date[d] = {
            "found": int(r.get("contradictions_found") or 0),
            "resolved": int(r.get("contradictions_resolved") or 0),
            "validated": int(r.get("artifacts_validated") or 0),
            "failed": int(r.get("artifacts_failed") or 0),
            "corrections": int(r.get("corrections_detected") or 0),
        }

    days_out: list[dict[str, Any]] = []
    cursor = start
    while cursor <= today:
        iso = cursor.isoformat()
        rec = by_date.get(iso)
        if rec is None:
            days_out.append({
                "date": iso,
                "found": 0,
                "resolved": 0,
                "validated": 0,
                "failed": 0,
                "corrections": 0,
                "missing_report": True,
            })
        else:
            days_out.append({
                "date": iso,
                "found": rec["found"],
                "resolved": rec["resolved"],
                "validated": rec["validated"],
                "failed": rec["failed"],
                "corrections": rec["corrections"],
                "missing_report": False,
            })
        cursor += timedelta(days=1)

    totals = {
        "found": sum(d["found"] for d in days_out),
        "resolved": sum(d["resolved"] for d in days_out),
        "validated": sum(d["validated"] for d in days_out),
        "failed": sum(d["failed"] for d in days_out),
        "corrections": sum(d["corrections"] for d in days_out),
    }
    totals["backlog"] = max(totals["found"] - totals["resolved"], 0)

    missing_count = sum(1 for d in days_out if d["missing_report"])
    reports_count = days - missing_count

    alarms: list[str] = []
    if totals["found"] > 0 and totals["resolved"] == 0:
        alarms.append(
            f"resolved=0 across all {reports_count} reports — "
            "Meditation finding contradictions but not closing them"
        )
    if totals["failed"] > 0 and totals["validated"] == 0:
        alarms.append(
            f"{totals['failed']} artifact failures and 0 validations — "
            "validation loop has not yet fired"
        )
    if missing_count > 0:
        alarms.append(
            f"{missing_count} day{'s' if missing_count != 1 else ''} missing a meditation_report in window"
        )

    return {
        "days": days_out,
        "totals": totals,
        "alarms": alarms,
        "window": {
            "days": days,
            "start": start.isoformat(),
            "end": today.isoformat(),
            "reports": reports_count,
            "missing": missing_count,
        },
    }


@router.get("/backlog/{report_date}", dependencies=[Depends(require_token)])
async def meditation_backlog_report(report_date: str) -> dict[str, Any]:
    """Single meditation_report.markdown for click-to-expand modal."""
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid date: {e}") from e

    sb = get_supabase_client()
    query = (
        "select=report_date,report_markdown,contradictions_found,"
        "contradictions_resolved,artifacts_validated,artifacts_failed,"
        "corrections_detected,day_type,created_at"
        f"&report_date=eq.{report_date}"
        "&limit=1"
    )
    cache_key = f"meditation:report:{report_date}"
    try:
        rows = await sb.select("meditation_reports", query, cache_key=cache_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    if not rows:
        raise HTTPException(status_code=404, detail=f"no meditation_report for {report_date}")
    r = rows[0]
    return {
        "report_date": r.get("report_date"),
        "day_type": r.get("day_type"),
        "created_at": r.get("created_at"),
        "metrics": {
            "found": r.get("contradictions_found"),
            "resolved": r.get("contradictions_resolved"),
            "validated": r.get("artifacts_validated"),
            "failed": r.get("artifacts_failed"),
            "corrections": r.get("corrections_detected"),
        },
        "markdown": r.get("report_markdown") or "",
    }
