"""Sentence-level TTS chunking for realtime tutor replies.

This module detects spoken sentence boundaries in streamed tutor text and
generates independent audio chunks so clients can play early sentences first.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.schemas import RealtimeVoiceEvent, RealtimeVoiceEventType
from app.services.qwen_client import QwenClient
from app.utils.audio import storage_url

logger = logging.getLogger(__name__)
SENTENCE_BOUNDARIES = set("。！？!?\n")
CLOSING_TRAILERS = set("”\"’」』）)")
CONTINUATION_AFTER_CLOSER = set("，,、；;：:")
QUOTE_PAIRS = {
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
    '"': '"',
}
DEFAULT_REALTIME_TTS_MAX_CONCURRENCY = 2


@dataclass
class SentenceTtsPipeline:
    """Accumulate text chunks and create background TTS tasks per sentence."""

    qwen_client: QwenClient
    settings: Settings
    user_id: str
    _buffer: str = ""
    _sequence: int = 0
    _tasks: list[asyncio.Task[RealtimeVoiceEvent | None]] = field(
        default_factory=list
    )
    _semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        """Create the per-session TTS concurrency guard."""
        self._semaphore = asyncio.Semaphore(DEFAULT_REALTIME_TTS_MAX_CONCURRENCY)

    def accept_text_chunk(self, text: str) -> list[RealtimeVoiceEvent]:
        """Add streamed tutor text and start TTS tasks for complete sentences."""
        self._buffer += text
        sentences, self._buffer = split_complete_sentences(self._buffer)
        events = []
        for sentence in sentences:
            self._sequence += 1
            events.append(
                RealtimeVoiceEvent(
                    type=RealtimeVoiceEventType.TUTOR_SENTENCE,
                    payload={"sequence": self._sequence, "text": sentence},
                )
            )
            self._tasks.append(
                asyncio.create_task(
                    self._generate_audio_event(
                        sentence=sentence,
                        sequence=self._sequence,
                    )
                )
            )
        return events

    def flush(self) -> list[RealtimeVoiceEvent]:
        """Finalize trailing text as one sentence and start its TTS task."""
        sentence = self._buffer.strip()
        self._buffer = ""
        if not _is_speakable_sentence(sentence):
            return []
        self._sequence += 1
        self._tasks.append(
            asyncio.create_task(
                self._generate_audio_event(sentence=sentence, sequence=self._sequence)
            )
        )
        return [
            RealtimeVoiceEvent(
                type=RealtimeVoiceEventType.TUTOR_SENTENCE,
                payload={"sequence": self._sequence, "text": sentence},
            )
        ]

    async def drain_ready(self) -> list[RealtimeVoiceEvent]:
        """Return completed TTS events without waiting for pending sentences."""
        ready_events = []
        pending_tasks = []
        for task in self._tasks:
            if task.done():
                event = await task
                if event is not None:
                    ready_events.append(event)
            else:
                pending_tasks.append(task)
        self._tasks = pending_tasks
        return ready_events

    def has_pending_tasks(self) -> bool:
        """Return whether any sentence TTS tasks are still running."""
        return bool(self._tasks)

    async def wait_for_next_event(self) -> list[RealtimeVoiceEvent]:
        """Wait for the next TTS task to finish and return completed events."""
        if not self._tasks:
            return []
        done_tasks, pending_tasks = await asyncio.wait(
            self._tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        self._tasks = list(pending_tasks)
        events = []
        for task in done_tasks:
            event = await task
            if event is not None:
                events.append(event)
        return sorted(events, key=_event_sequence)

    async def drain_all(self) -> list[RealtimeVoiceEvent]:
        """Wait for all pending TTS tasks and return their events by sequence."""
        events = []
        for task in self._tasks:
            event = await task
            if event is not None:
                events.append(event)
        self._tasks = []
        return sorted(events, key=_event_sequence)

    async def _generate_audio_event(
        self,
        sentence: str,
        sequence: int,
    ) -> RealtimeVoiceEvent | None:
        """Generate one sentence audio file and return the frontend event."""
        output_path = self._build_chunk_path(sequence)
        try:
            async with self._semaphore:
                synthesized_path = await self.qwen_client.synthesize_speech(
                    sentence,
                    str(output_path),
                )
        except ValueError as exc:
            logger.warning(
                "realtime.tts_sentence_failed sequence=%s sentence_length=%s "
                "reason=%s",
                sequence,
                len(sentence),
                _safe_tts_error(str(exc)),
            )
            return RealtimeVoiceEvent(
                type=RealtimeVoiceEventType.ERROR,
                payload={
                    "severity": "warning",
                    "code": "tts_sentence_failed",
                    "sequence": sequence,
                    "message": str(exc),
                },
            )
        if synthesized_path is None:
            return None
        return RealtimeVoiceEvent(
            type=RealtimeVoiceEventType.AUDIO_CHUNK_READY,
            payload={
                "sequence": sequence,
                "sentence": sentence,
                "audio_url": storage_url(synthesized_path, self.settings.STORAGE_DIR),
            },
        )

    def _build_chunk_path(self, sequence: int) -> Path:
        """Return a unique user-scoped TTS path for one sentence chunk."""
        safe_user_id = "".join(
            character
            for character in self.user_id
            if character.isalnum() or character in "-_"
        )
        safe_user_id = safe_user_id or "user"
        extension = (
            "wav" if self.settings.QWEN_TTS_OUTPUT_FORMAT.lower() == "wav" else "mp3"
        )
        return (
            Path(self.settings.TUTOR_AUDIO_DIR)
            / safe_user_id
            / f"chunk-{sequence}-{uuid4().hex}.{extension}"
        )


def split_complete_sentences(text: str) -> tuple[list[str], str]:
    """Split complete TTS-safe sentences without breaking Chinese quotes."""
    sentences = []
    start = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character not in SENTENCE_BOUNDARIES:
            index += 1
            continue

        boundary_end = _include_trailing_closers(text, index + 1)
        candidate = text[start:boundary_end].strip()
        if candidate and _has_unbalanced_quotes(candidate):
            if boundary_end == len(text):
                break
            index += 1
            continue
        if _continues_after_closing_quote(text, boundary_end):
            index = boundary_end + 1
            continue
        if _should_wait_for_more_text(candidate, boundary_end, len(text)):
            break
        if _is_speakable_sentence(candidate):
            sentences.append(candidate)
        start = boundary_end
        index = boundary_end
    return sentences, text[start:]


def _event_sequence(event: RealtimeVoiceEvent) -> int:
    """Return an event sequence number for deterministic audio ordering."""
    sequence = event.payload.get("sequence", 0)
    return sequence if isinstance(sequence, int) else 0


def _include_trailing_closers(text: str, boundary_end: int) -> int:
    """Include trailing closing quotes and brackets with a sentence."""
    while boundary_end < len(text) and text[boundary_end] in CLOSING_TRAILERS:
        boundary_end += 1
    return boundary_end


def _continues_after_closing_quote(text: str, boundary_end: int) -> bool:
    """Return whether a closed quote is followed by continuation punctuation."""
    if boundary_end <= 0 or boundary_end >= len(text):
        return False
    return (
        text[boundary_end - 1] in CLOSING_TRAILERS
        and text[boundary_end] in CONTINUATION_AFTER_CLOSER
    )


def _should_wait_for_more_text(
    candidate: str,
    boundary_end: int,
    text_length: int,
) -> bool:
    """Return whether a possible sentence needs more streamed text first."""
    if not candidate:
        return False
    if boundary_end == text_length and candidate[-1] in SENTENCE_BOUNDARIES:
        return True
    return False


def _has_unbalanced_quotes(text: str) -> bool:
    """Return whether Chinese/English quote characters are not balanced yet."""
    for opener, closer in QUOTE_PAIRS.items():
        if opener == closer:
            if text.count(opener) % 2:
                return True
            continue
        if text.count(opener) != text.count(closer):
            return True
    return False


def _is_speakable_sentence(text: str) -> bool:
    """Reject quote-only, punctuation-only, or emoji-only TTS chunks."""
    stripped = text.strip()
    if not stripped:
        return False
    return any(character.isalnum() for character in stripped)


def _safe_tts_error(message: str) -> str:
    """Return compact TTS error text without raw multiline provider detail."""
    compact = " ".join(message.split())
    if len(compact) > 160:
        return f"{compact[:157]}..."
    return compact
