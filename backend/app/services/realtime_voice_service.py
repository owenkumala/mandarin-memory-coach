"""Realtime WebSocket orchestration for progressive voice-chat events.

The service coordinates buffered ASR, streaming tutor replies, sentence-level
TTS, and memory updates while preserving the stable REST voice-chat pipeline.
"""

import asyncio
import logging
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas import (
    AnalysisResponse,
    MemoryResponse,
    RealtimeVoiceEvent,
    RealtimeVoiceEventType,
)
from app.services.lesson_service import create_lesson_plan
from app.services.memory_service import (
    get_memory,
    get_or_create_user,
    save_mistakes,
    save_session,
    update_active_weaknesses,
)
from app.services.qwen_client import QwenClient
from app.services.realtime_asr_service import (
    RealtimeAsrResult,
    RealtimeAsrSession,
    build_realtime_asr_session,
    decode_audio_chunk,
)
from app.services.sentence_tts_pipeline import SentenceTtsPipeline

logger = logging.getLogger(__name__)
DEFAULT_REALTIME_LEVEL = "HSK1 beginner"


async def run_realtime_voice_websocket(websocket: WebSocket, db: Session) -> None:
    """Accept and run one realtime voice-chat WebSocket session."""
    await websocket.accept()
    settings = get_settings()
    qwen_client = QwenClient(settings=settings)
    session_state: _RealtimeSessionState | None = None

    try:
        while True:
            message = await websocket.receive_json()
            message_type = _message_type(message)
            if message_type == "start":
                session_state = await _handle_start(
                    message=message,
                    db=db,
                    qwen_client=qwen_client,
                    websocket=websocket,
                )
            elif message_type == "audio_chunk":
                await _handle_audio_chunk(
                    message=message,
                    session_state=session_state,
                    websocket=websocket,
                )
            elif message_type == "end_audio":
                await _handle_end_audio(
                    db=db,
                    qwen_client=qwen_client,
                    session_state=session_state,
                    websocket=websocket,
                )
                await websocket.close()
                return
            elif message_type == "cancel":
                await _send_event(
                    websocket,
                    RealtimeVoiceEvent(
                        type=RealtimeVoiceEventType.DONE,
                        payload={"cancelled": True},
                    ),
                )
                await websocket.close()
                return
            else:
                await _send_error(
                    websocket,
                    "unknown_message_type",
                    "Unknown message type.",
                )
    except WebSocketDisconnect:
        logger.info("voice_chat.realtime_disconnected")
    except (ValueError, OSError, NotImplementedError) as exc:
        logger.exception("Realtime voice-chat pipeline failed")
        await _send_error(websocket, "realtime_pipeline_failed", str(exc))
        await _send_event(
            websocket,
            RealtimeVoiceEvent(type=RealtimeVoiceEventType.DONE),
        )


async def _handle_start(
    message: dict[str, object],
    db: Session,
    qwen_client: QwenClient,
    websocket: WebSocket,
) -> "_RealtimeSessionState":
    """Initialize learner context and emit session_started immediately."""
    user_id = _string_field(message, "user_id", "demo-user")
    scenario = _string_field(message, "scenario", "restaurant ordering")
    level = _string_field(message, "level", DEFAULT_REALTIME_LEVEL)
    session_id = uuid4().hex

    get_or_create_user(db, user_id=user_id, mandarin_level=level)
    memory_before = get_memory(db, user_id=user_id)
    settings = get_settings()
    asr_session = build_realtime_asr_session(
        qwen_client=qwen_client,
        settings=settings,
        user_id=user_id,
    )
    state = _RealtimeSessionState(
        session_id=session_id,
        user_id=user_id,
        scenario=scenario,
        level=level,
        asr_session=asr_session,
        memory_before=memory_before,
    )
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.SESSION_STARTED,
            payload={
                "session_id": session_id,
                "user_id": user_id,
                "scenario": scenario,
                "level": level,
                "asr_mode": "buffered_fallback",
            },
        ),
    )
    for event in await asr_session.start():
        await _send_event(websocket, event)
    return state


async def _handle_audio_chunk(
    message: dict[str, object],
    session_state: "_RealtimeSessionState | None",
    websocket: WebSocket,
) -> None:
    """Decode and pass one audio chunk to the active ASR session."""
    state = _require_session(session_state)
    audio_bytes = decode_audio_chunk(message)
    for event in await state.asr_session.accept_audio_chunk(audio_bytes):
        await _send_event(websocket, event)


async def _handle_end_audio(
    db: Session,
    qwen_client: QwenClient,
    session_state: "_RealtimeSessionState | None",
    websocket: WebSocket,
) -> None:
    """Finish ASR, then run streaming tutor, TTS, feedback, and memory work."""
    state = _require_session(session_state)
    asr_result = await state.asr_session.finish()
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.ASR_FINAL,
            payload={"transcript": asr_result.transcript},
        ),
    )
    await _run_tutor_feedback_memory_pipeline(
        db=db,
        qwen_client=qwen_client,
        state=state,
        asr_result=asr_result,
        websocket=websocket,
    )


