"""Voice-chat orchestration service for the fake-Qwen memory pipeline.

This module keeps the endpoint thin while coordinating audio persistence,
Qwen calls, session storage, weakness updates, lesson-plan creation, and the
final response assembly.
"""

import logging
import time
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
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
from app.utils.audio import (
    build_audio_file_path,
    storage_url,
    validate_audio_upload,
    write_audio_bytes,
)

logger = logging.getLogger(__name__)


async def run_voice_chat_pipeline(
    db: Session,
    audio: UploadFile,
    user_id: str,
    scenario: str,
    level: str,
) -> VoiceChatResponse:
    """Run the complete voice-chat pipeline and return the API response."""
    pipeline_started_at = time.perf_counter()
    settings = get_settings()
    qwen_client = QwenClient(settings=settings)

    # Persist learner audio first so raw session memory exists even in fake mode.
    read_started_at = time.perf_counter()
    audio_content = await audio.read()
    _log_elapsed("voice_chat.read_audio_seconds", read_started_at)

    save_started_at = time.perf_counter()
    audio_path = build_audio_file_path(
        settings.USER_AUDIO_DIR,
        user_id,
        audio.filename or "audio.webm",
    )
    validate_audio_upload(
        audio.filename or "",
        audio_content,
        settings.MAX_AUDIO_UPLOAD_BYTES,
    )
    saved_audio_path = await write_audio_bytes(audio_path, audio_content)
    _log_elapsed("voice_chat.validate_save_audio_seconds", save_started_at)

    # Load memory before generating the reply so Qwen can adapt to past mistakes.
    get_or_create_user(db, user_id=user_id, mandarin_level=level)
    memory_before = get_memory(db, user_id=user_id)

    asr_started_at = time.perf_counter()
    transcript = await qwen_client.transcribe_audio(saved_audio_path)
    _log_elapsed("voice_chat.transcribe_seconds", asr_started_at)

    feedback_started_at = time.perf_counter()
    tutor_reply, analysis = await qwen_client.generate_tutor_turn(
        transcript=transcript,
        memory=memory_before,
        scenario=scenario,
        level=level,
    )
    _log_elapsed("voice_chat.generate_feedback_seconds", feedback_started_at)

    # Store raw and structured memory before computing the updated working state.
    session_started_at = time.perf_counter()
    session = save_session(
        db,
        user_id=user_id,
        scenario=scenario,
        transcript=transcript,
        tutor_reply=tutor_reply,
        summary=analysis.summary,
        audio_path=saved_audio_path,
    )
    _log_elapsed("voice_chat.save_session_seconds", session_started_at)

    mistakes_started_at = time.perf_counter()
    save_mistakes(db, user_id=user_id, session_id=session.id, mistakes=analysis.mistakes)
    _log_elapsed("voice_chat.save_mistakes_seconds", mistakes_started_at)

    weaknesses_started_at = time.perf_counter()
    update_active_weaknesses(db, user_id=user_id, mistakes=analysis.mistakes)
    _log_elapsed("voice_chat.update_weaknesses_seconds", weaknesses_started_at)

    memory_after_weakness_update = get_memory(db, user_id=user_id)

    lesson_started_at = time.perf_counter()
    create_lesson_plan(
        db,
        user_id=user_id,
        analysis=analysis,
        memory=memory_after_weakness_update,
        scenario=scenario,
    )
    _log_elapsed("voice_chat.create_lesson_plan_seconds", lesson_started_at)

    tts_started_at = time.perf_counter()
    tutor_audio_url = await _generate_tutor_audio_url(
        qwen_client=qwen_client,
        tutor_reply=tutor_reply,
        user_id=user_id,
    )
    _log_elapsed("voice_chat.tts_seconds", tts_started_at)

    memory_after = get_memory(db, user_id=user_id)

    response = VoiceChatResponse(
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
    _log_elapsed("voice_chat.total_seconds", pipeline_started_at)
    return response


async def _generate_tutor_audio_url(
    qwen_client: QwenClient,
    tutor_reply: str,
    user_id: str,
) -> str | None:
    """Run optional TTS and convert a generated file path to a storage URL."""
    settings = get_settings()
    tutor_audio_path = _build_tutor_audio_path(
        settings.TUTOR_AUDIO_DIR,
        user_id,
        settings.QWEN_TTS_OUTPUT_FORMAT,
    )
    try:
        synthesized_path = await qwen_client.synthesize_speech(
            tutor_reply,
            str(tutor_audio_path),
        )
    except ValueError as exc:
        logger.warning("voice_chat.tts_fallback reason=%s", exc)
        return None
    if synthesized_path is None:
        return None
    return storage_url(synthesized_path, settings.STORAGE_DIR)


def _build_tutor_audio_path(
    tutor_audio_dir: str,
    user_id: str,
    output_format: str,
) -> Path:
    """Return a user-scoped tutor audio path with a strong unique filename."""
    safe_user_id = _safe_path_segment(user_id)
    extension = _tutor_audio_extension(output_format)
    return Path(tutor_audio_dir) / safe_user_id / f"reply-{uuid4().hex}.{extension}"


def _safe_path_segment(value: str) -> str:
    """Normalize user-provided path segments for local storage paths."""
    safe_value = "".join(
        character for character in value if character.isalnum() or character in "-_"
    )
    return safe_value or "user"


def _tutor_audio_extension(output_format: str) -> str:
    """Return the tutor audio extension used for the saved response file."""
    normalized_format = output_format.strip().lower() or "mp3"
    if normalized_format == "wav":
        return "wav"
    return "mp3"


def _log_elapsed(metric_name: str, started_at: float) -> None:
    """Log elapsed seconds for one voice-chat pipeline stage."""
    elapsed = time.perf_counter() - started_at
    logger.info("%s=%.2f", metric_name, elapsed)
