"""Unit tests for the manual realtime WebSocket diagnostic script."""

import base64
import importlib.util
from pathlib import Path


def _load_diagnostic_module():
    """Load the diagnostic script as a module without opening a WebSocket."""
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "check_realtime_voice_ws.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_realtime_voice_ws",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load check_realtime_voice_ws.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_realtime_diagnostic_formats_representative_events() -> None:
    """Diagnostic formatter prints compact event timing lines."""
    diagnostic = _load_diagnostic_module()

    session_line = diagnostic.format_event_line(
        0.0,
        {
            "type": "session_started",
            "payload": {
                "session_id": "abc",
                "user_id": "demo-user",
                "scenario": "restaurant ordering",
                "level": "HSK3 lower intermediate",
                "asr_mode": "buffered_fallback",
            },
        },
    )
    token_line = diagnostic.format_event_line(
        4.1,
        {"type": "tutor_token", "payload": {"text": "很好，你可以说。"}},
    )
    fast_ack_line = diagnostic.format_event_line(
        3.1,
        {
            "type": "audio_chunk_ready",
            "payload": {
                "sequence": 0,
                "source": "fast_ack",
                "audio_url": "/storage/tutor_audio/_shared/realtime-fast-ack.mp3",
            },
        },
    )
    error_line = diagnostic.format_event_line(
        6.0,
        {
            "type": "error",
            "payload": {
                "severity": "warning",
                "code": "tts_sentence_failed",
                "message": "Qwen TTS request failed.",
            },
        },
    )

    assert session_line == (
        "0.00s session_started "
        "payload_keys=session_id,user_id,scenario,level,asr_mode"
    )
    assert token_line == "4.10s tutor_token text=很好，你可以说。"
    assert fast_ack_line == (
        "3.10s audio_chunk_ready sequence=0 source=fast_ack "
        "audio_url=/storage/tutor_audio/_shared/realtime-fast-ack.mp3"
    )
    assert "6.00s error severity=warning code=tts_sentence_failed" in error_line


def test_realtime_diagnostic_builds_base64_audio_chunks() -> None:
    """Audio helper splits bytes into base64 audio_chunk messages."""
    diagnostic = _load_diagnostic_module()

    messages = diagnostic.build_audio_chunk_messages(b"abcdef", chunk_size=2)

    assert [message["type"] for message in messages] == [
        "audio_chunk",
        "audio_chunk",
        "audio_chunk",
    ]
    assert [
        base64.b64decode(message["audio_base64"].encode("ascii"))
        for message in messages
    ] == [b"ab", b"cd", b"ef"]


def test_realtime_diagnostic_start_message_includes_audio_metadata() -> None:
    """Start messages include safe audio filename and inferred MIME metadata."""
    diagnostic = _load_diagnostic_module()

    mp3_message = diagnostic.build_start_message(
        "demo-user",
        "restaurant ordering",
        "HSK3 lower intermediate",
        "../sample-mandarin.mp3",
    )
    m4a_message = diagnostic.build_start_message(
        "demo-user",
        "restaurant ordering",
        "HSK3 lower intermediate",
        "sample-mandarin.m4a",
    )

    assert mp3_message["audio_filename"] == "sample-mandarin.mp3"
    assert mp3_message["audio_mime_type"] == "audio/mpeg"
    assert m4a_message["audio_filename"] == "sample-mandarin.m4a"
    assert m4a_message["audio_mime_type"] == "audio/mp4"


def test_realtime_diagnostic_rejects_missing_audio_file(tmp_path) -> None:
    """Missing default or user-provided audio paths fail with a useful message."""
    diagnostic = _load_diagnostic_module()

    missing_path = tmp_path / "missing.mp3"

    try:
        diagnostic.read_audio_file(str(missing_path))
    except FileNotFoundError as exc:
        assert "Pass --audio with a valid file" in str(exc)
    else:
        raise AssertionError("Expected missing audio file to fail")
