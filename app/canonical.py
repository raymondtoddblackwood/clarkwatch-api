"""Canonical filter — single source of truth for every widget.

Per spec §1.2: surface normalization + signal/noise/error event classification.
Every widget that filters for "story events" uses these constants and helpers.
Get this wrong here and every widget shows different numbers.
"""

from __future__ import annotations

# ----- Surface normalization -----------------------------------------------

# Raw clark_watch_details.surface values seen in production map to a small set
# of canonical agent names. New variants get added here; anything unmapped
# falls through to "other".
SURFACE_MAP: dict[str, str] = {
    "clark_trader": "trader",
    "clark_trader_(n8n)": "trader",
    "clark_trader_maverick": "trader",
    "trading": "trader",
    "clark_code_builder": "code_builder",
    "clark_code_builder_(n8n)": "code_builder",
    "clark_code": "code_builder",
    "n8n": "n8n",
    "clark_web_master": "website",
    "website": "website",
    "meditation": "meditation",
    "clark_columnist": "columnist",
    "columnist": "columnist",
    "clark_newsletter": "newsletter",
    "newsletter": "newsletter",
    "clark_linkedin": "linkedin",
    "linkedin": "linkedin",
    "clark_console": "console",
    "console": "console",
    "heartbeat": "heartbeat",
}

CANONICAL_AGENTS: list[str] = [
    "trader",
    "n8n",
    "website",
    "meditation",
    "columnist",
    "newsletter",
    "linkedin",
    "console",
    "code_builder",
    "heartbeat",
]


def normalize_surface(raw: str | None) -> str:
    if not raw:
        return "other"
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return SURFACE_MAP.get(key, "other")


# ----- Event type classification -------------------------------------------

NOISE_EVENT_TYPES: frozenset[str] = frozenset({
    "heartbeat_alive",
    "intraday_overlay_served",
    "trading_docs_synced",
    "heartbeat",
    "backup_synced",
    "routine_triggered",
    "surface_init",
    "session_start",
    "session_end",
})

SIGNAL_EVENT_TYPES: frozenset[str] = frozenset({
    "milestone", "decision", "creation", "note", "plan", "win", "vision",
    "trade_executed", "blog_published", "deployment_triggered", "page_updated",
    "meditation_complete", "meditation_edit", "coaching_applied",
    "trading_learning", "workflow_modified", "strategy_adjusted",
    "workflow_built", "strategy_check", "execution_summary",
    "strategy_generated", "trade_patched", "daily_shutdown", "eod_summary",
    "surface_boundary_observation", "surface_boundary_violation",
})


def classify_event(event_type: str | None) -> str:
    """Return one of: 'noise', 'signal', 'error', 'other'."""
    if not event_type:
        return "other"
    if event_type in NOISE_EVENT_TYPES:
        return "noise"
    if event_type == "error" or event_type.endswith("_failed"):
        return "error"
    if event_type in SIGNAL_EVENT_TYPES:
        return "signal"
    return "other"
