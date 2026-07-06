"""Versioned API router that aggregates all v1 endpoint modules."""

from fastapi import APIRouter

from app.api.v1.endpoints import health, lesson_plan, memory, voice_chat

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(voice_chat.router)
api_router.include_router(memory.router)
api_router.include_router(lesson_plan.router)
