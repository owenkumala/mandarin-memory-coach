"""Pydantic schemas and enums for all public API contracts."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MistakeType(str, Enum):
    """Allowed Mandarin mistake types produced by Qwen analysis."""

    PRONUNCIATION = "pronunciation"
    TONE = "tone"
    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    FLUENCY = "fluency"
    HESITATION = "hesitation"


class WeaknessCategory(str, Enum):
    """Allowed longitudinal weakness categories for learner memory."""

    TONE_ACCURACY = "tone_accuracy"
    ZH_CH_CONFUSION = "zh_ch_confusion"
    SENTENCE_LENGTH = "sentence_length"
    VOCABULARY_RECALL = "vocabulary_recall"
    GRAMMAR_STRUCTURE = "grammar_structure"
    HESITATION = "hesitation"


class WeaknessStatus(str, Enum):
    """Status labels derived from longitudinal weakness severity scores."""

    ACTIVE = "active"
    IMPROVING = "improving"
    RESOLVED = "resolved"


class RealtimeVoiceEventType(str, Enum):
    """WebSocket event types emitted by the realtime voice-chat pipeline."""

    SESSION_STARTED = "session_started"
    AUDIO_RECEIVED = "audio_received"
    ASR_PARTIAL = "asr_partial"
    ASR_FINAL = "asr_final"
    TUTOR_TOKEN = "tutor_token"
    TUTOR_SENTENCE = "tutor_sentence"
    AUDIO_CHUNK_READY = "audio_chunk_ready"
    FEEDBACK_READY = "feedback_ready"
    MEMORY_UPDATED = "memory_updated"
    ERROR = "error"
    DONE = "done"


class RealtimeVoiceEvent(BaseModel):
    """One frontend-consumable event emitted over realtime voice WebSockets."""

    type: RealtimeVoiceEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Health-check response for local and deployment verification."""

    status: str
    project_name: str
    use_fake_qwen: bool
    database_type: str


class MistakeAnalysis(BaseModel):
    """One structured mistake from the Qwen analysis step."""

    type: MistakeType
    weakness_category: WeaknessCategory
    target: str
    severity: int = Field(ge=1, le=5)
    feedback: str
    example_sentence: str
    recommended_drill: str


class AnalysisResponse(BaseModel):
    """Full structured Qwen analysis for a single learner turn."""

    mistakes: list[MistakeAnalysis]
    fluency_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    summary: str
    next_focus: str
    next_drill: str


class ActiveWeaknessResponse(BaseModel):
    """Learner weakness state returned in memory responses."""

    weakness_category: WeaknessCategory
    weakness_name: str
    severity_score: float
    times_failed: int
    status: WeaknessStatus
    recommended_drill: str
    last_seen: datetime


class SessionSummaryResponse(BaseModel):
    """Compact recent-session row for the memory dashboard."""

    id: int
    scenario: str
    transcript: str
    tutor_reply: str
    summary: str
    created_at: datetime


class LessonPlanResponse(BaseModel):
    """Recommended next lesson focus for a learner."""

    user_id: str
    focus_area: str
    recommended_drill: str
    next_scenario: str
    target_words: list[str]
    created_at: datetime | None = None


class MemoryResponse(BaseModel):
    """Working memory and recent raw-memory summary for one learner."""

    user_id: str
    learner_level: str
    native_language: str
    active_weaknesses: list[ActiveWeaknessResponse]
    recent_sessions: list[SessionSummaryResponse]
    latest_lesson_plan: LessonPlanResponse | None


class VoiceChatResponse(BaseModel):
    """Response returned after the full fake-Qwen voice-chat memory pipeline."""

    user_id: str
    scenario: str
    level: str
    transcript: str
    tutor_reply: str
    tutor_audio_url: str | None
    feedback: AnalysisResponse
    memory_before: MemoryResponse
    memory_after: MemoryResponse
    memory_updated: bool
