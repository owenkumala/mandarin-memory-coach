"""Lesson-plan endpoint for retrieving the learner's next speaking drill."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas import LessonPlanResponse
from app.services.lesson_service import get_latest_or_default_lesson_plan

router = APIRouter(tags=["lesson-plan"])


@router.get("/lesson-plan/{user_id}", response_model=LessonPlanResponse)
def get_lesson_plan(user_id: str, db: Session = Depends(get_db)) -> LessonPlanResponse:
    """Return the latest lesson plan, or a starter plan for a new learner."""
    return get_latest_or_default_lesson_plan(db, user_id=user_id)
