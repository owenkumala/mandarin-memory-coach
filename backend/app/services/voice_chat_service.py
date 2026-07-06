"""Voice-chat orchestration service for the fake-Qwen memory pipeline.

This module keeps the endpoint thin while coordinating audio persistence,
Qwen calls, session storage, weakness updates, lesson-plan creation, and the
final response assembly.
"""

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


async def run_voice_chat_pipeline(
    db: Session,
    audio: UploadFile,
    user_id: str,
    scenario: str,
    level: str,
) -> VoiceChatResponse:
    """Run the complete voice-chat pipeline and return the API response."""
    settings = get_settings()
    qwen_client = QwenClient(settings=settings)

    # Persist learner audio first so raw session memory exists even in fake mode.
    audio_path = build_audio_file_path(
        settings.USER_AUDIO_DIR,
        user_id,
        audio.filename or "audio.webm",
    )
    audio_content = await audio.read()
    validate_audio_upload(audio.filename or "", audio_content)
    saved_audio_path = await write_audio_bytes(audio_path, audio_content)

    # Load memory before generating the reply so Qwen can adapt to past mistakes.
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

    # Store raw and structured memory before computing the updated working state.
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

    tutor_audio_url = await _generate_tutor_audio_url(
        qwen_client=qwen_client,
        tutor_reply=tutor_reply,
        user_id=user_id,
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


async def _generate_tutor_audio_url(
    qwen_client: QwenClient,
    tutor_reply: str,
    user_id: str,
) -> str | None:
    """Run fake/future TTS and convert a generated file path to a storage URL."""
    settings = get_settings()
    tutor_audio_path = build_audio_file_path(settings.TUTOR_AUDIO_DIR, user_id, "reply.mp3")
    synthesized_path = await qwen_client.synthesize_speech(
        tutor_reply,
        str(tutor_audio_path),
    )
    if synthesized_path is None:
        return None
    return storage_url(synthesized_path, settings.STORAGE_DIR)
