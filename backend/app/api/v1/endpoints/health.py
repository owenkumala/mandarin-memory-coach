"""Health endpoint for backend, fake-Qwen, and database diagnostics."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return backend status and configuration details safe for clients."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        project_name=settings.APP_NAME,
        use_fake_qwen=settings.USE_FAKE_QWEN,
        database_type=settings.database_type,
    )
