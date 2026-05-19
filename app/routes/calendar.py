"""Phase 6 — Day-Type Compass.

Per spec section 8.6. Returns a per-day record for the requested window,
each day carrying its meditation_reports.day_type, normalized rationale,
and a few counters. Missing reports return as null day_type so the widget
can render them as light grey instead of dropping them.

Production has two day_type schemas in the wild:
  * Newer rows: {"type": "Build", "rationale": "...", "evidence": [...]}
  * Older rows: {"type": "Build Day", "errors": 0, "milestones": 2, ...}

Normalize 'Build Day' -> 'Build' and 'Correction Day' -> 'Correction' on
the way out so the frontend can paint one color per canonical type.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_token
from ..clients.supabase import get_supabase_client

router = APIRouter()


def _canonical_day_type(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    if s.lower() == "build day":
        return "Build"
    if s.lower() == "correction day":
        return "Correction"
    return s  # Build / Correction / Record / Grind / Rest / etc.


@router.get("/day-types", dependencies=[Depends(require_token)])
async def calendar_day_types(
    start: str = Query(default="", description="YYYY-MM-DD; defaults to 13 weeks ago"),
    end: str = Query(default="", description="YYYY-MM-DD; defaults to today"),
) -> dict[str, Any]:
    today = datetime.now().date()
    try:
        end_d = datetime.strptime(end, "%Y-%m-%d").date() if end else today
        start_d = (
            datetime.strptime(start, "%Y-%m-%d").date() if start else today - timedelta(weeks=13)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad date: {e}") from e

    if start_d > end_d:
        raise HTTPException(status_code=400, detail="start must be <= end")

    sb = get_supabase_client()
    query = (
        "select=report_date,day_type,day_score,contradictions_found,corrections_detected"
        f"&report_date=gte.{start_d.isoformat()}"
        f"&report_date=lte.{end_d.isoformat()}"
        "&order=report_date.asc"
    )
    cache_key = f"calendar:day-types:{start_d}:{end_d}"

    try:
        rows = await sb.select_paginated(
            "meditation_reports", query, cache_key=cache_key
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    by_date: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = r.get("report_date")
        if not d:
            continue
        score = r.get("day_score") or {}
        # day_type column wins; fall back to day_score.type for legacy rows
        raw_type = r.get("day_type") or score.get("type")
        canonical = _canonical_day_type(raw_type)
        rationale = score.get("rationale")
        if not rationale and "errors" in score:
            # Old schema — synthesize a one-liner from the counters
            parts = []
            for k in ("milestones", "creations", "corrections", "errors"):
                v = score.get(k)
                if v:
                    parts.append(f"{k}={v}")
            rationale = ", ".join(parts) or None

        by_date[d] = {
            "day_type": canonical,
            "raw_day_type": raw_type,
            "rationale": rationale,
            "contradictions_found": int(r.get("contradictions_found") or 0),
            "corrections_detected": int(r.get("corrections_detected") or 0),
        }

    days_out: list[dict[str, Any]] = []
    cursor = start_d
    while cursor <= end_d:
        iso = cursor.isoformat()
        rec = by_date.get(iso)
        if rec is None:
            days_out.append({
                "date": iso,
                "weekday": cursor.weekday(),  # 0 = Monday
                "day_type": None,
                "rationale": None,
                "missing_report": True,
                "contradictions_found": 0,
                "corrections_detected": 0,
            })
        else:
            days_out.append({
                "date": iso,
                "weekday": cursor.weekday(),
                "day_type": rec["day_type"],
                "raw_day_type": rec.get("raw_day_type"),
                "rationale": rec["rationale"],
                "missing_report": False,
                "contradictions_found": rec["contradictions_found"],
                "corrections_detected": rec["corrections_detected"],
            })
        cursor += timedelta(days=1)

    counts = Counter(d["day_type"] for d in days_out if d["day_type"])

    return {
        "days": days_out,
        "counts": dict(counts),
        "missing_count": sum(1 for d in days_out if d["missing_report"]),
        "window": {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "days": (end_d - start_d).days + 1,
        },
    }
