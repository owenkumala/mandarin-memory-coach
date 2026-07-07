"""Fast acknowledgement audio helper for realtime voice sessions.

The acknowledgement is generic, cached under shared tutor audio storage, and
lets the frontend play a very short response before model-generated TTS is done.
"""

import logging
from pathlib import Path

from app.core.config import Settings
from app.schemas import RealtimeVoiceEvent, RealtimeVoiceEventType
from app.services.qwen_client import QwenClient
from app.utils.audio import storage_url

logger = logging.getLogger(__name__)
FAST_ACK_TEXT = "我来帮你改一句。"
FAST_ACK_SEQUENCE = 0
FAST_ACK_SOURCE = "fast_ack"


async def build_fast_ack_audio_event(
    qwen_client: QwenClient,
    settings: Settings,
) -> RealtimeVoiceEvent | None:
    """Return cached/generated fast-ack audio event or skip safely."""
    cached_event = cached_fast_ack_audio_event(settings)
    if cached_event is not None:
        return cached_event
    try:
        output_path = _fast_ack_path(settings)
        synthesized_path = await qwen_client.synthesize_speech(
            FAST_ACK_TEXT,
            str(output_path),
        )
    except ValueError as exc:
        logger.warning(
            "realtime.fast_ack_failed sentence_length=%s reason=%s",
            len(FAST_ACK_TEXT),
            _safe_error(str(exc)),
        )
        return None
    if synthesized_path is None:
        return None
    return _audio_event(synthesized_path, settings)


def cached_fast_ack_audio_event(settings: Settings) -> RealtimeVoiceEvent | None:
    """Return the cached fast-ack audio event if the shared file already exists."""
    output_path = _fast_ack_path(settings)
    if not output_path.exists():
        return None
    return _audio_event(str(output_path), settings)


def fast_ack_sentence_event() -> RealtimeVoiceEvent:
    """Return the sequence-0 tutor sentence event for the fast acknowledgement."""
    return RealtimeVoiceEvent(
        type=RealtimeVoiceEventType.TUTOR_SENTENCE,
        payload={
            "sequence": FAST_ACK_SEQUENCE,
            "text": FAST_ACK_TEXT,
            "source": FAST_ACK_SOURCE,
        },
    )


def _audio_event(path: str, settings: Settings) -> RealtimeVoiceEvent:
    """Return the sequence-0 audio event for cached or generated ack audio."""
    return RealtimeVoiceEvent(
        type=RealtimeVoiceEventType.AUDIO_CHUNK_READY,
        payload={
            "sequence": FAST_ACK_SEQUENCE,
            "sentence": FAST_ACK_TEXT,
            "audio_url": storage_url(path, settings.STORAGE_DIR),
            "source": FAST_ACK_SOURCE,
        },
    )


def _fast_ack_path(settings: Settings) -> Path:
    """Return the shared cached fast-ack audio file path."""
    extension = "wav" if settings.QWEN_TTS_OUTPUT_FORMAT.lower() == "wav" else "mp3"
    return (
        Path(settings.TUTOR_AUDIO_DIR)
        / "_shared"
        / f"realtime-fast-ack.{extension}"
    )


def _safe_error(message: str) -> str:
    """Return compact single-line provider error detail for server logs."""
    compact = " ".join(message.split())
    if len(compact) > 160:
        return f"{compact[:157]}..."
    return compact
