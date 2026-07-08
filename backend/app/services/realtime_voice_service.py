"""Realtime WebSocket orchestration for progressive voice-chat events.

The service coordinates buffered ASR, streaming tutor replies, sentence-level
TTS, and memory updates while preserving the stable REST voice-chat pipeline.
"""

import asyncio
import logging
import time
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
from app.services.qwen_client import QwenClient, build_fallback_analysis
from app.services.realtime_asr_service import (
    RealtimeAsrResult,
    RealtimeAsrSession,
    build_realtime_asr_session,
    decode_audio_chunk,
)
from app.services.realtime_fast_ack_service import (
    build_fast_ack_audio_event,
    cached_fast_ack_audio_event,
    fast_ack_sentence_event,
)
from app.services.sentence_tts_pipeline import SentenceTtsPipeline

logger = logging.getLogger(__name__)
DEFAULT_REALTIME_LEVEL = "HSK1 beginner"
ANALYSIS_FAILED_MESSAGE = "Structured feedback could not be generated for this turn."
RECOVERABLE_ANALYSIS_ERROR_MESSAGES = (
    "Qwen analysis response was not valid JSON.",
    "Qwen analysis response did not match the expected schema or enums.",
)


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
        audio_filename=_optional_string_field(message, "audio_filename"),
        audio_mime_type=_optional_string_field(message, "audio_mime_type"),
    )
    state = _RealtimeSessionState(
        session_id=session_id,
        user_id=user_id,
        scenario=scenario,
        level=level,
        asr_session=asr_session,
        memory_before=memory_before,
        started_at=time.perf_counter(),
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
    _log_elapsed("realtime.session_started", state.started_at)
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
        _log_audio_received(state, event)


async def _handle_end_audio(
    db: Session,
    qwen_client: QwenClient,
    session_state: "_RealtimeSessionState | None",
    websocket: WebSocket,
) -> None:
    """Finish ASR, then run streaming tutor, TTS, feedback, and memory work."""
    state = _require_session(session_state)
    _log_elapsed("realtime.end_audio_received_seconds", state.started_at)
    _log_elapsed("realtime.asr_finish_start_seconds", state.started_at)
    asr_result = await state.asr_session.finish()
    _log_elapsed("realtime.asr_finish_done_seconds", state.started_at)
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.ASR_FINAL,
            payload={"transcript": asr_result.transcript},
        ),
    )
    _log_elapsed("realtime.asr_final_seconds", state.started_at)
    fast_ack_task = await _start_fast_ack(
        websocket=websocket,
        qwen_client=qwen_client,
        state=state,
    )
    await _run_tutor_feedback_memory_pipeline(
        db=db,
        qwen_client=qwen_client,
        state=state,
        asr_result=asr_result,
        websocket=websocket,
        fast_ack_task=fast_ack_task,
    )


async def _run_tutor_feedback_memory_pipeline(
    db: Session,
    qwen_client: QwenClient,
    state: "_RealtimeSessionState",
    asr_result: RealtimeAsrResult,
    websocket: WebSocket,
    fast_ack_task: "asyncio.Task[RealtimeVoiceEvent | None] | None",
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
    analysis: AnalysisResponse | None = None
    feedback_sent = False
    memory_sent = False
    fast_ack_done = False

    async for token in qwen_client.stream_tutor_reply(
        transcript=asr_result.transcript,
        memory=state.memory_before,
        scenario=state.scenario,
        level=state.level,
    ):
        tutor_reply_parts.append(token)
        _log_once(state, "first_tutor_token_logged", "realtime.first_tutor_token_seconds")
        await _send_event(
            websocket,
            RealtimeVoiceEvent(
                type=RealtimeVoiceEventType.TUTOR_TOKEN,
                payload={"text": token},
            ),
        )
        await _send_events(websocket, state, tts_pipeline.accept_text_chunk(token))
        await _send_events(websocket, state, await tts_pipeline.drain_ready())
        fast_ack_done = await _emit_fast_ack_if_ready(
            websocket=websocket,
            state=state,
            fast_ack_task=fast_ack_task,
            already_done=fast_ack_done,
        )
        if analysis is None and analysis_task.done():
            analysis = await _resolve_analysis_task(
                websocket=websocket,
                state=state,
                asr_result=asr_result,
                analysis_task=analysis_task,
            )
            feedback_sent = await _emit_feedback_ready(
                websocket=websocket,
                state=state,
                analysis=analysis,
                already_sent=feedback_sent,
            )

    await _send_events(websocket, state, tts_pipeline.flush())

    tutor_reply = "".join(tutor_reply_parts).strip()
    if analysis is None and analysis_task.done():
        analysis = await _resolve_analysis_task(
            websocket=websocket,
            state=state,
            asr_result=asr_result,
            analysis_task=analysis_task,
        )
        feedback_sent = await _emit_feedback_ready(
            websocket=websocket,
            state=state,
            analysis=analysis,
            already_sent=feedback_sent,
        )
    if analysis is not None:
        memory_sent = await _persist_and_emit_memory(
            db=db,
            websocket=websocket,
            state=state,
            asr_result=asr_result,
            tutor_reply=tutor_reply,
            analysis=analysis,
            already_sent=memory_sent,
        )

    analysis, feedback_sent, memory_sent = await _finish_analysis_tts_and_memory(
        db=db,
        websocket=websocket,
        state=state,
        asr_result=asr_result,
        tutor_reply=tutor_reply,
        analysis_task=analysis_task,
        tts_pipeline=tts_pipeline,
        analysis=analysis,
        feedback_sent=feedback_sent,
        memory_sent=memory_sent,
        fast_ack_task=fast_ack_task,
        fast_ack_done=fast_ack_done,
    )
    if analysis is None or not memory_sent:
        raise ValueError("Realtime feedback and memory update did not complete.")
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.DONE,
            payload={"session_id": state.session_id},
        ),
    )
    _log_elapsed("realtime.done_seconds", state.started_at)


