"""Endpoint tests for the fake-Qwen SpeakHan backend MVP."""

import asyncio
import base64
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
os.environ["USE_FAKE_TTS"] = "true"

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
from app.services.sentence_tts_pipeline import (  # noqa: E402
    SentenceTtsPipeline,
    split_complete_sentences,
)
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


def _receive_realtime_events_until_done(websocket: object) -> list[dict]:
    """Receive realtime WebSocket events until the terminal done event."""
    events = []
    while True:
        event = websocket.receive_json()
        events.append(event)
        if event["type"] == "done":
            return events


def _first_event(events: list[dict], event_type: str) -> dict:
    """Return the first realtime event with the requested type."""
    for event in events:
        if event["type"] == event_type:
            return event
    raise AssertionError(f"Missing realtime event: {event_type}")


async def _fake_realtime_transcribe_audio(self: QwenClient, audio_path: str) -> str:
    """Return a deterministic transcript without calling live Qwen ASR."""
    assert Path(audio_path).exists()
    return "我想点菜"


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


def test_realtime_voice_chat_accepts_hsk3_and_emits_ordered_events(monkeypatch) -> None:
    """WS /voice-chat/realtime streams events and passes HSK3 into Qwen calls."""
    captured_levels = {}

    async def fake_transcribe_audio(self: QwenClient, audio_path: str) -> str:
        """Return a deterministic transcript without calling live Qwen ASR."""
        assert Path(audio_path).exists()
        return "我想点菜"

    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield deterministic tutor chunks and capture the learner level."""
        captured_levels["stream"] = level
        yield "很好，你可以说：我想点一份中国菜。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return structured feedback and capture the learner level."""
        captured_levels["analysis"] = level
        return AnalysisResponse(
            mistakes=[],
            fluency_score=82,
            confidence_score=78,
            summary=f"Realtime analysis for {level}",
            next_focus="restaurant ordering scenario vocabulary",
            next_drill="Practice ordering one dish and one drink.",
        )

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Write fake sentence audio without calling live Qwen TTS."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(QwenClient, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "user_id": "demo-user-realtime-hsk3",
                    "scenario": "restaurant ordering",
                    "level": "HSK3 lower intermediate",
                }
            )
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "audio_base64": base64.b64encode(b"fake audio").decode("ascii"),
                }
            )
            websocket.send_json({"type": "end_audio"})
            events = _receive_realtime_events_until_done(websocket)

    event_types = [event["type"] for event in events]
    assert event_types[0] == "session_started"
    assert "audio_received" in event_types
    assert "asr_final" in event_types
    assert "tutor_token" in event_types
    assert "tutor_sentence" in event_types
    assert "audio_chunk_ready" in event_types
    assert "feedback_ready" in event_types
    assert "memory_updated" in event_types
    assert event_types[-1] == "done"
    assert event_types.index("asr_final") < event_types.index("tutor_token")
    assert captured_levels == {
        "stream": "HSK3 lower intermediate",
        "analysis": "HSK3 lower intermediate",
    }
    session_event = events[0]
    assert session_event["payload"]["level"] == "HSK3 lower intermediate"
    memory_event = _first_event(events, "memory_updated")
    assert memory_event["payload"]["memory_after"]["learner_level"] == (
        "HSK3 lower intermediate"
    )


def test_realtime_voice_chat_defaults_missing_level_to_hsk1(monkeypatch) -> None:
    """Realtime start messages default to HSK1 when level is omitted."""
    monkeypatch.setattr(
        QwenClient,
        "transcribe_audio",
        _fake_realtime_transcribe_audio,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "user_id": "demo-user-realtime-default-level",
                    "scenario": "restaurant ordering",
                }
            )
            event = websocket.receive_json()

    assert event["type"] == "session_started"
    assert event["payload"]["level"] == "HSK1 beginner"


def test_realtime_feedback_ready_can_emit_before_slow_audio_chunk(monkeypatch) -> None:
    """Structured feedback can emit before a slow final sentence TTS task."""
    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield one complete sentence so TTS can run in the background."""
        yield "很好，你可以说：我想点一份中国菜。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return structured feedback before the mocked TTS task finishes."""
        await asyncio.sleep(0)
        return AnalysisResponse(
            mistakes=[],
            fluency_score=84,
            confidence_score=80,
            summary="Fast realtime analysis",
            next_focus="restaurant ordering",
            next_drill="Practice ordering one dish.",
        )

    async def slow_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Delay TTS enough for feedback_ready to win the event race."""
        await asyncio.sleep(0.05)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", slow_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            websocket.send_json({"type": "start", "user_id": "demo-user-realtime-fast-feedback"})
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "audio_base64": base64.b64encode(b"fake audio").decode("ascii"),
                }
            )
            websocket.send_json({"type": "end_audio"})
            events = _receive_realtime_events_until_done(websocket)

    event_types = [event["type"] for event in events]
    assert event_types.index("feedback_ready") < event_types.index("audio_chunk_ready")
    assert event_types.index("memory_updated") < event_types.index("audio_chunk_ready")
    assert event_types[-1] == "done"


def test_sentence_tts_splitter_detects_chinese_and_english_punctuation() -> None:
    """Sentence splitting detects Chinese punctuation and common English endings."""
    sentences, remainder = split_complete_sentences("你好！我想点菜。Can I order? unfinished")

    assert sentences == ["你好！", "我想点菜。", "Can I order?"]
    assert remainder == " unfinished"


def test_realtime_tts_chunk_paths_are_unique() -> None:
    """Sentence TTS chunk filenames are unique and sequence-prefixed."""
    pipeline = SentenceTtsPipeline(
        qwen_client=QwenClient(settings=get_settings()),
        settings=get_settings(),
        user_id="demo-user-realtime-unique",
    )

    first_path = pipeline._build_chunk_path(1)
    second_path = pipeline._build_chunk_path(1)

    assert first_path != second_path
    assert first_path.parent.name == "demo-user-realtime-unique"
    assert first_path.name.startswith("chunk-1-")
    assert first_path.name.endswith(".mp3")


def test_realtime_tts_failure_sends_warning_and_continues(monkeypatch) -> None:
    """A failed sentence TTS chunk emits an error event without stopping the WS."""
    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield two complete sentences so the second can still produce audio."""
        yield "第一句。第二句。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return minimal structured feedback for the realtime test."""
        return AnalysisResponse(
            mistakes=[],
            fluency_score=80,
            confidence_score=80,
            summary="Realtime analysis",
            next_focus="sentence flow",
            next_drill="Repeat the second sentence.",
        )

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Fail the first sentence and write fake audio for later sentences."""
        if "chunk-1-" in output_path:
            raise ValueError("Qwen TTS request failed.")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            websocket.send_json({"type": "start", "user_id": "demo-user-realtime-tts"})
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "audio_base64": base64.b64encode(b"fake audio").decode("ascii"),
                }
            )
            websocket.send_json({"type": "end_audio"})
            events = _receive_realtime_events_until_done(websocket)

    warning_events = [
        event
        for event in events
        if event["type"] == "error"
        and event["payload"]["code"] == "tts_sentence_failed"
    ]
    assert warning_events
    assert _first_event(events, "audio_chunk_ready")["payload"]["sequence"] == 2
    assert events[-1]["type"] == "done"


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
