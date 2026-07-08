"""Realtime WebSocket and sentence-TTS tests for the backend voice pipeline."""

import asyncio
import base64
import logging
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.schemas import AnalysisResponse
from app.services import realtime_voice_service
from app.services.qwen_client import QwenClient
from app.services.realtime_asr_service import sanitize_realtime_audio_metadata
from app.services.sentence_tts_pipeline import (
    DEFAULT_REALTIME_TTS_MAX_CONCURRENCY,
    SentenceTtsPipeline,
    realtime_tts_max_concurrency,
    split_complete_sentences,
)
from conftest import TEST_ROOT


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


def _realtime_test_settings(use_fake_tts: bool, suffix: str) -> Settings:
    """Return isolated storage settings for realtime WebSocket tests."""
    return Settings(
        USE_FAKE_QWEN=True,
        USE_FAKE_TTS=use_fake_tts,
        DATABASE_URL=os.environ["DATABASE_URL"],
        STORAGE_DIR=os.environ["STORAGE_DIR"],
        USER_AUDIO_DIR=os.environ["USER_AUDIO_DIR"],
        TUTOR_AUDIO_DIR=str(TEST_ROOT / "storage" / f"tutor_audio_{suffix}"),
    )


def _send_fake_audio_turn(websocket: object, user_id: str) -> None:
    """Send a minimal realtime audio turn through the test WebSocket."""
    websocket.send_json({"type": "start", "user_id": user_id})
    websocket.send_json(
        {
            "type": "audio_chunk",
            "audio_base64": base64.b64encode(b"fake audio").decode("ascii"),
        }
    )
    websocket.send_json({"type": "end_audio"})


def _write_cached_fast_ack(settings: Settings) -> None:
    """Create the shared fast-ack cache file for cached-path tests."""
    cached_path = Path(settings.TUTOR_AUDIO_DIR) / "_shared" / "realtime-fast-ack.mp3"
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"cached fast ack audio")


def test_realtime_voice_chat_accepts_hsk3_and_emits_ordered_events(
    caplog,
    monkeypatch,
) -> None:
    """WS /voice-chat/realtime streams events and passes HSK3 into Qwen calls."""
    captured_levels = {}

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

    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with caplog.at_level(logging.INFO):
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
    assert events[0]["payload"]["asr_mode"] == "buffered_fallback"
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
    assert events[0]["payload"]["level"] == "HSK3 lower intermediate"
    memory_event = _first_event(events, "memory_updated")
    assert memory_event["payload"]["memory_after"]["learner_level"] == (
        "HSK3 lower intermediate"
    )
    assert "realtime.asr_buffer_bytes=10 chunks=1" in caplog.text
    assert "realtime.asr_audio_filename=realtime.webm" in caplog.text
    assert "realtime.asr_audio_extension=.webm" in caplog.text
    assert "realtime.asr_save_audio_seconds=" in caplog.text
    assert "realtime.asr_transcribe_seconds=" in caplog.text
    assert "realtime.summary asr_total=" in caplog.text
    assert "asr_mode=buffered_fallback" in caplog.text
    done_timings = events[-1]["payload"]["timings"]
    assert done_timings["asr_mode"] == "buffered_fallback"
    assert done_timings["audio_ref_mode"] == get_settings().QWEN_ASR_AUDIO_REF_MODE
    assert done_timings["asr_total"] is not None
    assert done_timings["first_token"] is not None
    assert done_timings["analysis"] is not None
    assert done_timings["done"] is not None
    assert done_timings["tts_chunks"] >= 1


def test_realtime_voice_chat_preserves_mp3_audio_metadata(monkeypatch) -> None:
    """Realtime start metadata preserves MP3 extension for saved ASR audio."""
    captured_audio_paths = []

    async def fake_transcribe_audio(self: QwenClient, audio_path: str) -> str:
        """Capture the saved ASR path without calling live Qwen."""
        captured_audio_paths.append(audio_path)
        assert Path(audio_path).exists()
        return "我想点菜"

    monkeypatch.setattr(QwenClient, "transcribe_audio", fake_transcribe_audio)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "user_id": "demo-user-realtime-mp3",
                    "audio_filename": "sample-mandarin.mp3",
                    "audio_mime_type": "audio/mpeg",
                }
            )
            websocket.send_json(
                {
                    "type": "audio_chunk",
                    "audio_base64": base64.b64encode(b"fake mp3 bytes").decode("ascii"),
                }
            )
            websocket.send_json({"type": "end_audio"})
            events = _receive_realtime_events_until_done(websocket)

    assert events[-1]["type"] == "done"
    assert captured_audio_paths
    assert Path(captured_audio_paths[0]).suffix == ".mp3"


