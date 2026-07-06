"""Memory endpoint for learner weaknesses, sessions, and next lesson."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas import MemoryResponse
from app.services.memory_service import get_memory

router = APIRouter(tags=["memory"])


@router.get("/memory/{user_id}", response_model=MemoryResponse)
def read_memory(user_id: str, db: Session = Depends(get_db)) -> MemoryResponse:
    """Return the current working memory and recent raw-memory summary."""
    return get_memory(db, user_id=user_id)
