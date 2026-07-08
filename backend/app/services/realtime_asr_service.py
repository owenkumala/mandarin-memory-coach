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
from queue import Empty, Queue
from typing import Protocol

from app.core.config import Settings
from app.schemas import RealtimeVoiceEvent, RealtimeVoiceEventType
from app.services.qwen_client import QwenClient, _asr_api_key
from app.utils.audio import (
    build_audio_file_path,
    validate_audio_upload,
    write_audio_bytes,
)

logger = logging.getLogger(__name__)
DEFAULT_REALTIME_AUDIO_FILENAME = "realtime.webm"
DEFAULT_REALTIME_AUDIO_MIME_TYPE = "audio/webm"
REALTIME_ASR_MODE_BUFFERED = "buffered_fallback"
REALTIME_ASR_MODE_QWEN_STREAMING = "qwen_streaming_realtime"
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


class RealtimeAsrProvider(Protocol):
    """Small provider seam for mocked streaming ASR tests."""

    def start(self, callback: "_QwenStreamingAsrCallback") -> None:
        """Open the provider stream and register the callback."""

    def append_audio(self, audio_bytes: bytes) -> None:
        """Forward one audio chunk to the provider stream immediately."""

    def finish(self) -> None:
        """Finalize the provider stream."""


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
        return REALTIME_ASR_MODE_BUFFERED

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
        saved_audio_path = await self.save_audio()
        transcribe_started_at = time.perf_counter()
        logger.info("realtime.asr_transcribe_start")
        transcript = await self.qwen_client.transcribe_audio(saved_audio_path)
        logger.info(
            "realtime.asr_transcribe_seconds=%.2f",
            time.perf_counter() - transcribe_started_at,
        )
        return RealtimeAsrResult(transcript=transcript, audio_path=saved_audio_path)

    async def save_audio(self) -> str:
        """Persist buffered audio without transcribing it."""
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
        _validate_realtime_audio(
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
        return saved_audio_path


@dataclass
class QwenStreamingRealtimeAsrSession(RealtimeAsrSession):
    """Qwen3 realtime ASR session using the official DashScope omni SDK seam.

    The installed SDK exposes `OmniRealtimeConversation` plus
    `TranscriptionParams` for `qwen3-asr-flash-realtime`. It accepts base64 PCM
    audio through `input_audio_buffer.append`, so browser WebM/Opus chunks must
    stay on the buffered fallback until the frontend can provide PCM chunks.
    """

    qwen_client: QwenClient
    settings: Settings
    user_id: str
    audio_filename: str = "realtime.pcm"
    audio_mime_type: str = "audio/pcm"
    provider: RealtimeAsrProvider | None = None
    _callback: "_QwenStreamingAsrCallback | None" = None
    _fallback: BufferedRealtimeAsrSession = field(init=False)
    _streaming_failed: bool = False

    @property
    def mode(self) -> str:
        """Return the active ASR mode label."""
        if self._streaming_failed:
            return REALTIME_ASR_MODE_BUFFERED
        return REALTIME_ASR_MODE_QWEN_STREAMING

    def __post_init__(self) -> None:
        """Create the always-on local audio buffer used for safe fallback."""
        self._fallback = BufferedRealtimeAsrSession(
            qwen_client=self.qwen_client,
            settings=self.settings,
            user_id=self.user_id,
            audio_filename=self.audio_filename,
            audio_mime_type=self.audio_mime_type,
        )
        if self.provider is None:
            self.provider = QwenRealtimeAsrProvider(settings=self.settings)

    async def start(self) -> list[RealtimeVoiceEvent]:
        """Open the Qwen realtime ASR stream."""
        self._callback = _QwenStreamingAsrCallback()
        try:
            self.provider.start(self._callback)
        except Exception as exc:
            self._streaming_failed = True
            logger.warning("realtime.asr_streaming_start_failed reason=%s", exc)
            return [_streaming_asr_warning(str(exc))]
        logger.info(
            "realtime.asr_streaming_start model=%s sample_rate=%s format=%s",
            self.settings.REALTIME_ASR_MODEL,
            self.settings.REALTIME_ASR_SAMPLE_RATE,
            self.settings.REALTIME_ASR_AUDIO_FORMAT,
        )
        return []

    async def accept_audio_chunk(self, audio_bytes: bytes) -> list[RealtimeVoiceEvent]:
        """Forward one audio chunk immediately and emit provider partials."""
        events = await self._fallback.accept_audio_chunk(audio_bytes)
        if self._streaming_failed:
            return events
        try:
            self.provider.append_audio(audio_bytes)
        except Exception as exc:
            self._streaming_failed = True
            logger.warning("realtime.asr_streaming_append_failed reason=%s", exc)
            events.append(_streaming_asr_warning(str(exc)))
            return events
        return events + self._drain_provider_events()

    async def finish(self) -> RealtimeAsrResult:
        """Finalize Qwen streaming ASR or fall back to buffered ASR."""
        if self._streaming_failed:
            return await self._fallback.finish()
        try:
            self.provider.finish()
        except Exception as exc:
            self._streaming_failed = True
            logger.warning("realtime.asr_streaming_finish_failed reason=%s", exc)
            return await self._fallback.finish()

        self._drain_provider_events()
        transcript = self._callback.final_transcript if self._callback else ""
        if not transcript and self._callback:
            transcript = self._callback.latest_transcript
        if not transcript.strip():
            logger.warning("realtime.asr_streaming_empty_transcript_fallback")
            self._streaming_failed = True
            return await self._fallback.finish()
        audio_path = await self._fallback.save_audio()
        return RealtimeAsrResult(transcript=transcript.strip(), audio_path=audio_path)

    def _drain_provider_events(self) -> list[RealtimeVoiceEvent]:
        """Return currently available provider transcription events."""
        if self._callback is None:
            return []
        return self._callback.drain_events()


class QwenRealtimeAsrProvider:
    """Thin wrapper around DashScope's official Qwen omni realtime SDK."""

    def __init__(self, settings: Settings) -> None:
        """Store settings for lazy SDK construction."""
        self.settings = settings
        self._conversation = None

    def start(self, callback: "_QwenStreamingAsrCallback") -> None:
        """Open and configure the Qwen realtime ASR websocket."""
        from dashscope.audio.qwen_omni.omni_realtime import (  # noqa: PLC0415
            MultiModality,
            OmniRealtimeConversation,
            TranscriptionParams,
        )

        api_key, _key_source = _asr_api_key(self.settings)
        base_url = self.settings.REALTIME_ASR_BASE_URL.strip() or None
        self._conversation = OmniRealtimeConversation(
            model=self.settings.REALTIME_ASR_MODEL,
            callback=callback,
            url=base_url,
            api_key=api_key,
        )
        self._conversation.connect()
        self._conversation.update_session(
            output_modalities=[MultiModality.TEXT],
            enable_input_audio_transcription=True,
            enable_turn_detection=False,
            transcription_params=TranscriptionParams(
                language=self.settings.QWEN_ASR_LANGUAGE,
                sample_rate=self.settings.REALTIME_ASR_SAMPLE_RATE,
                input_audio_format=self.settings.REALTIME_ASR_AUDIO_FORMAT,
            ),
        )

    def append_audio(self, audio_bytes: bytes) -> None:
        """Forward one PCM audio chunk to the Qwen realtime stream."""
        if self._conversation is None:
            raise RuntimeError("Qwen realtime ASR provider has not started.")
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        self._conversation.append_audio(audio_b64)

    def finish(self) -> None:
        """Commit buffered provider audio and close the realtime session."""
        if self._conversation is None:
            raise RuntimeError("Qwen realtime ASR provider has not started.")
        self._conversation.commit()
        self._conversation.end_session(
            timeout=self.settings.REALTIME_ASR_SESSION_FINISH_TIMEOUT_SECONDS,
        )


def build_realtime_asr_session(
    qwen_client: QwenClient,
    settings: Settings,
    user_id: str,
    audio_filename: str | None = None,
    audio_mime_type: str | None = None,
) -> RealtimeAsrSession:
    """Return the best supported realtime ASR session for current settings.

    The default stays buffered. Qwen streaming mode is opt-in and only selected
    when the incoming audio metadata is compatible with the SDK's PCM stream.
    """
    mode = settings.REALTIME_ASR_MODE.strip().lower()
    if mode == REALTIME_ASR_MODE_QWEN_STREAMING:
        if _supports_qwen_streaming_audio(audio_filename, audio_mime_type):
            return QwenStreamingRealtimeAsrSession(
                qwen_client=qwen_client,
                settings=settings,
                user_id=user_id,
                audio_filename=_streaming_audio_filename(audio_filename),
                audio_mime_type="audio/pcm",
            )
        logger.warning(
            "realtime.asr_streaming_requires_pcm falling_back_to_buffered "
            "audio_filename=%s audio_mime_type=%s",
            audio_filename,
            audio_mime_type,
        )
    elif mode != REALTIME_ASR_MODE_BUFFERED:
        raise ValueError(
            "REALTIME_ASR_MODE must be buffered_fallback or qwen_streaming_realtime."
        )

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


class _QwenStreamingAsrCallback:
    """Collect Qwen realtime ASR callback events across SDK worker threads."""

    def __init__(self) -> None:
        """Create thread-safe event storage for provider callbacks."""
        self.events: Queue[RealtimeVoiceEvent] = Queue()
        self.latest_transcript = ""
        self.final_transcript = ""

    def on_open(self) -> None:
        """Provider stream opened."""

    def on_close(self, close_status_code=None, close_msg=None) -> None:
        """Provider stream closed."""

    def on_error(self, message) -> None:
        """Provider emitted an error callback."""
        self.events.put(_streaming_asr_warning(str(message)))

    def on_event(self, message) -> None:
        """Convert provider JSON messages into realtime ASR events."""
        provider_events = _provider_message_to_events(message)
        for event in provider_events:
            text = event.payload.get("text") or event.payload.get("transcript")
            if isinstance(text, str) and text.strip():
                self.latest_transcript = text.strip()
                if event.type == RealtimeVoiceEventType.ASR_FINAL:
                    self.final_transcript = text.strip()
            self.events.put(event)

    def drain_events(self) -> list[RealtimeVoiceEvent]:
        """Return all currently queued callback events."""
        drained = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except Empty:
                return drained


def _provider_message_to_events(message: object) -> list[RealtimeVoiceEvent]:
    """Convert Qwen realtime JSON callbacks into typed realtime ASR events."""
    if not isinstance(message, dict):
        return []
    event_type = message.get("type")
    if event_type == "error":
        return [_streaming_asr_warning(str(message.get("error") or message))]

    text = _extract_provider_transcript_text(message)
    if not text:
        return []
    is_final = _is_provider_final_transcript(message)
    return [
        RealtimeVoiceEvent(
            type=(
                RealtimeVoiceEventType.ASR_FINAL
                if is_final
                else RealtimeVoiceEventType.ASR_PARTIAL
            ),
            payload={
                "transcript" if is_final else "text": text,
                "provider_event_type": event_type,
            },
        )
    ]


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


def _supports_qwen_streaming_audio(
    audio_filename: str | None,
    audio_mime_type: str | None,
) -> bool:
    """Return whether client metadata is compatible with Qwen PCM streaming."""
    if isinstance(audio_mime_type, str) and audio_mime_type.strip().lower() in {
        "audio/pcm",
        "audio/l16",
        "application/octet-stream",
    }:
        return True
    if not isinstance(audio_filename, str):
        return False
    return Path(audio_filename.strip().replace("\\", "/")).suffix.lower() in {
        ".pcm",
        ".raw",
    }


def _validate_realtime_audio(
    original_filename: str,
    content: bytes,
    max_bytes: int,
) -> None:
    """Validate buffered realtime audio, including raw PCM streaming storage."""
    if Path(original_filename).suffix.lower() not in {".pcm", ".raw"}:
        validate_audio_upload(original_filename, content, max_bytes)
        return
    if not content:
        raise ValueError("Audio file is empty.")
    if len(content) > max_bytes:
        raise ValueError(f"Audio file is too large. Maximum size is {max_bytes} bytes.")


def _streaming_audio_filename(audio_filename: str | None) -> str:
    """Return a safe PCM filename for local streaming-session audio storage."""
    basename = _safe_audio_basename(audio_filename)
    if Path(basename).suffix.lower() not in {".pcm", ".raw"}:
        return "realtime.pcm"
    return basename


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


def _streaming_asr_warning(message: str) -> RealtimeVoiceEvent:
    """Return a warning event when streaming ASR falls back or reports trouble."""
    return RealtimeVoiceEvent(
        type=RealtimeVoiceEventType.ERROR,
        payload={
            "severity": "warning",
            "code": "streaming_asr_unavailable",
            "message": (
                "Streaming ASR was unavailable; using buffered ASR fallback."
            ),
            "details": message,
        },
    )


def _extract_provider_transcript_text(message: dict[str, object]) -> str:
    """Extract transcript text from common Qwen realtime event shapes."""
    for key in ("transcript", "text", "delta"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("transcription", "item", "response", "output"):
        value = message.get(key)
        text = _extract_text_recursive(value)
        if text:
            return text
    return ""


def _extract_text_recursive(value: object) -> str:
    """Find text-like values in nested provider payloads."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("transcript", "text", "delta"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        for nested in value.values():
            text = _extract_text_recursive(nested)
            if text:
                return text
    if isinstance(value, list):
        for nested in value:
            text = _extract_text_recursive(nested)
            if text:
                return text
    return ""


def _is_provider_final_transcript(message: dict[str, object]) -> bool:
    """Return whether a provider message represents a final transcript."""
    event_type = message.get("type")
    if isinstance(event_type, str):
        normalized = event_type.lower()
        if any(token in normalized for token in ("completed", "complete", "final")):
            return True
        if normalized.endswith(".done") and "transcription" in normalized:
            return True
    for key in ("is_final", "final", "sentence_end", "completed"):
        if message.get(key) is True:
            return True
    return False


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
