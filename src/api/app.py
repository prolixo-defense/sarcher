import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import leads, tasks, campaigns, compliance, workflows, dashboard

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Networking Engine API",
        description="B2B networking extraction engine — Phases 1-4",
        version="4.0.0",
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

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "version": "0.1.0"}

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