async def _finish_analysis_tts_and_memory(
    db: Session,
    websocket: WebSocket,
    state: "_RealtimeSessionState",
    asr_result: RealtimeAsrResult,
    tutor_reply: str,
    analysis_task: asyncio.Task[AnalysisResponse],
    tts_pipeline: SentenceTtsPipeline,
    analysis: AnalysisResponse | None,
    feedback_sent: bool,
    memory_sent: bool,
    fast_ack_task: "asyncio.Task[RealtimeVoiceEvent | None] | None",
    fast_ack_done: bool,
) -> tuple[AnalysisResponse | None, bool, bool]:
    """Drain pending TTS while emitting feedback as soon as analysis finishes."""
    while (
        tts_pipeline.has_pending_tasks()
        or analysis is None
        or (fast_ack_task is not None and not fast_ack_done)
    ):
        waiters: dict[asyncio.Task[object], str] = {}
        if tts_pipeline.has_pending_tasks():
            waiters[
                asyncio.create_task(tts_pipeline.wait_for_next_event())
            ] = "tts"
        if analysis is None:
            waiters[analysis_task] = "analysis"
        if fast_ack_task is not None and not fast_ack_done:
            waiters[fast_ack_task] = "fast_ack"

        done_tasks, pending_tasks = await asyncio.wait(
            waiters,
            return_when=asyncio.FIRST_COMPLETED,
        )
        await _cancel_tts_waiters(waiters, pending_tasks)

        for task in done_tasks:
            if waiters[task] == "tts":
                events = task.result()
                if isinstance(events, list):
                    await _send_events(websocket, state, events)
                continue
            if waiters[task] == "fast_ack":
                event = task.result()
                fast_ack_done = True
                if isinstance(event, RealtimeVoiceEvent):
                    await _send_events(websocket, state, [event])
                    _log_elapsed(
                        "realtime.fast_ack_audio_ready_seconds",
                        state.started_at,
                    )
                else:
                    _log_elapsed("realtime.fast_ack_skipped_seconds", state.started_at)
                continue

            analysis = await _resolve_analysis_task(
                websocket=websocket,
                state=state,
                asr_result=asr_result,
                analysis_task=analysis_task,
            )
            if isinstance(analysis, AnalysisResponse):
                feedback_sent = await _emit_feedback_ready(
                    websocket=websocket,
                    state=state,
                    analysis=analysis,
                    already_sent=feedback_sent,
                )
                memory_sent = await _persist_and_emit_memory(
                    db=db,
                    websocket=websocket,
                    state=state,
                    asr_result=asr_result,
                    tutor_reply=tutor_reply,
                    analysis=analysis,
                    already_sent=memory_sent,
                )
    return analysis, feedback_sent, memory_sent


async def _resolve_analysis_task(
    websocket: WebSocket,
    state: "_RealtimeSessionState",
    asr_result: RealtimeAsrResult,
    analysis_task: asyncio.Task[AnalysisResponse],
) -> AnalysisResponse:
    """Return analysis or a safe fallback for recoverable model JSON failures."""
    try:
        return await analysis_task
    except Exception as exc:
        if not _is_recoverable_analysis_error(exc):
            raise
        logger.warning(
            "realtime.analysis_failed code=analysis_failed reason=%s",
            str(exc),
        )
        await _send_warning(websocket, "analysis_failed", ANALYSIS_FAILED_MESSAGE)
        return build_fallback_analysis(
            transcript=asr_result.transcript,
            scenario=state.scenario,
            level=state.level,
            reason=str(exc),
        )


def _is_recoverable_analysis_error(exc: Exception) -> bool:
    """Return true only for malformed model analysis output failures."""
    if not isinstance(exc, ValueError):
        return False
    message = str(exc)
    return any(
        recoverable_message in message
        for recoverable_message in RECOVERABLE_ANALYSIS_ERROR_MESSAGES
    )