def test_realtime_audio_metadata_sanitizer_falls_back_safely() -> None:
    """Unsupported or unsafe realtime filenames fall back to webm metadata."""
    assert sanitize_realtime_audio_metadata(
        "../../bad.exe",
        "application/x-msdownload",
    ) == ("realtime.webm", "audio/webm")
    assert sanitize_realtime_audio_metadata(
        "..\\sample.mp3",
        "audio/webm",
    ) == ("sample.mp3", "audio/mpeg")
    assert sanitize_realtime_audio_metadata(None, None) == (
        "realtime.webm",
        "audio/webm",
    )


def test_realtime_voice_chat_defaults_missing_level_to_hsk1(monkeypatch) -> None:
    """Realtime start messages default to HSK1 when level is omitted."""
    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)

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


def test_realtime_cached_fast_ack_audio_emits_before_tutor_token(monkeypatch) -> None:
    """Cached fast ack audio emits immediately after ASR final before model tokens."""
    settings = _realtime_test_settings(use_fake_tts=False, suffix="fast_ack_cached")
    _write_cached_fast_ack(settings)

    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield one model sentence after cached fast ack has been emitted."""
        yield "在餐厅里，说您好更自然。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return deterministic structured feedback without live Qwen."""
        return AnalysisResponse(
            mistakes=[],
            fluency_score=84,
            confidence_score=80,
            summary="Cached fast ack analysis",
            next_focus="restaurant greeting",
            next_drill="Practice greeting before ordering.",
        )

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Write model audio while ensuring the cached ack is not regenerated."""
        assert "realtime-fast-ack" not in output_path
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(realtime_voice_service, "get_settings", lambda: settings)
    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            _send_fake_audio_turn(websocket, "demo-user-fast-ack-cached")
            events = _receive_realtime_events_until_done(websocket)

    event_types = [event["type"] for event in events]
    audio_events = [event for event in events if event["type"] == "audio_chunk_ready"]
    assert event_types.index("asr_final") < event_types.index("tutor_sentence")
    assert event_types.index("audio_chunk_ready") < event_types.index("tutor_token")
    assert audio_events[0]["payload"]["sequence"] == 0
    assert audio_events[0]["payload"]["source"] == "fast_ack"
    assert audio_events[0]["payload"]["audio_url"].endswith(
        "/_shared/realtime-fast-ack.mp3"
    )


def test_realtime_non_cached_fast_ack_generates_in_background(monkeypatch) -> None:
    """Non-cached fast ack is generated asynchronously and normal audio continues."""
    settings = _realtime_test_settings(use_fake_tts=False, suffix="fast_ack_generated")

    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield one model sentence while fast ack generation is in flight."""
        yield "在餐厅里，说您好更自然。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return deterministic structured feedback without live Qwen."""
        return AnalysisResponse(
            mistakes=[],
            fluency_score=84,
            confidence_score=80,
            summary="Generated fast ack analysis",
            next_focus="restaurant greeting",
            next_drill="Practice greeting before ordering.",
        )

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Write fast ack and model chunks without calling live Qwen TTS."""
        if "realtime-fast-ack" not in output_path:
            await asyncio.sleep(0.02)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(realtime_voice_service, "get_settings", lambda: settings)
    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            _send_fake_audio_turn(websocket, "demo-user-fast-ack-generated")
            events = _receive_realtime_events_until_done(websocket)

    sentence_events = [event for event in events if event["type"] == "tutor_sentence"]
    audio_events = [event for event in events if event["type"] == "audio_chunk_ready"]
    assert sentence_events[0]["payload"] == {
        "sequence": 0,
        "text": "我来帮你改一句。",
        "source": "fast_ack",
    }
    assert any(
        event["payload"]["sequence"] == 0
        and event["payload"].get("source") == "fast_ack"
        for event in audio_events
    )
    assert any(event["payload"]["sequence"] == 1 for event in audio_events)
    assert events[-1]["type"] == "done"


def test_realtime_fast_ack_failure_does_not_break_session(monkeypatch) -> None:
    """Fast ack TTS failure is skipped while model-generated audio continues."""
    settings = _realtime_test_settings(use_fake_tts=False, suffix="fast_ack_failure")

    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield one model sentence for normal TTS after ack failure."""
        yield "请说：您好，我想点菜。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return deterministic structured feedback without live Qwen."""
        return AnalysisResponse(
            mistakes=[],
            fluency_score=80,
            confidence_score=80,
            summary="Fast ack failure analysis",
            next_focus="ordering sentence",
            next_drill="Practice one complete ordering sentence.",
        )

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Fail only the shared fast ack audio generation."""
        if "realtime-fast-ack" in output_path:
            raise ValueError("Qwen TTS request failed.")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(realtime_voice_service, "get_settings", lambda: settings)
    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            _send_fake_audio_turn(websocket, "demo-user-fast-ack-fail")
            events = _receive_realtime_events_until_done(websocket)

    audio_sequences = [
        event["payload"]["sequence"]
        for event in events
        if event["type"] == "audio_chunk_ready"
    ]
    assert 0 not in audio_sequences
    assert 1 in audio_sequences
    assert events[-1]["type"] == "done"


def test_realtime_fake_tts_skips_fast_ack_sequence_zero(monkeypatch) -> None:
    """Fake TTS mode skips sequence-0 fast ack and keeps normal flow working."""
    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            _send_fake_audio_turn(websocket, "demo-user-fast-ack-fake")
            events = _receive_realtime_events_until_done(websocket)

    assert not any(
        event["type"] in {"tutor_sentence", "audio_chunk_ready"}
        and event["payload"].get("sequence") == 0
        for event in events
    )
    assert events[-1]["type"] == "done"


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
            _send_fake_audio_turn(websocket, "demo-user-realtime-fast-feedback")
            events = _receive_realtime_events_until_done(websocket)

    event_types = [event["type"] for event in events]
    assert event_types.index("feedback_ready") < event_types.index("audio_chunk_ready")
    assert event_types.index("memory_updated") < event_types.index("audio_chunk_ready")
    assert event_types[-1] == "done"


def test_realtime_analysis_json_failure_uses_warning_fallback(monkeypatch) -> None:
    """Malformed structured analysis JSON does not fail the realtime session."""
    settings = _realtime_test_settings(use_fake_tts=False, suffix="analysis_fallback")

    async def fake_stream_tutor_reply(
        self: QwenClient,
        transcript: str,
        memory: object,
        scenario: str,
        level: str,
    ):
        """Yield a normal spoken tutor sentence while analysis fails."""
        yield "点餐时说：您好，我想点菜。"

    async def fake_analyze_mistakes(
        self: QwenClient,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Simulate the strict parser rejecting malformed Qwen JSON."""
        raise ValueError("Qwen analysis response was not valid JSON.")

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Write fake audio so the session still produces playable chunks."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    monkeypatch.setattr(realtime_voice_service, "get_settings", lambda: settings)
    monkeypatch.setattr(QwenClient, "transcribe_audio", _fake_realtime_transcribe_audio)
    monkeypatch.setattr(QwenClient, "stream_tutor_reply", fake_stream_tutor_reply)
    monkeypatch.setattr(QwenClient, "analyze_mistakes", fake_analyze_mistakes)
    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/voice-chat/realtime") as websocket:
            _send_fake_audio_turn(websocket, "demo-user-analysis-fallback")
            events = _receive_realtime_events_until_done(websocket)

    warning_events = [
        event
        for event in events
        if event["type"] == "error"
        and event["payload"]["code"] == "analysis_failed"
    ]
    assert warning_events == [
        {
            "type": "error",
            "payload": {
                "severity": "warning",
                "code": "analysis_failed",
                "message": "Structured feedback could not be generated for this turn.",
            },
        }
    ]
    assert not any(
        event["type"] == "error"
        and event["payload"]["code"] == "realtime_pipeline_failed"
        for event in events
    )
    event_types = [event["type"] for event in events]
    assert "tutor_token" in event_types
    assert "audio_chunk_ready" in event_types
    assert "feedback_ready" in event_types
    assert "memory_updated" in event_types
    assert event_types[-1] == "done"
    feedback = _first_event(events, "feedback_ready")["payload"]["feedback"]
    assert feedback["mistakes"] == []
    assert feedback["summary"] == (
        "Structured feedback could not be generated reliably for this turn."
    )
    assert feedback["next_focus"] == "Repeat the corrected phrase."


