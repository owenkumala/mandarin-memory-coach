"""Database-backed learner memory service for sessions and weaknesses."""

from datetime import UTC, datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import models
from app.schemas import (
    ActiveWeaknessResponse,
    AnalysisResponse,
    LessonPlanResponse,
    MemoryResponse,
    MistakeAnalysis,
    SessionSummaryResponse,
    WeaknessCategory,
    WeaknessStatus,
)

DEFAULT_NATIVE_LANGUAGE = "Indonesian"
DEFAULT_LEARNING_GOAL = "Improve Mandarin speaking confidence"
DEFAULT_EXPLANATION_LANGUAGE = "English"
DEFAULT_LEARNER_NAME = "Demo Learner"

WEAKNESS_NAMES: dict[WeaknessCategory, str] = {
    WeaknessCategory.TONE_ACCURACY: "tone accuracy",
    WeaknessCategory.ZH_CH_CONFUSION: "zh/ch pronunciation confusion",
    WeaknessCategory.SENTENCE_LENGTH: "complete sentence answers",
    WeaknessCategory.VOCABULARY_RECALL: "vocabulary recall",
    WeaknessCategory.GRAMMAR_STRUCTURE: "grammar structure",
    WeaknessCategory.HESITATION: "hesitation and pauses",
}


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for memory updates."""
    return datetime.now(UTC)


def get_or_create_user(db: Session, user_id: str, mandarin_level: str) -> models.User:
    """Load a learner or create the MVP demo learner profile."""
    user = db.get(models.User, user_id)
    if user is not None:
        if user.mandarin_level != mandarin_level:
            user.mandarin_level = mandarin_level
            db.commit()
            db.refresh(user)
        return user

    user = models.User(
        id=user_id,
        name=DEFAULT_LEARNER_NAME,
        native_language=DEFAULT_NATIVE_LANGUAGE,
        mandarin_level=mandarin_level,
        learning_goal=DEFAULT_LEARNING_GOAL,
        preferred_explanation_language=DEFAULT_EXPLANATION_LANGUAGE,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_memory(db: Session, user_id: str) -> MemoryResponse:
    """Return active weaknesses, recent sessions, and latest lesson plan."""
    user = db.get(models.User, user_id)
    if user is None:
        return MemoryResponse(
            user_id=user_id,
            learner_level="HSK1 beginner",
            native_language=DEFAULT_NATIVE_LANGUAGE,
            active_weaknesses=[],
            recent_sessions=[],
            latest_lesson_plan=None,
        )

    weaknesses = (
        db.query(models.ActiveWeakness)
        .filter(models.ActiveWeakness.user_id == user_id)
        .order_by(desc(models.ActiveWeakness.severity_score), desc(models.ActiveWeakness.last_seen))
        .all()
    )
    sessions = (
        db.query(models.SessionRecord)
        .filter(models.SessionRecord.user_id == user_id)
        .order_by(desc(models.SessionRecord.created_at))
        .limit(5)
        .all()
    )
    lesson_plan = (
        db.query(models.LessonPlan)
        .filter(models.LessonPlan.user_id == user_id)
        .order_by(desc(models.LessonPlan.created_at))
        .first()
    )

    return MemoryResponse(
        user_id=user.id,
        learner_level=user.mandarin_level,
        native_language=user.native_language,
        active_weaknesses=[_to_active_weakness_response(weakness) for weakness in weaknesses],
        recent_sessions=[_to_session_summary_response(session) for session in sessions],
        latest_lesson_plan=_to_lesson_plan_response(lesson_plan) if lesson_plan else None,
    )


def save_session(
    db: Session,
    user_id: str,
    scenario: str,
    transcript: str,
    tutor_reply: str,
    summary: str,
    audio_path: str,
) -> models.SessionRecord:
    """Persist one voice-chat session and return the stored row."""
    session = models.SessionRecord(
        user_id=user_id,
        scenario=scenario,
        transcript=transcript,
        tutor_reply=tutor_reply,
        summary=summary,
        audio_path=audio_path,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def save_mistakes(
    db: Session,
    user_id: str,
    session_id: int,
    mistakes: list[MistakeAnalysis],
) -> list[models.Mistake]:
    """Persist validated Qwen mistake rows for a session."""
    stored_mistakes = [
        models.Mistake(
            user_id=user_id,
            session_id=session_id,
            mistake_type=mistake.type.value,
            weakness_category=mistake.weakness_category.value,
            target=mistake.target,
            severity=mistake.severity,
            feedback=mistake.feedback,
            example_sentence=mistake.example_sentence,
            recommended_drill=mistake.recommended_drill,
        )
        for mistake in mistakes
    ]
    db.add_all(stored_mistakes)
    db.commit()
    for mistake in stored_mistakes:
        db.refresh(mistake)
    return stored_mistakes


def update_active_weaknesses(
    db: Session,
    user_id: str,
    mistakes: list[MistakeAnalysis],
) -> list[models.ActiveWeakness]:
    """Update the longitudinal weakness memory from validated mistakes."""
    updated_weaknesses: list[models.ActiveWeakness] = []
    for mistake in mistakes:
        weakness = _get_weakness_by_category(db, user_id, mistake.weakness_category)
        if weakness is None:
            weakness = _create_active_weakness(user_id, mistake)
            db.add(weakness)
        else:
            _apply_weakness_score_update(weakness, mistake)
        updated_weaknesses.append(weakness)

    db.commit()
    for weakness in updated_weaknesses:
        db.refresh(weakness)
    return updated_weaknesses


def _get_weakness_by_category(
    db: Session,
    user_id: str,
    category: WeaknessCategory,
) -> models.ActiveWeakness | None:
    """Find an existing weakness row by its validated enum category."""
    return (
        db.query(models.ActiveWeakness)
        .filter(
            models.ActiveWeakness.user_id == user_id,
            models.ActiveWeakness.weakness_category == category.value,
        )
        .first()
    )


def _create_active_weakness(
    user_id: str,
    mistake: MistakeAnalysis,
) -> models.ActiveWeakness:
    """Create a new weakness row from the first observed mistake."""
    severity_score = float(mistake.severity)
    return models.ActiveWeakness(
        user_id=user_id,
        weakness_category=mistake.weakness_category.value,
        weakness_name=WEAKNESS_NAMES[mistake.weakness_category],
        severity_score=severity_score,
        times_failed=1,
        status=_status_for_score(severity_score).value,
        recommended_drill=mistake.recommended_drill,
        last_seen=utc_now(),
    )


def _apply_weakness_score_update(
    weakness: models.ActiveWeakness,
    mistake: MistakeAnalysis,
) -> None:
    """Apply the custom longitudinal recurrence scoring formula."""
    weakness.times_failed += 1
    recurrence_bonus = min(weakness.times_failed / 5, 1.0)
    weighted_score = (
        weakness.severity_score * 0.65
        + mistake.severity * 0.25
        + recurrence_bonus * 0.10
    )
    new_score = min(
        5.0,
        max(float(mistake.severity), weighted_score),
    )
    weakness.severity_score = round(new_score, 2)
    weakness.status = _status_for_score(new_score).value
    weakness.recommended_drill = mistake.recommended_drill
    weakness.last_seen = utc_now()


def _status_for_score(score: float) -> WeaknessStatus:
    """Map a numeric weakness score into the public status enum."""
    if score >= 4.0:
        return WeaknessStatus.ACTIVE
    if score >= 2.5:
        return WeaknessStatus.IMPROVING
    return WeaknessStatus.RESOLVED


def _to_active_weakness_response(
    weakness: models.ActiveWeakness,
) -> ActiveWeaknessResponse:
    """Convert a database weakness row into the API response schema."""
    return ActiveWeaknessResponse(
        weakness_category=WeaknessCategory(weakness.weakness_category),
        weakness_name=weakness.weakness_name,
        severity_score=weakness.severity_score,
        times_failed=weakness.times_failed,
        status=WeaknessStatus(weakness.status),
        recommended_drill=weakness.recommended_drill,
        last_seen=weakness.last_seen,
    )


def _to_session_summary_response(session: models.SessionRecord) -> SessionSummaryResponse:
    """Convert a database session row into the memory summary schema."""
    return SessionSummaryResponse(
        id=session.id,
        scenario=session.scenario,
        transcript=session.transcript,
        tutor_reply=session.tutor_reply,
        summary=session.summary,
        created_at=session.created_at,
    )


def _to_lesson_plan_response(lesson_plan: models.LessonPlan) -> LessonPlanResponse:
    """Convert a persisted lesson plan into the API response schema."""
    return LessonPlanResponse(
        user_id=lesson_plan.user_id,
        focus_area=lesson_plan.focus_area,
        recommended_drill=lesson_plan.recommended_drill,
        next_scenario=lesson_plan.next_scenario,
        target_words=lesson_plan.target_words,
        created_at=lesson_plan.created_at,
    )
