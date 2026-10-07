from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.files import router as files_router
from app.config import Settings
from app.database import Base, make_engine, make_session_factory
from app import models  # noqa: F401  (register tables)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings.resolved_database_url)
    Base.metadata.create_all(engine)

    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        description="Upload a KML or zipped Shapefile and get area / length measurements.",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.include_router(files_router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


logging.basicConfig(level=logging.INFO)
app = create_app()
