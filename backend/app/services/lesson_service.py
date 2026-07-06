"""Lesson-plan persistence and fallback recommendation logic."""

from datetime import UTC, datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import models
from app.schemas import AnalysisResponse, LessonPlanResponse, MemoryResponse

DEFAULT_TARGET_WORDS = ["中国菜", "想吃", "多少钱", "我想喝茶"]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for default lesson responses."""
    return datetime.now(UTC)


def create_lesson_plan(
    db: Session,
    user_id: str,
    analysis: AnalysisResponse,
    memory: MemoryResponse,
    scenario: str,
) -> LessonPlanResponse:
    """Persist and return the next lesson plan after a voice-chat turn."""
    focus_area = analysis.next_focus
    if memory.active_weaknesses:
        focus_area = memory.active_weaknesses[0].weakness_name

    lesson_plan = models.LessonPlan(
        user_id=user_id,
        focus_area=focus_area,
        recommended_drill=analysis.next_drill,
        next_scenario=scenario,
        target_words=DEFAULT_TARGET_WORDS,
    )
    db.add(lesson_plan)
    db.commit()
    db.refresh(lesson_plan)
    return _to_lesson_plan_response(lesson_plan)


def get_latest_or_default_lesson_plan(db: Session, user_id: str) -> LessonPlanResponse:
    """Return the latest saved lesson plan or a starter restaurant drill."""
    lesson_plan = (
        db.query(models.LessonPlan)
        .filter(models.LessonPlan.user_id == user_id)
        .order_by(desc(models.LessonPlan.created_at))
        .first()
    )
    if lesson_plan is not None:
        return _to_lesson_plan_response(lesson_plan)

    return LessonPlanResponse(
        user_id=user_id,
        focus_area="restaurant ordering basics",
        recommended_drill="Practice saying 我想吃中国菜 and 多少钱 in complete sentences.",
        next_scenario="restaurant ordering",
        target_words=DEFAULT_TARGET_WORDS,
        created_at=utc_now(),
    )


def _to_lesson_plan_response(lesson_plan: models.LessonPlan) -> LessonPlanResponse:
    """Convert a lesson-plan ORM row into the public schema."""
    return LessonPlanResponse(
        user_id=lesson_plan.user_id,
        focus_area=lesson_plan.focus_area,
        recommended_drill=lesson_plan.recommended_drill,
        next_scenario=lesson_plan.next_scenario,
        target_words=lesson_plan.target_words,
        created_at=lesson_plan.created_at,
    )