async def _run_tutor_feedback_memory_pipeline(
    db: Session,
    qwen_client: QwenClient,
    state: "_RealtimeSessionState",
    asr_result: RealtimeAsrResult,
    websocket: WebSocket,
) -> None:
    """Stream tutor response first, then persist feedback and memory updates."""
    settings = get_settings()
    tts_pipeline = SentenceTtsPipeline(
        qwen_client=qwen_client,
        settings=settings,
        user_id=state.user_id,
    )
    analysis_task = asyncio.create_task(
        qwen_client.analyze_mistakes(
            transcript=asr_result.transcript,
            scenario=state.scenario,
            level=state.level,
        )
    )
    tutor_reply_parts = []

    async for token in qwen_client.stream_tutor_reply(
        transcript=asr_result.transcript,
        memory=state.memory_before,
        scenario=state.scenario,
        level=state.level,
    ):
        tutor_reply_parts.append(token)
        await _send_event(
            websocket,
            RealtimeVoiceEvent(
                type=RealtimeVoiceEventType.TUTOR_TOKEN,
                payload={"text": token},
            ),
        )
        for event in tts_pipeline.accept_text_chunk(token):
            await _send_event(websocket, event)
        for event in await tts_pipeline.drain_ready():
            await _send_event(websocket, event)

    for event in tts_pipeline.flush():
        await _send_event(websocket, event)
    for event in await tts_pipeline.drain_all():
        await _send_event(websocket, event)

    tutor_reply = "".join(tutor_reply_parts).strip()
    analysis = await analysis_task
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.FEEDBACK_READY,
            payload={"feedback": analysis.model_dump(mode="json")},
        ),
    )
    memory_after = _persist_realtime_memory(
        db=db,
        state=state,
        asr_result=asr_result,
        tutor_reply=tutor_reply,
        analysis=analysis,
    )
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.MEMORY_UPDATED,
            payload={"memory_after": memory_after.model_dump(mode="json")},
        ),
    )
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.DONE,
            payload={"session_id": state.session_id},
        ),
    )


def _persist_realtime_memory(
    db: Session,
    state: "_RealtimeSessionState",
    asr_result: RealtimeAsrResult,
    tutor_reply: str,
    analysis: AnalysisResponse,
) -> MemoryResponse:
    """Persist session, mistakes, active weaknesses, and the next lesson plan."""
    session = save_session(
        db,
        user_id=state.user_id,
        scenario=state.scenario,
        transcript=asr_result.transcript,
        tutor_reply=tutor_reply,
        summary=analysis.summary,
        audio_path=asr_result.audio_path,
    )
    save_mistakes(
        db,
        user_id=state.user_id,
        session_id=session.id,
        mistakes=analysis.mistakes,
    )
    update_active_weaknesses(db, user_id=state.user_id, mistakes=analysis.mistakes)
    memory_after_weakness_update = get_memory(db, user_id=state.user_id)
    create_lesson_plan(
        db,
        user_id=state.user_id,
        analysis=analysis,
        memory=memory_after_weakness_update,
        scenario=state.scenario,
    )
    return get_memory(db, user_id=state.user_id)


async def _send_event(websocket: WebSocket, event: RealtimeVoiceEvent) -> None:
    """Serialize one typed event to the WebSocket."""
    await websocket.send_json(event.model_dump(mode="json"))


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    """Send a recoverable or terminal error event to the frontend."""
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.ERROR,
            payload={"severity": "error", "code": code, "message": message},
        ),
    )


def _message_type(message: object) -> str:
    """Return the normalized incoming control message type."""
    if not isinstance(message, dict):
        raise ValueError("Realtime WebSocket messages must be JSON objects.")
    message_type = message.get("type")
    if not isinstance(message_type, str):
        raise ValueError("Realtime WebSocket message type is required.")
    return message_type


def _string_field(message: dict[str, object], field_name: str, default: str) -> str:
    """Return a trimmed string field from a message or a safe default."""
    value = message.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _require_session(
    session_state: "_RealtimeSessionState | None",
) -> "_RealtimeSessionState":
    """Return the active session state or fail before audio processing starts."""
    if session_state is None:
        raise ValueError("Send a start message before audio_chunk or end_audio.")
    return session_state


class _RealtimeSessionState:
    """Internal state shared across one realtime WebSocket session."""

    def __init__(
        self,
        session_id: str,
        user_id: str,
        scenario: str,
        level: str,
        asr_session: RealtimeAsrSession,
        memory_before: MemoryResponse,
    ) -> None:
        """Store session fields that need to survive multiple messages."""
        self.session_id = session_id
        self.user_id = user_id
        self.scenario = scenario
        self.level = level
        self.asr_session = asr_session
        self.memory_before = memory_before
