"""Sentence-level TTS chunking for realtime tutor replies.

This module detects spoken sentence boundaries in streamed tutor text and
generates independent audio chunks so clients can play early sentences first.
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.schemas import RealtimeVoiceEvent, RealtimeVoiceEventType
from app.services.qwen_client import QwenClient
from app.utils.audio import storage_url

SENTENCE_BOUNDARIES = set("。！？!?\n")


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
        if not sentence:
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
            synthesized_path = await self.qwen_client.synthesize_speech(
                sentence,
                str(output_path),
            )
        except ValueError as exc:
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
    """Split complete Chinese/English sentence endings from trailing text."""
    sentences = []
    start = 0
    for index, character in enumerate(text):
        if character in SENTENCE_BOUNDARIES:
            sentence = text[start : index + 1].strip()
            if sentence:
                sentences.append(sentence)
            start = index + 1
    return sentences, text[start:]


def _event_sequence(event: RealtimeVoiceEvent) -> int:
    """Return an event sequence number for deterministic audio ordering."""
    sequence = event.payload.get("sequence", 0)
    return sequence if isinstance(sequence, int) else 0
