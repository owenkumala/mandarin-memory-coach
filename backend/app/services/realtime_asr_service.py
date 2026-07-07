"""Realtime ASR session abstractions for progressive voice-chat sessions.

The default implementation buffers WebSocket audio chunks and then reuses the
stable Qwen ASR path. A provider-specific realtime ASR session can be added
behind the same interface when the Qwen realtime ASR contract is clear.
"""

import base64
import logging
import time
from dataclasses import dataclass, field

from app.core.config import Settings
from app.schemas import RealtimeVoiceEvent, RealtimeVoiceEventType
from app.services.qwen_client import QwenClient
from app.utils.audio import (
    build_audio_file_path,
    validate_audio_upload,
    write_audio_bytes,
)

logger = logging.getLogger(__name__)


@dataclass
class RealtimeAsrResult:
    """Final ASR result and persisted audio path for a realtime session."""

    transcript: str
    audio_path: str


class RealtimeAsrSession:
    """Common interface for realtime or buffered ASR implementations."""

    async def start(self) -> list[RealtimeVoiceEvent]:
        """Start the ASR session and return any initial events."""
        raise NotImplementedError

    async def accept_audio_chunk(self, audio_bytes: bytes) -> list[RealtimeVoiceEvent]:
        """Accept one raw audio chunk and return any progressive ASR events."""
        raise NotImplementedError

    async def finish(self) -> RealtimeAsrResult:
        """Finalize ASR and return the transcript."""
        raise NotImplementedError


@dataclass
class BufferedRealtimeAsrSession(RealtimeAsrSession):
    """Buffered fallback that transcribes the full uploaded audio on end_audio."""

    qwen_client: QwenClient
    settings: Settings
    user_id: str
    chunks: list[bytes] = field(default_factory=list)
    bytes_received: int = 0

    async def start(self) -> list[RealtimeVoiceEvent]:
        """Start buffered ASR without opening any provider network stream."""
        return []

    async def accept_audio_chunk(self, audio_bytes: bytes) -> list[RealtimeVoiceEvent]:
        """Buffer one audio chunk and emit an audio_received progress event."""
        self.chunks.append(audio_bytes)
        self.bytes_received += len(audio_bytes)
        return [
            RealtimeVoiceEvent(
                type=RealtimeVoiceEventType.AUDIO_RECEIVED,
                payload={
                    "bytes_received": len(audio_bytes),
                    "total_bytes_received": self.bytes_received,
                },
            )
        ]

    async def finish(self) -> RealtimeAsrResult:
        """Persist buffered audio and transcribe it through the existing ASR path."""
        audio_content = b"".join(self.chunks)
        logger.info(
            "realtime.asr_buffer_bytes=%s chunks=%s",
            len(audio_content),
            len(self.chunks),
        )
        validate_audio_upload(
            "realtime.webm",
            audio_content,
            self.settings.MAX_AUDIO_UPLOAD_BYTES,
        )
        audio_path = build_audio_file_path(
            self.settings.USER_AUDIO_DIR,
            self.user_id,
            "realtime.webm",
        )
        save_started_at = time.perf_counter()
        logger.info("realtime.asr_save_audio_start")
        saved_audio_path = await write_audio_bytes(audio_path, audio_content)
        logger.info(
            "realtime.asr_save_audio_seconds=%.2f bytes=%s",
            time.perf_counter() - save_started_at,
            len(audio_content),
        )
        transcribe_started_at = time.perf_counter()
        logger.info("realtime.asr_transcribe_start")
        transcript = await self.qwen_client.transcribe_audio(saved_audio_path)
        logger.info(
            "realtime.asr_transcribe_seconds=%.2f",
            time.perf_counter() - transcribe_started_at,
        )
        return RealtimeAsrResult(transcript=transcript, audio_path=saved_audio_path)


def build_realtime_asr_session(
    qwen_client: QwenClient,
    settings: Settings,
    user_id: str,
) -> RealtimeAsrSession:
    """Return the best supported realtime ASR session for current settings."""
    return BufferedRealtimeAsrSession(
        qwen_client=qwen_client,
        settings=settings,
        user_id=user_id,
    )


def decode_audio_chunk(message: dict[str, object]) -> bytes:
    """Decode a base64 audio chunk from a frontend WebSocket message."""
    candidate = message.get("audio_base64") or message.get("audio")
    if not isinstance(candidate, str) or not candidate.strip():
        payload = message.get("payload")
        if isinstance(payload, dict):
            nested_candidate = payload.get("audio_base64") or payload.get("audio")
            if isinstance(nested_candidate, str):
                candidate = nested_candidate

    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("audio_chunk requires base64 audio in audio_base64.")
    try:
        return base64.b64decode(candidate, validate=True)
    except ValueError as exc:
        raise ValueError("audio_chunk contained invalid base64 audio.") from exc
