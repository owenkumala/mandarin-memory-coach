"""Endpoint tests for the fake-Qwen SpeakHan backend MVP."""

import os
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.gettempdir()) / "speakh_backend_tests"
shutil.rmtree(TEST_ROOT, ignore_errors=True)
TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'memory_test.db'}"
os.environ["STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["USER_AUDIO_DIR"] = str(TEST_ROOT / "storage" / "user_audio")
os.environ["TUTOR_AUDIO_DIR"] = str(TEST_ROOT / "storage" / "tutor_audio")
os.environ["USE_FAKE_QWEN"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.schemas import MistakeAnalysis, MistakeType, WeaknessCategory  # noqa: E402
from app.services.memory_service import (  # noqa: E402
    get_or_create_user,
    update_active_weaknesses,
)


def _post_voice_chat(client: TestClient, user_id: str) -> dict:
    """Post a dummy audio file and return the parsed JSON response."""
    response = client.post(
        "/api/v1/voice-chat",
        data={
            "user_id": user_id,
            "scenario": "restaurant ordering",
            "level": "HSK1 beginner",
        },
        files={"audio": ("sample.webm", b"fake audio bytes", "audio/webm")},
    )
    assert response.status_code == 200
    return response.json()


def test_health_returns_backend_status() -> None:
    """GET /health returns the API status and fake Qwen mode."""
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["use_fake_qwen"] is True
    assert body["database_type"] == "sqlite"


def test_voice_chat_works_with_fake_qwen() -> None:
    """POST /voice-chat runs the fake pipeline and stores memory."""
    with TestClient(app) as client:
        body = _post_voice_chat(client, "demo-user-voice")

    assert body["transcript"] == "我想吃中国菜"
    assert body["memory_updated"] is True
    assert body["feedback"]["fluency_score"] == 65
    assert len(body["memory_after"]["active_weaknesses"]) == 2


def test_memory_returns_active_weaknesses_after_voice_chat() -> None:
    """GET /memory/{user_id} returns weaknesses after a voice-chat turn."""
    user_id = "demo-user-memory"
    with TestClient(app) as client:
        _post_voice_chat(client, user_id)
        response = client.get(f"/api/v1/memory/{user_id}")

    assert response.status_code == 200
    body = response.json()
    categories = {
        weakness["weakness_category"] for weakness in body["active_weaknesses"]
    }
    assert "zh_ch_confusion" in categories
    assert "sentence_length" in categories
    assert body["latest_lesson_plan"]["next_scenario"] == "restaurant ordering"


def test_second_voice_chat_uses_memory_in_tutor_reply() -> None:
    """The second voice-chat response references prior active weaknesses."""
    user_id = "demo-user-repeat"
    with TestClient(app) as client:
        _post_voice_chat(client, user_id)
        second_response = _post_voice_chat(client, user_id)

    assert "欢迎回来" in second_response["tutor_reply"]
    assert "我记得你之前需要练习" in second_response["tutor_reply"]
    assert second_response["memory_before"]["active_weaknesses"]


def test_repeated_mistake_score_stays_at_or_above_latest_severity() -> None:
    """Repeated mistakes keep the weakness score at least at latest severity."""
    user_id = "demo-user-scoring"
    mistake = MistakeAnalysis(
        type=MistakeType.PRONUNCIATION,
        weakness_category=WeaknessCategory.ZH_CH_CONFUSION,
        target="中国菜 / 吃",
        severity=4,
        feedback="Practice separating zh from ch.",
        example_sentence="我想吃中国菜。",
        recommended_drill="Repeat 中国菜 and 想吃 in full sentences.",
    )

    db = SessionLocal()
    try:
        get_or_create_user(db, user_id=user_id, mandarin_level="HSK1 beginner")
        update_active_weaknesses(db, user_id=user_id, mistakes=[mistake])
        updated_weaknesses = update_active_weaknesses(
            db,
            user_id=user_id,
            mistakes=[mistake],
        )
    finally:
        db.close()

    assert updated_weaknesses[0].times_failed == 2
    assert updated_weaknesses[0].severity_score >= mistake.severity
