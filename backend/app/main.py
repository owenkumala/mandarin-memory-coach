"""FastAPI application factory for the SpeakHan backend API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.database import create_database_tables
from app.utils.audio import ensure_storage_directories


def configure_application_logging() -> None:
    """Expose app INFO logs through uvicorn's terminal logging handlers."""
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)

    # Uvicorn owns terminal formatting; reuse its handler so app timing logs
    # appear beside access logs without adding duplicate root handlers.
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    if uvicorn_error_logger.handlers:
        app_logger.handlers = uvicorn_error_logger.handlers
        app_logger.propagate = False
    else:
        logging.basicConfig(level=logging.INFO)

    logging.getLogger("app.services.voice_chat_service").setLevel(logging.INFO)
    logging.getLogger("app.services.qwen_client").setLevel(logging.INFO)


def create_app() -> FastAPI:
    """Create and configure the FastAPI app without business logic."""
    configure_application_logging()
    settings = get_settings()
    ensure_storage_directories(
        settings.STORAGE_DIR,
        settings.USER_AUDIO_DIR,
        settings.TUTOR_AUDIO_DIR,
    )
    create_database_tables()

    app = FastAPI(title=settings.APP_NAME)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/storage", StaticFiles(directory=settings.STORAGE_DIR), name="storage")
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
