"""FastAPI app entry. Phase 0 mounts /health; Phase 1+ mount widget routes."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ClarkWatch API",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["X-ClarkWatch-Token", "Content-Type"],
        max_age=600,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": __version__,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    try:
        from .routes import snr

        app.include_router(snr.router, prefix="/snr")
    except ImportError:
        pass

    try:
        from .routes import cascade

        app.include_router(cascade.router, prefix="/cascade")
    except ImportError:
        pass

    try:
        from .routes import agents

        app.include_router(agents.router, prefix="/agents")
    except ImportError:
        pass

    try:
        from .routes import agent_card

        app.include_router(agent_card.router, prefix="/agents")
    except ImportError:
        pass

    try:
        from .routes import meditation

        app.include_router(meditation.router, prefix="/meditation")
    except ImportError:
        pass

    try:
        from .routes import calendar

        app.include_router(calendar.router, prefix="/calendar")
    except ImportError:
        pass

    return app


app = create_app()
