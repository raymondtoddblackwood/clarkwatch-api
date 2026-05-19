"""Phase 4 — Pokemon Card Lifetime Stats Extension.

Per spec section 8.3 — single-agent lifetime stats served to the rich Agent
Card flip-back. Endpoint accepts either a canonical agent name ('trader',
'website', ...) or any raw surface variant the canonical map knows about
('Clark Trader', 'Clark Web Master', ...). The frontend can therefore pass
the SURFACE_META key without translating.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
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

# How long ago a longest_streak still counts as "this season". Keeps the
# holographic shiny from being permanently locked to one historical run.
SEASON_DAYS = 180


def _to_et_date(event_at_iso: str) -> str:
    dt = datetime.fromisoformat(event_at_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().isoformat()


def _human_last_spoken(last: datetime | None, now_et: datetime) -> str:
    if last is None:
        return "never"
    delta_seconds = (now_et - last).total_seconds()
    if delta_seconds < 0:
        delta_seconds = 0
    today_et = now_et.date()
    last_d = last.date()
    if last_d == today_et:
        return "today, " + last.strftime("%-I:%M %p ET").lstrip("0") if hasattr(datetime, "strftime") else last.strftime("%I:%M %p ET").lstrip("0")
    if last_d == today_et - timedelta(days=1):
        return "yesterday"
    days = (today_et - last_d).days
    if days < 7:
        return f"{days} days ago"
    if days < 60:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = days // 30
    return f"{months} month{'s' if months != 1 else ''} ago"


def _compute_streaks(signal_dates: set[str], today_et) -> tuple[int, int]:
    """Return (current_streak_days, longest_streak_days)."""
    if not signal_dates:
        return 0, 0
    sorted_dates = sorted(signal_dates)
    longest = 0
    run = 0
    prev = None
    for d_iso in sorted_dates:
        d = datetime.strptime(d_iso, "%Y-%m-%d").date()
        if prev is None or (d - prev).days == 1:
            run += 1
        else:
            longest = max(longest, run)
            run = 1
        prev = d
    longest = max(longest, run)

    # Current streak: count backward from today
    current = 0
    cursor = today_et
    while cursor.isoformat() in signal_dates:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def _pick_voice_sample(rows: list[dict[str, Any]]) -> str | None:
    """Most recent signal row with a meaty summary (>80 chars)."""
    for row in rows:
        s = row.get("summary") or ""
        if classify_event(row.get("event_type")) == "signal" and len(s) > 80:
            return s
    return None


@router.get("/card/{surface}", dependencies=[Depends(require_token)])
async def agent_card(
    surface: str = Path(..., description="Canonical name or raw surface"),
) -> dict[str, Any]:
    agent = normalize_surface(surface)
    if agent == "other":
        # Accept both the canonical token directly (already normalized) and any
        # raw variant. The normalize call already returns 'other' for unknowns.
        if surface in CANONICAL_AGENTS:
            agent = surface
        else:
            raise HTTPException(status_code=404, detail=f"unknown surface: {surface}")

    sb = get_supabase_client()
    now_utc = datetime.now(timezone.utc)
    now_et = datetime.now(ET)
    today_et = now_et.date()
    sparkline_start = today_et - timedelta(days=29)

    signal_list = ",".join(sorted(SIGNAL_EVENT_TYPES))

    # Pull every signal row for this surface across all time. For verbose
    # agents (trader, meditation) this can be a few thousand rows; pagination
    # caps at 60k. Cached 5 min per agent.
    base_query = (
        "select=event_at,event_type,surface,summary"
        f"&event_type=in.({signal_list})"
        "&order=event_at.desc"
    )
    cache_key = f"agents:card:{agent}"
    try:
        rows = await sb.select_paginated(
            "clark_watch_details", base_query, cache_key=cache_key
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"supabase fetch failed: {e}") from e

    mine = [r for r in rows if normalize_surface(r.get("surface")) == agent]

    if not mine:
        return {
            "surface": agent,
            "lifetime_signal": 0,
            "signature_event": None,
            "last_spoken_iso": None,
            "last_spoken_human": "never",
            "streak_days": 0,
            "longest_streak_days": 0,
            "sparkline_30d": [0] * 30,
            "voice_sample": None,
            "shiny": {"tier": "shadow", "reason": "no signal events on record"},
        }

    lifetime = len(mine)
    type_counter: Counter[str] = Counter(r.get("event_type") for r in mine if r.get("event_type"))
    signature_event = type_counter.most_common(1)[0][0] if type_counter else None

    last_row = mine[0]  # rows are desc
    last_dt = datetime.fromisoformat(last_row["event_at"].replace("Z", "+00:00")).astimezone(ET)
    last_iso = last_row["event_at"]
    last_human = _human_last_spoken(last_dt, now_et)

    signal_dates = {_to_et_date(r["event_at"]) for r in mine if r.get("event_at")}
    streak, longest_streak = _compute_streaks(signal_dates, today_et)

    sparkline = []
    for i in range(30):
        d = (sparkline_start + timedelta(days=i)).isoformat()
        sparkline.append(sum(1 for r in mine if _to_et_date(r["event_at"]) == d))

    voice = _pick_voice_sample(mine)

    # Shiny tier
    silent_days = (today_et - last_dt.date()).days
    season_cutoff = today_et - timedelta(days=SEASON_DAYS)
    shiny_tier = "common"
    shiny_reason = "default"
    if silent_days >= 30:
        shiny_tier = "shadow"
        shiny_reason = f"silent {silent_days} days"
    elif streak >= 5:
        shiny_tier = "radiant"
        shiny_reason = f"{streak}-day active streak"
    if longest_streak >= 14 and last_dt.date() >= season_cutoff:
        shiny_tier = "holographic"
        shiny_reason = f"longest streak this season ({longest_streak} days)"
    if agent == "trader" and lifetime >= 1000:
        # Trader is the workhorse — keep the holo unless gone dark
        if silent_days < 30:
            shiny_tier = "holographic"
            shiny_reason = f"lifetime workhorse ({lifetime} signal events)"

    return {
        "surface": agent,
        "lifetime_signal": lifetime,
        "signature_event": signature_event,
        "last_spoken_iso": last_iso,
        "last_spoken_human": last_human,
        "streak_days": streak,
        "longest_streak_days": longest_streak,
        "silent_days": silent_days,
        "sparkline_30d": sparkline,
        "voice_sample": (voice[:300] if voice else None),
        "shiny": {"tier": shiny_tier, "reason": shiny_reason},
    }