async def _start_fast_ack(
    websocket: WebSocket,
    qwen_client: QwenClient,
    state: "_RealtimeSessionState",
) -> asyncio.Task[RealtimeVoiceEvent | None] | None:
    """Start sequence-0 fast acknowledgement audio generation when possible."""
    settings = get_settings()
    if settings.USE_FAKE_TTS:
        _log_elapsed("realtime.fast_ack_skipped_seconds", state.started_at)
        return None
    await _send_events(websocket, state, [fast_ack_sentence_event()])
    _log_elapsed("realtime.fast_ack_start_seconds", state.started_at)
    cached_event = cached_fast_ack_audio_event(settings)
    if cached_event is not None:
        await _send_events(websocket, state, [cached_event])
        _log_elapsed("realtime.fast_ack_audio_ready_seconds", state.started_at)
        return None
    return asyncio.create_task(
        build_fast_ack_audio_event(qwen_client=qwen_client, settings=settings)
    )


async def _emit_fast_ack_if_ready(
    websocket: WebSocket,
    state: "_RealtimeSessionState",
    fast_ack_task: "asyncio.Task[RealtimeVoiceEvent | None] | None",
    already_done: bool,
) -> bool:
    """Emit completed sequence-0 fast ack audio without blocking streaming."""
    if already_done or fast_ack_task is None or not fast_ack_task.done():
        return already_done
    event = await fast_ack_task
    if event is None:
        _log_elapsed("realtime.fast_ack_skipped_seconds", state.started_at)
        return True
    await _send_events(websocket, state, [event])
    _log_elapsed("realtime.fast_ack_audio_ready_seconds", state.started_at)
    return True


async def _cancel_tts_waiters(
    waiters: dict[asyncio.Task[object], str],
    pending_tasks: set[asyncio.Task[object]],
) -> None:
    """Cancel pending wait helper tasks without cancelling underlying TTS jobs."""
    for task in pending_tasks:
        if waiters[task] == "tts":
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _emit_feedback_ready(
    websocket: WebSocket,
    state: "_RealtimeSessionState",
    analysis: AnalysisResponse,
    already_sent: bool,
) -> bool:
    """Emit structured feedback once and log when it became available."""
    if already_sent:
        return True
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.FEEDBACK_READY,
            payload={"feedback": analysis.model_dump(mode="json")},
        ),
    )
    _log_elapsed("realtime.feedback_ready_seconds", state.started_at)
    return True


async def _persist_and_emit_memory(
    db: Session,
    websocket: WebSocket,
    state: "_RealtimeSessionState",
    asr_result: RealtimeAsrResult,
    tutor_reply: str,
    analysis: AnalysisResponse,
    already_sent: bool,
) -> bool:
    """Persist memory once and emit the resulting memory snapshot."""
    if already_sent:
        return True
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
    _log_elapsed("realtime.memory_updated_seconds", state.started_at)
    return True


async def _send_events(
    websocket: WebSocket,
    state: "_RealtimeSessionState",
    events: list[RealtimeVoiceEvent],
) -> None:
    """Send a batch of events and log first sentence/audio milestones."""
    for event in events:
        await _send_event(websocket, event)
        if event.type == RealtimeVoiceEventType.TUTOR_SENTENCE:
            _log_once(
                state,
                "first_tutor_sentence_logged",
                "realtime.first_tutor_sentence_seconds",
            )
        if event.type == RealtimeVoiceEventType.AUDIO_CHUNK_READY:
            _log_once(
                state,
                "first_audio_chunk_logged",
                "realtime.first_audio_chunk_ready_seconds",
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


async def _send_warning(websocket: WebSocket, code: str, message: str) -> None:
    """Send a recoverable warning event to the frontend."""
    await _send_event(
        websocket,
        RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.ERROR,
            payload={"severity": "warning", "code": code, "message": message},
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


def _optional_string_field(message: dict[str, object], field_name: str) -> str | None:
    """Return a trimmed optional string field from a message."""
    value = message.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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
        started_at: float,
    ) -> None:
        """Store session fields that need to survive multiple messages."""
        self.session_id = session_id
        self.user_id = user_id
        self.scenario = scenario
        self.level = level
        self.asr_session = asr_session
        self.memory_before = memory_before
        self.started_at = started_at
        self.first_tutor_token_logged = False
        self.first_tutor_sentence_logged = False
        self.first_audio_chunk_logged = False


def _log_audio_received(
    state: "_RealtimeSessionState",
    event: RealtimeVoiceEvent,
) -> None:
    """Log realtime audio byte progress without logging audio content."""
    bytes_received = event.payload.get("bytes_received")
    total_bytes_received = event.payload.get("total_bytes_received")
    logger.info(
        "realtime.audio_received elapsed_seconds=%.2f bytes=%s total_bytes=%s",
        time.perf_counter() - state.started_at,
        bytes_received,
        total_bytes_received,
    )


def _log_once(
    state: "_RealtimeSessionState",
    flag_name: str,
    metric_name: str,
) -> None:
    """Log a first-occurrence realtime milestone exactly once."""
    if getattr(state, flag_name):
        return
    setattr(state, flag_name, True)
    _log_elapsed(metric_name, state.started_at)


def _log_elapsed(metric_name: str, started_at: float) -> None:
    """Log elapsed seconds for one realtime pipeline stage."""
    logger.info("%s=%.2f", metric_name, time.perf_counter() - started_at)
