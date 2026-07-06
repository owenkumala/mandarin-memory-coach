"""Voice-chat endpoint that runs the fake-Qwen memory coaching pipeline."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db
from app.schemas import VoiceChatResponse
from app.services.lesson_service import create_lesson_plan
from app.services.memory_service import (
    get_memory,
    get_or_create_user,
    save_mistakes,
    save_session,
    update_active_weaknesses,
)
from app.services.qwen_client import QwenClient
from app.utils.audio import build_audio_file_path, storage_url, write_audio_bytes

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
    """Run upload, fake Qwen, persistence, memory update, and response assembly."""
    settings = get_settings()
    qwen_client = QwenClient(settings=settings)

    try:
        # Persist the learner audio before analysis so each session has raw memory.
        audio_path = build_audio_file_path(settings.USER_AUDIO_DIR, user_id, audio.filename or "audio.webm")
        audio_content = await audio.read()
        saved_audio_path = await write_audio_bytes(audio_path, audio_content)

        # Ensure learner metadata exists before reading or mutating memory.
        get_or_create_user(db, user_id=user_id, mandarin_level=level)
        memory_before = get_memory(db, user_id=user_id)

        transcript = await qwen_client.transcribe_audio(saved_audio_path)
        tutor_reply = await qwen_client.generate_tutor_reply(
            transcript=transcript,
            memory=memory_before,
            scenario=scenario,
            level=level,
        )
        analysis = await qwen_client.analyze_mistakes(
            transcript=transcript,
            scenario=scenario,
            level=level,
        )

        # Store raw session and structured mistakes before recomputing working memory.
        session = save_session(
            db,
            user_id=user_id,
            scenario=scenario,
            transcript=transcript,
            tutor_reply=tutor_reply,
            summary=analysis.summary,
            audio_path=saved_audio_path,
        )
        save_mistakes(db, user_id=user_id, session_id=session.id, mistakes=analysis.mistakes)
        update_active_weaknesses(db, user_id=user_id, mistakes=analysis.mistakes)
        memory_after_weakness_update = get_memory(db, user_id=user_id)
        create_lesson_plan(
            db,
            user_id=user_id,
            analysis=analysis,
            memory=memory_after_weakness_update,
            scenario=scenario,
        )

        tutor_audio_path = build_audio_file_path(settings.TUTOR_AUDIO_DIR, user_id, "reply.mp3")
        synthesized_path = await qwen_client.synthesize_speech(tutor_reply, str(tutor_audio_path))
        tutor_audio_url = (
            storage_url(synthesized_path, settings.STORAGE_DIR)
            if synthesized_path is not None
            else None
        )
        memory_after = get_memory(db, user_id=user_id)

        return VoiceChatResponse(
            user_id=user_id,
            scenario=scenario,
            level=level,
            transcript=transcript,
            tutor_reply=tutor_reply,
            tutor_audio_url=tutor_audio_url,
            feedback=analysis,
            memory_before=memory_before,
            memory_after=memory_after,
            memory_updated=True,
        )
    except (OSError, ValueError, NotImplementedError) as exc:
        logger.exception("Voice-chat pipeline failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice-chat pipeline failed: {exc}",
        ) from exc
