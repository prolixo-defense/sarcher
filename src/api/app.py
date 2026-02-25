import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import leads, tasks, campaigns, compliance, workflows, dashboard, discover

logger = logging.getLogger(__name__)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Networking Engine API",
        description="B2B networking extraction engine — Phases 1-5",
        version="5.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(leads.router)
    app.include_router(tasks.router)
    app.include_router(campaigns.router)
    app.include_router(compliance.router)
    app.include_router(workflows.router)
    app.include_router(dashboard.router)
    app.include_router(discover.router)

    # Serve static assets (JS, CSS, images if any)
    if os.path.isdir(_STATIC_DIR):
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard() -> FileResponse:
        """Serve the React dashboard at the root URL."""
        index = os.path.join(_STATIC_DIR, "index.html")
        return FileResponse(index)

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "version": "5.0.0"}

    @app.on_event("startup")
    def on_startup():
        _run_migrations()

    return app


def _run_migrations():
    try:
        from alembic.config import Config
        from alembic import command

        # Find alembic.ini relative to project root
        ini_path = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
        ini_path = os.path.abspath(ini_path)
        if os.path.exists(ini_path):
            alembic_cfg = Config(ini_path)
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations applied.")
        else:
            logger.warning("alembic.ini not found at %s, skipping migrations.", ini_path)
    except Exception as e:
        logger.warning("Migration error (non-fatal): %s", e)


app = create_app()
