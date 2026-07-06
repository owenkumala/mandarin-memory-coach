"""Voice-chat endpoint that runs the fake-Qwen memory coaching pipeline."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas import VoiceChatResponse
from app.services.voice_chat_service import run_voice_chat_pipeline
from app.utils.audio import AudioValidationError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice-chat"])


@router.post("/voice-chat", response_model=VoiceChatResponse)
async def voice_chat(
    audio: UploadFile = File(...),
    user_id: str = Form("demo-user"),
    scenario: str = Form("restaurant ordering"),
    level: str = Form("HSK1 beginner"),
    db: Session = Depends(get_db),
) -> VoiceChatResponse:
    """Delegate voice-chat orchestration to the service layer."""
    try:
        return await run_voice_chat_pipeline(
            db=db,
            audio=audio,
            user_id=user_id,
            scenario=scenario,
            level=level,
        )
    except AudioValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except (OSError, ValueError, NotImplementedError) as exc:
        logger.exception("Voice-chat pipeline failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice-chat pipeline failed: {exc}",
        ) from exc
