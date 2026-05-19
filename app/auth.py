"""X-ClarkWatch-Token header auth for widget endpoints."""

from fastapi import Header, HTTPException, status

from .config import get_settings


async def require_token(x_clarkwatch_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not x_clarkwatch_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-ClarkWatch-Token header",
        )
    if x_clarkwatch_token != settings.clarkwatch_api_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-ClarkWatch-Token",
        )
