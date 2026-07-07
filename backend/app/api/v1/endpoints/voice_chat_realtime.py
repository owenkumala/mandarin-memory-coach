"""Realtime voice-chat WebSocket endpoint for progressive pipeline events."""

import logging

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.realtime_voice_service import run_realtime_voice_websocket

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice-chat"])


@router.websocket("/voice-chat/realtime")
async def voice_chat_realtime(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    """Delegate realtime voice-chat WebSocket orchestration to the service layer."""
    await run_realtime_voice_websocket(websocket=websocket, db=db)
