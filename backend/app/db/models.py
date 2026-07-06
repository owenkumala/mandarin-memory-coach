"""SQLAlchemy ORM models for learner memory, sessions, and lesson plans."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for persisted rows."""
    return datetime.now(UTC)


class User(Base):
    """Learner account used to group sessions and long-term memory."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    native_language: Mapped[str] = mapped_column(String, nullable=False)
    mandarin_level: Mapped[str] = mapped_column(String, nullable=False)
    learning_goal: Mapped[str] = mapped_column(String, nullable=False)
    preferred_explanation_language: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    sessions: Mapped[list["SessionRecord"]] = relationship(back_populates="user")
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="user")
    active_weaknesses: Mapped[list["ActiveWeakness"]] = relationship(back_populates="user")
    lesson_plans: Mapped[list["LessonPlan"]] = relationship(back_populates="user")


class SessionRecord(Base):
    """One voice-chat turn, including transcript and tutor response."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    scenario: Mapped[str] = mapped_column(String, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    tutor_reply: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    audio_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="sessions")
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="session")


class Mistake(Base):
    """Structured Mandarin mistake returned by Qwen analysis."""

    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), index=True)
    mistake_type: Mapped[str] = mapped_column(String, nullable=False)
    weakness_category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    example_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_drill: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="mistakes")
    session: Mapped[SessionRecord] = relationship(back_populates="mistakes")


class ActiveWeakness(Base):
    """Longitudinal memory row for a recurring learner weakness."""

    __tablename__ = "active_weaknesses"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "weakness_category",
            name="uq_active_weakness_user_category",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    weakness_category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    weakness_name: Mapped[str] = mapped_column(String, nullable=False)
    severity_score: Mapped[float] = mapped_column(Float, nullable=False)
    times_failed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    recommended_drill: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="active_weaknesses")


class LessonPlan(Base):
    """Persisted recommendation for the learner's next Mandarin drill."""

    __tablename__ = "lesson_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    focus_area: Mapped[str] = mapped_column(String, nullable=False)
    recommended_drill: Mapped[str] = mapped_column(Text, nullable=False)
    next_scenario: Mapped[str] = mapped_column(String, nullable=False)
    target_words: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="lesson_plans")
