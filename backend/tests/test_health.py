"""Endpoint tests for the fake-Qwen SpeakHan backend MVP."""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db import models  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import (  # noqa: E402
    AnalysisResponse,
    MistakeAnalysis,
    MistakeType,
    WeaknessCategory,
    WeaknessStatus,
)
from app.services.lesson_service import create_lesson_plan  # noqa: E402
from app.services.memory_service import (  # noqa: E402
    get_memory,
    get_or_create_user,
    update_active_weaknesses,
)
from app.services.qwen_client import QwenClient  # noqa: E402
from app.services.voice_chat_service import _generate_tutor_audio_url  # noqa: E402


def _post_voice_chat(client: TestClient, user_id: str) -> dict:
    """Post a dummy audio file and return the parsed JSON response."""
    response = _voice_chat_response(client, user_id=user_id)
    assert response.status_code == 200
    return response.json()


def _voice_chat_response(
    client: TestClient,
    user_id: str,
    filename: str = "sample.webm",
    content: bytes = b"fake audio bytes",
) -> object:
    """Post audio to voice-chat and return the raw test response."""
    return client.post(
        "/api/v1/voice-chat",
        data={
            "user_id": user_id,
            "scenario": "restaurant ordering",
            "level": "HSK1 beginner",
        },
        files={"audio": (filename, content, "audio/webm")},
    )


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


def test_lesson_plan_returns_default_for_new_user() -> None:
    """GET /lesson-plan/{user_id} returns a starter lesson for new users."""
    with TestClient(app) as client:
        response = client.get("/api/v1/lesson-plan/demo-user-new-lesson")

    assert response.status_code == 200
    body = response.json()
    assert body["focus_area"] == "restaurant ordering basics"
    assert body["next_scenario"] == "restaurant ordering"
    assert "中国菜" in body["target_words"]