def test_sentence_tts_splitter_detects_chinese_and_english_punctuation() -> None:
    """Sentence splitting detects Chinese punctuation and common English endings."""
    text = "你好！我想点菜。Can I order? unfinished"
    sentences, remainder = split_complete_sentences(text)

    assert sentences == ["你好！", "我想点菜。", "Can I order?"]
    assert remainder == " unfinished"


def test_sentence_tts_splitter_keeps_chinese_quotes_together() -> None:
    """Quoted punctuation stays inside one clean sentence chunk."""
    text = "在餐厅点餐时，我们一般不说“你叫什么名字？”，而是说“我要点菜。”"

    sentences, remainder = split_complete_sentences(text)

    assert sentences == [text]
    assert remainder == ""


def test_sentence_tts_splitter_waits_for_streamed_closing_quote() -> None:
    """A boundary waits when a closing quote may arrive in the next chunk."""
    sentences, remainder = split_complete_sentences("你可以说“我要点菜。")

    assert sentences == []
    assert remainder == "你可以说“我要点菜。"

    sentences, remainder = split_complete_sentences(f'{remainder}”')

    assert sentences == ['你可以说“我要点菜。”']
    assert remainder == ""


def test_sentence_tts_flush_ignores_quote_only_fragments() -> None:
    """Quote-only or emoji-only leftovers are not emitted as TTS sentences."""
    pipeline = SentenceTtsPipeline(
        qwen_client=QwenClient(settings=get_settings()),
        settings=get_settings(),
        user_id="demo-user-quote-fragment",
    )
    pipeline._buffer = "”😊"

    assert pipeline.flush() == []


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


