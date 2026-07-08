"""Realtime ASR session abstractions for progressive voice-chat sessions.

The default implementation buffers WebSocket audio chunks and then reuses the
stable Qwen ASR path. A provider-specific realtime ASR session can be added
behind the same interface when the Qwen realtime ASR contract is clear.
"""

import base64
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.schemas import RealtimeVoiceEvent, RealtimeVoiceEventType
from app.services.qwen_client import QwenClient
from app.utils.audio import (
    build_audio_file_path,
    validate_audio_upload,
    write_audio_bytes,
)

logger = logging.getLogger(__name__)
DEFAULT_REALTIME_AUDIO_FILENAME = "realtime.webm"
DEFAULT_REALTIME_AUDIO_MIME_TYPE = "audio/webm"
REALTIME_AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


@dataclass
class RealtimeAsrResult:
    """Final ASR result and persisted audio path for a realtime session."""

    transcript: str
    audio_path: str


class RealtimeAsrSession:
    """Common interface for realtime or buffered ASR implementations."""

    @property
    def mode(self) -> str:
        """Return a stable frontend/logging label for this ASR implementation."""
        raise NotImplementedError

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
    audio_filename: str = DEFAULT_REALTIME_AUDIO_FILENAME
    audio_mime_type: str = DEFAULT_REALTIME_AUDIO_MIME_TYPE
    chunks: list[bytes] = field(default_factory=list)
    bytes_received: int = 0

    @property
    def mode(self) -> str:
        """Return the stable ASR mode label for frontend/debug events."""
        return "buffered_fallback"

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
        logger.info(
            "realtime.asr_audio_filename=%s "
            "realtime.asr_audio_mime_type=%s "
            "realtime.asr_audio_extension=%s",
            self.audio_filename,
            self.audio_mime_type,
            Path(self.audio_filename).suffix.lower(),
        )
        validate_audio_upload(
            self.audio_filename,
            audio_content,
            self.settings.MAX_AUDIO_UPLOAD_BYTES,
        )
        audio_path = build_audio_file_path(
            self.settings.USER_AUDIO_DIR,
            self.user_id,
            self.audio_filename,
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


class QwenStreamingRealtimeAsrSession(RealtimeAsrSession):
    """Placeholder for a future official Qwen streaming ASR implementation.

    This class intentionally does not implement a private or guessed wire
    protocol. When Qwen/DashScope documents a supported realtime ASR contract
    for the target model, this session should open that provider stream in
    start(), forward each accept_audio_chunk() payload immediately, emit
    asr_partial/asr_final events as provider results arrive, and keep
    BufferedRealtimeAsrSession as the safe fallback.
    """

    @property
    def mode(self) -> str:
        """Return the planned provider-specific ASR mode label."""
        return "qwen_streaming_realtime"

    async def start(self) -> list[RealtimeVoiceEvent]:
        """Do not start an unsupported provider stream."""
        raise NotImplementedError("Qwen streaming realtime ASR is not implemented.")

    async def accept_audio_chunk(self, audio_bytes: bytes) -> list[RealtimeVoiceEvent]:
        """Do not forward audio to an unsupported provider stream."""
        raise NotImplementedError("Qwen streaming realtime ASR is not implemented.")

    async def finish(self) -> RealtimeAsrResult:
        """Do not finalize an unsupported provider stream."""
        raise NotImplementedError("Qwen streaming realtime ASR is not implemented.")


def build_realtime_asr_session(
    qwen_client: QwenClient,
    settings: Settings,
    user_id: str,
    audio_filename: str | None = None,
    audio_mime_type: str | None = None,
) -> RealtimeAsrSession:
    """Return the best supported realtime ASR session for current settings.

    TODO: choose QwenStreamingRealtimeAsrSession here only after the SDK or
    provider docs expose a real supported streaming ASR protocol for the target
    Qwen realtime model.
    """
    metadata = sanitize_realtime_audio_metadata(
        audio_filename=audio_filename,
        audio_mime_type=audio_mime_type,
    )
    return BufferedRealtimeAsrSession(
        qwen_client=qwen_client,
        settings=settings,
        user_id=user_id,
        audio_filename=metadata[0],
        audio_mime_type=metadata[1],
    )


def sanitize_realtime_audio_metadata(
    audio_filename: str | None,
    audio_mime_type: str | None,
) -> tuple[str, str]:
    """Return safe realtime audio filename and MIME metadata for buffered ASR."""
    safe_filename = _safe_audio_basename(audio_filename)
    extension = Path(safe_filename).suffix.lower()
    if extension not in REALTIME_AUDIO_MIME_TYPES:
        return DEFAULT_REALTIME_AUDIO_FILENAME, DEFAULT_REALTIME_AUDIO_MIME_TYPE
    safe_mime_type = _safe_audio_mime_type(audio_mime_type, extension)
    return safe_filename, safe_mime_type


def _safe_audio_basename(audio_filename: str | None) -> str:
    """Return a path-traversal-safe audio basename from client metadata."""
    if not isinstance(audio_filename, str) or not audio_filename.strip():
        return DEFAULT_REALTIME_AUDIO_FILENAME
    basename = Path(audio_filename.strip().replace("\\", "/")).name
    if basename in {"", ".", ".."}:
        return DEFAULT_REALTIME_AUDIO_FILENAME
    return basename


def _safe_audio_mime_type(audio_mime_type: str | None, extension: str) -> str:
    """Return recognized MIME metadata, defaulting by validated extension."""
    expected_mime_type = REALTIME_AUDIO_MIME_TYPES[extension]
    if not isinstance(audio_mime_type, str) or not audio_mime_type.strip():
        return expected_mime_type
    candidate = audio_mime_type.strip().lower()
    if candidate == expected_mime_type:
        return candidate
    return expected_mime_type


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