def test_lesson_plan_returns_saved_adaptive_lesson_after_voice_chat() -> None:
    """GET /lesson-plan/{user_id} returns the saved adaptive lesson."""
    user_id = "demo-user-adaptive-lesson"
    with TestClient(app) as client:
        _post_voice_chat(client, user_id)
        response = client.get(f"/api/v1/lesson-plan/{user_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["focus_area"] == "zh/ch pronunciation confusion"
    assert body["recommended_drill"] == "Practice 中国菜, 想吃, 多少钱, and 我想喝茶."
    assert body["next_scenario"] == "restaurant ordering"


def test_second_voice_chat_uses_memory_in_tutor_reply() -> None:
    """The second voice-chat response references prior active weaknesses."""
    user_id = "demo-user-repeat"
    with TestClient(app) as client:
        _post_voice_chat(client, user_id)
        second_response = _post_voice_chat(client, user_id)

    assert "欢迎回来" in second_response["tutor_reply"]
    assert "我记得你之前需要练习" in second_response["tutor_reply"]
    assert second_response["memory_before"]["active_weaknesses"]


def test_voice_chat_rejects_empty_audio_file() -> None:
    """POST /voice-chat rejects empty audio uploads with a client error."""
    with TestClient(app) as client:
        response = _voice_chat_response(
            client,
            user_id="demo-user-empty-audio",
            content=b"",
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Audio file is empty."


def test_voice_chat_rejects_unsupported_audio_extension() -> None:
    """POST /voice-chat rejects unsupported upload file extensions."""
    with TestClient(app) as client:
        response = _voice_chat_response(
            client,
            user_id="demo-user-bad-audio",
            filename="sample.txt",
        )

    assert response.status_code == 400
    assert "Unsupported audio extension" in response.json()["detail"]


def test_voice_chat_rejects_oversized_audio_file() -> None:
    """POST /voice-chat rejects uploads larger than the configured limit."""
    with TestClient(app) as client:
        response = _voice_chat_response(
            client,
            user_id="demo-user-large-audio",
            content=b"x" * 5_000_001,
        )

    assert response.status_code == 400
    assert "Audio file is too large" in response.json()["detail"]


def test_voice_chat_returns_tutor_audio_url_when_tts_succeeds(monkeypatch) -> None:
    """POST /voice-chat includes tutor_audio_url when mocked TTS saves audio."""
    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Write fake tutor audio without calling live DashScope TTS."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake tutor audio")
        return str(path)

    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        body = _post_voice_chat(client, "demo-user-tts-url")

    assert body["tutor_audio_url"] is not None
    assert body["tutor_audio_url"].startswith("/storage/tutor_audio/")
    assert body["tutor_audio_url"].endswith(".mp3")


def test_voice_chat_keeps_working_when_tts_fails(monkeypatch) -> None:
    """POST /voice-chat falls back to text response when optional TTS fails."""
    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Simulate a non-live DashScope TTS failure."""
        raise ValueError("Qwen TTS request failed.")

    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        body = _post_voice_chat(client, "demo-user-tts-fallback")

    assert body["transcript"] == "我想吃中国菜"
    assert body["tutor_reply"]
    assert body["tutor_audio_url"] is None
    assert body["memory_updated"] is True


def test_tutor_audio_paths_are_unique(monkeypatch) -> None:
    """Optional TTS writes each generated reply to a unique audio path."""
    generated_paths = []

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Capture generated paths without calling live DashScope TTS."""
        generated_paths.append(output_path)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake tutor audio")
        return str(path)

    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    qwen_client = QwenClient(settings=get_settings())
    first_url = asyncio.run(
        _generate_tutor_audio_url(qwen_client, "你好", "demo-user-unique-tts")
    )
    second_url = asyncio.run(
        _generate_tutor_audio_url(qwen_client, "你好", "demo-user-unique-tts")
    )

    assert first_url != second_url
    assert generated_paths[0] != generated_paths[1]
    for generated_path in generated_paths:
        path = Path(generated_path)
        assert path.parent.name == "demo-user-unique-tts"
        assert path.name.startswith("reply-")
        assert path.name.endswith(".mp3")


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


def test_first_low_severity_hesitation_is_improving_not_resolved() -> None:
    """A newly observed low-severity hesitation remains visible in memory."""
    user_id = "demo-user-low-hesitation"
    mistake = MistakeAnalysis(
        type=MistakeType.HESITATION,
        weakness_category=WeaknessCategory.HESITATION,
        target="呃",
        severity=2,
        feedback="Pause briefly instead of filling with 呃.",
        example_sentence="请问我可以点菜了吗？",
        recommended_drill="Repeat the sentence once with a calm pause before 请问.",
    )

    db = SessionLocal()
    try:
        get_or_create_user(db, user_id=user_id, mandarin_level="HSK1 beginner")
        updated_weaknesses = update_active_weaknesses(
            db,
            user_id=user_id,
            mistakes=[mistake],
        )
    finally:
        db.close()

    assert updated_weaknesses[0].times_failed == 1
    assert updated_weaknesses[0].severity_score == 2.0
    assert updated_weaknesses[0].status == WeaknessStatus.IMPROVING.value


def test_repeated_low_severity_hesitation_never_becomes_resolved() -> None:
    """Repeated low-severity hesitation increments recurrence without resolving."""
    user_id = "demo-user-repeat-hesitation"
    mistake = MistakeAnalysis(
        type=MistakeType.HESITATION,
        weakness_category=WeaknessCategory.HESITATION,
        target="呃",
        severity=2,
        feedback="Try the sentence again without filler sounds.",
        example_sentence="请问我可以点菜了吗？",
        recommended_drill="Say 请问我可以点菜了吗 slowly, then at normal speed.",
    )

    db = SessionLocal()
    try:
        get_or_create_user(db, user_id=user_id, mandarin_level="HSK1 beginner")
        update_active_weaknesses(db, user_id=user_id, mistakes=[mistake])
        second_update = update_active_weaknesses(
            db,
            user_id=user_id,
            mistakes=[mistake],
        )[0]
        second_times_failed = second_update.times_failed
        second_status = second_update.status
        second_score = second_update.severity_score
        third_update = update_active_weaknesses(
            db,
            user_id=user_id,
            mistakes=[mistake],
        )[0]
    finally:
        db.close()

    assert second_times_failed == 2
    assert second_status == WeaknessStatus.IMPROVING.value
    assert 2.2 <= second_score <= 2.5
    assert third_update.times_failed == 3
    assert third_update.status == WeaknessStatus.ACTIVE.value
    assert third_update.status != WeaknessStatus.RESOLVED.value


def test_memory_excludes_resolved_weaknesses_from_active_list() -> None:
    """Resolved rows stay in storage but not in active_weaknesses responses."""
    user_id = "demo-user-resolved-filter"

    db = SessionLocal()
    try:
        get_or_create_user(db, user_id=user_id, mandarin_level="HSK1 beginner")
        db.add(
            models.ActiveWeakness(
                user_id=user_id,
                weakness_category=WeaknessCategory.HESITATION.value,
                weakness_name="hesitation and pauses",
                severity_score=1.5,
                times_failed=1,
                status=WeaknessStatus.RESOLVED.value,
                recommended_drill="Previously resolved drill.",
            )
        )
        db.commit()
        memory = get_memory(db, user_id=user_id)
    finally:
        db.close()

    assert memory.active_weaknesses == []


def test_lesson_plan_next_scenario_preserves_word_spaces() -> None:
    """Lesson-plan creation normalizes whitespace without joining words."""
    user_id = "demo-user-scenario-spacing"
    analysis = AnalysisResponse(
        mistakes=[],
        fluency_score=80,
        confidence_score=75,
        summary="Good short turn.",
        next_focus="restaurant ordering basics",
        next_drill="Practice asking to order.",
    )

    db = SessionLocal()
    try:
        get_or_create_user(db, user_id=user_id, mandarin_level="HSK1 beginner")
        lesson_plan = create_lesson_plan(
            db,
            user_id=user_id,
            analysis=analysis,
            memory=get_memory(db, user_id=user_id),
            scenario="  restaurant   ordering  ",
        )
    finally:
        db.close()

    assert lesson_plan.next_scenario == "restaurant ordering"