def test_realtime_tts_pipeline_defaults_to_single_live_concurrency() -> None:
    """Default realtime TTS concurrency is one for live CosyVoice reliability."""
    pipeline = SentenceTtsPipeline(
        qwen_client=QwenClient(settings=get_settings()),
        settings=get_settings(),
        user_id="demo-user-realtime-default-concurrency",
    )

    assert DEFAULT_REALTIME_TTS_MAX_CONCURRENCY == 1
    assert pipeline._max_concurrency == 1


def test_realtime_tts_pipeline_clamps_zero_concurrency_to_one() -> None:
    """Invalid low realtime TTS concurrency settings clamp to one."""
    settings = Settings(REALTIME_TTS_MAX_CONCURRENCY=0)
    pipeline = SentenceTtsPipeline(
        qwen_client=QwenClient(settings=settings),
        settings=settings,
        user_id="demo-user-realtime-clamped-concurrency",
    )

    assert realtime_tts_max_concurrency(settings) == 1
    assert pipeline._max_concurrency == 1


def test_realtime_tts_pipeline_limits_concurrent_synthesis(monkeypatch) -> None:
    """Custom realtime TTS concurrency allows bounded parallel synthesis."""
    active_calls = 0
    max_active_calls = 0
    settings = Settings(REALTIME_TTS_MAX_CONCURRENCY=2)

    async def fake_synthesize_speech(
        self: QwenClient,
        text: str,
        output_path: str,
    ) -> str:
        """Track concurrent fake TTS calls without touching live Qwen."""
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake realtime tutor audio")
        return str(path)

    async def run_pipeline() -> list[dict]:
        """Start several TTS tasks and drain their generated events."""
        pipeline = SentenceTtsPipeline(
            qwen_client=QwenClient(settings=settings),
            settings=settings,
            user_id="demo-user-realtime-concurrency",
        )
        pipeline.accept_text_chunk("第一句。第二句。第三句。第四句。还有")
        return [event.model_dump(mode="json") for event in await pipeline.drain_all()]

    monkeypatch.setattr(QwenClient, "synthesize_speech", fake_synthesize_speech)

    events = asyncio.run(run_pipeline())

    assert max_active_calls == 2
    assert [event["payload"]["sequence"] for event in events] == [1, 2, 3, 4]


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
            _send_fake_audio_turn(websocket, "demo-user-realtime-tts")
            events = _receive_realtime_events_until_done(websocket)

    warning_events = [
        event
        for event in events
        if event["type"] == "error"
        and event["payload"]["code"] == "tts_sentence_failed"
    ]
    assert warning_events
    assert warning_events[0]["payload"]["sequence"] == 1
    assert _first_event(events, "audio_chunk_ready")["payload"]["sequence"] == 2
    assert events[-1]["type"] == "done"
